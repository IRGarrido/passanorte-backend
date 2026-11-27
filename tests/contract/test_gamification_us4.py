from fastapi.testclient import TestClient

from services.catalog.app.models.spot import Category, TouristSpot
from services.gamification.app.core import deps
from services.gamification.app.main import create_test_app
from shared.security import create_access_token


def headers(role, user_id="user-1"):
    token, _ = create_access_token(user_id, role)
    return {"Authorization": f"Bearer {token}"}


def test_routes_validate_distinct_points_themes_and_rewards(db_session, connect_route_services):
    app = create_test_app()
    app.dependency_overrides[deps.get_db] = lambda: db_session
    catalog, gamification = connect_route_services(app)
    db_session.add_all([
        Category(id="theme", name="Cultura"),
        TouristSpot(id="a", name="A", description="A", latitude=0, longitude=0),
        TouristSpot(id="b", name="B", description="B", latitude=0, longitude=0),
    ])
    db_session.commit()
    payload = {"name": "Rota", "points": ["a", "b"], "category_ids": ["theme"], "reward_amount": 0}
    for invalid in ({"points": ["a", "a"]}, {"points": ["a", "missing"]},
                    {"category_ids": []}, {"category_ids": ["no"]}, {"reward_amount": -1}):
        assert catalog.post("/api/v1/routes", headers=headers("admin"), json={**payload, **invalid}).status_code == 422
    assert catalog.post("/api/v1/routes", headers=headers("tourist"), json=payload).status_code == 403
    response = catalog.post("/api/v1/routes", headers=headers("admin"), json=payload)
    assert response.status_code == 201, response.text
    route = response.json()
    assert catalog.get(f"/api/v1/routes/{route['id']}").json() == route
    assert "prize" not in route
    assert gamification.get("/api/v1/prizes", headers=headers("admin")).status_code == 404
    assert isinstance(gamification, TestClient)
