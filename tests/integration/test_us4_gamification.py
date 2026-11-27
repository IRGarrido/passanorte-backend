from fastapi.testclient import TestClient

from services.benefits.app.api.partners import get_db as get_benefits_db
from services.benefits.app.main import app as benefits_app
from services.catalog.app.models.spot import Category, TouristSpot
from services.gamification.app.core import rewards
from services.gamification.app.core.deps import get_db, get_route_lookup
from services.gamification.app.main import create_test_app
from services.gamification.app.models.enrollment import RouteCompletion
from services.validation.app.core.deps import get_catalog_snapshot
from services.validation.app.core.deps import get_db as get_visits_db
from shared.errors import ApiError
from shared.security import create_access_token


def headers(role, user):
    token, _ = create_access_token(user, role)
    return {"Authorization": f"Bearer {token}"}


def test_checkin_reconciles_two_routes_and_never_repeats_credit(
    db_session, connect_route_services, monkeypatch, events,
):
    db_session.add_all([
        Category(id="theme", name="Cultura"),
        *(TouristSpot(id=key, name=key, description=key, latitude=0, longitude=0) for key in ("a", "b", "c", "d")),
    ])
    db_session.commit()
    app = create_test_app()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_visits_db] = lambda: db_session
    app.dependency_overrides[get_catalog_snapshot] = lambda: lambda _: {
        "latitude": 0, "longitude": 0, "status": "open", "tolerance_radius_m": 100,
    }
    catalog, game = connect_route_services(app)
    benefits_app.dependency_overrides[get_benefits_db] = lambda: db_session
    benefits = TestClient(benefits_app)
    admin, tourist = headers("admin", "admin"), headers("tourist", "tourist")

    def visit(point):
        return game.post("/api/v1/visits", headers=tourist, json={
            "tourist_spot_id": point, "latitude": 0, "longitude": 0, "accuracy_m": 4,
        })

    def route(name, points, amount):
        response = catalog.post("/api/v1/routes", headers=admin, json={
            "name": name, "points": points, "category_ids": ["theme"], "reward_amount": amount,
        })
        assert response.status_code == 201, response.text
        return response.json()["id"]

    def balance():
        return benefits.get("/api/v1/me/balance", headers=tourist).json()["balance"]

    try:
        assert visit("a").json()["balance"] == 1
        assert visit("c").json()["balance"] == 2
        routes = [route("A", ["a", "b"], 3), route("C", ["c", "b"], 5)]
        for route_id in routes:
            response = game.post(f"/api/v1/routes/{route_id}/enrollments", headers=tourist)
            assert response.status_code == 201 and response.json()["percent"] == 50
        result = visit("b")
        assert result.status_code == 201, result.text
        assert result.json()["balance"] == 11
        assert len(db_session.query(RouteCompletion).all()) == 2
        assert visit("b").json()["already_visited"] is True
        for route_id in routes:
            assert game.get(f"/api/v1/enrollments/{route_id}", headers=tourist).json()["status"] == "completed"
            assert game.delete(f"/api/v1/enrollments/{route_id}", headers=tourist).status_code == 204
            again = game.post(f"/api/v1/routes/{route_id}/enrollments", headers=tourist)
            assert again.json()["status"] == "completed"
        assert balance() == 11
        assert catalog.delete(f"/api/v1/routes/{routes[0]}", headers=admin).status_code == 204
        lookup = app.dependency_overrides[get_route_lookup]
        monkeypatch.setattr(rewards, "get_route_lookup", lookup)
        rewards.reconcile_route(db_session, {"route_id": routes[0]})
        db_session.commit()
        assert game.get(f"/api/v1/enrollments/{routes[0]}", headers=tourist).status_code == 404
        assert balance() == 11

        changed = route("Mudança", ["a", "c", "d"], 7)
        game.post(f"/api/v1/routes/{changed}/enrollments", headers=tourist).raise_for_status()
        catalog.patch("/api/v1/tourist-spots/d/status", headers=admin,
                      json={"status": "permanently_closed"}).raise_for_status()
        progress = game.get(f"/api/v1/enrollments/{changed}", headers=tourist).json()
        assert progress["percent"] == 100 and progress["status"] == "in_progress"
        from services.benefits.app.api.rewards import apply_rewards

        for _ in range(2):
            rewards.reconcile_route(db_session, {"route_id": changed})
            db_session.commit()
        pending_commands = [event["data"] for event in events if event["type"] == "rewards.requested"
                            and event["data"]["rewards"]["credits"][0]["amount"] == 7]
        assert len(pending_commands) == 1
        apply_rewards(db_session, pending_commands[0])
        db_session.commit()
        assert balance() == 18

        # A confirmed visit outlives loss of the synchronous Benefits connection.
        gateway = app.dependency_overrides[rewards.get_reward_gateway]
        app.dependency_overrides[rewards.get_reward_gateway] = lambda: lambda *_: unavailable()
        other = headers("tourist", "other")
        pending = game.post("/api/v1/visits", headers=other, json={
            "tourist_spot_id": "a", "latitude": 0, "longitude": 0, "accuracy_m": 4,
        })
        assert pending.status_code == 202 and pending.json()["reward_status"] == "pending"
        operation = pending.json()["operation_id"]
        assert game.get(f"/api/v1/reward-operations/{operation}", headers=tourist).status_code == 404
        app.dependency_overrides[rewards.get_reward_gateway] = gateway
        command = next(event["data"] for event in events if event["type"] == "rewards.requested"
                       and event["data"]["rewards"]["user_id"] == "other")
        apply_rewards(db_session, command)
        db_session.commit()
        status = game.get(f"/api/v1/reward-operations/{operation}", headers=other).json()
        assert status["reward_status"] == "confirmed" and status["balance"] == 1
    finally:
        benefits_app.dependency_overrides.clear()


def unavailable():
    raise ApiError("dependency_unavailable", "Beneficios indisponivel.", 503)
