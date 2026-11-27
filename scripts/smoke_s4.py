"""Verify the S4 journey against a running development stack through Kong."""

import argparse
import ssl
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import httpx


def synthetic_cpf(marker: str) -> str:
    digits = f"{int(marker, 16) % 1_000_000_000:09d}"
    if len(set(digits)) == 1:
        digits = f"{digits[:-1]}{(int(digits[-1]) + 1) % 10}"
    for weight in (10, 11):
        remainder = sum(int(value) * (weight - index) for index, value in enumerate(digits)) % 11
        digits += str(0 if remainder < 2 else 11 - remainder)
    return digits


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://localhost:8443")
    parser.add_argument("--ca", type=Path, default=Path("secrets/edge.crt"))
    parser.add_argument("--email", default="admin@example.com")
    parser.add_argument("--password-file", type=Path, default=Path("secrets/admin-password"))
    parser.add_argument("--exercise-outage", action="store_true")
    parser.add_argument("--project")
    args = parser.parse_args()

    tls = ssl.create_default_context(cafile=str(args.ca))
    with httpx.Client(base_url=args.url, verify=tls, timeout=30) as client:
        def login(email: str, password: str) -> dict[str, str]:
            token = client.post("/api/v1/session", json={"email": email, "password": password})
            return {"Authorization": f"Bearer {token.raise_for_status().json()['access_token']}"}

        admin = login(args.email, args.password_file.read_text().strip())
        marker = uuid4().hex
        email, password = f"s4-{marker}@example.com", uuid4().hex
        client.post("/api/v1/tourists", json={
            "name": "Ensaio", "surname": "S4", "email": email, "password": password,
            "phone": "92900000000", "country_of_origin": "Brasil", "cpf": synthetic_cpf(marker),
            "consent_version": "1", "accept_terms": True, "accept_privacy": True,
        }).raise_for_status()
        tourist = login(email, password)
        category = client.get("/api/v1/categories").raise_for_status().json()["items"][0]["id"]
        points = []
        for i in range(4):
            points.append(client.post("/api/v1/tourist-spots", headers=admin, json={
                "name": f"Ensaio S4 {marker}-{i}", "description": "Ponto fictício", "address": "Manaus",
                "latitude": -3.1, "longitude": -60.0, "category_ids": [category],
            }).raise_for_status().json()["id"])

        def visit(point: str) -> httpx.Response:
            return client.post("/api/v1/visits", headers=tourist, json={
                "tourist_spot_id": point, "latitude": -3.1, "longitude": -60.0, "accuracy_m": 5,
            })

        def balance() -> int:
            return client.get("/api/v1/me/balance", headers=tourist).raise_for_status().json()["balance"]

        first = visit(points[0]).raise_for_status().json()
        assert first["reward_status"] == "confirmed"
        unit = first["balance"]
        assert unit > 0
        routes = []
        for index, amount in enumerate((3, 5)):
            route = client.post("/api/v1/routes", headers=admin, json={
                "name": f"Ensaio S4 {marker}-{index}", "points": [points[0], points[1]],
                "category_ids": [category], "reward_amount": amount,
            }).raise_for_status().json()
            routes.append(route["id"])
            client.get(f"/api/v1/routes/{route['id']}").raise_for_status()
            result = client.post(f"/api/v1/routes/{route['id']}/enrollments", headers=tourist)
            assert result.raise_for_status().json()["percent"] == 50

        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(visit, [points[1]] * 20))
        assert sorted(result.status_code for result in results) == [200] * 19 + [201]
        assert len({result.json()["id"] for result in results}) == 1
        assert balance() == 2 * unit + 8
        for route_id in routes:
            url = f"/api/v1/enrollments/{route_id}"
            assert client.get(url, headers=tourist).raise_for_status().json()["status"] == "completed"
            client.delete(url, headers=tourist).raise_for_status()
            client.post(f"/api/v1/routes/{route_id}/enrollments", headers=tourist).raise_for_status()
        assert balance() == 2 * unit + 8

        response = client.patch(f"/api/v1/tourist-spots/{points[2]}/status", headers=admin,
                                json={"status": "permanently_closed"})
        response.raise_for_status()
        assert visit(points[2]).status_code == 422
        assert balance() == 2 * unit + 8

        if args.exercise_outage:
            compose = ["docker", "compose", "--env-file", ".env.example"]
            if args.project:
                compose += ["-p", args.project]
            try:
                subprocess.run([*compose, "stop", "benefits", "rabbitmq"], check=True)
                pending = visit(points[3])
                assert pending.status_code == 202 and pending.json()["reward_status"] == "pending"
                operation = pending.json()["operation_id"]
            finally:
                subprocess.run([*compose, "start", "rabbitmq", "benefits"], check=True)
            for _ in range(90):
                response = client.get(f"/api/v1/reward-operations/{operation}", headers=tourist)
                if response.is_success and response.json()["reward_status"] == "confirmed":
                    break
                time.sleep(1)
            else:
                raise RuntimeError("The reward operation did not converge after broker recovery")
            assert balance() == 3 * unit + 8
            assert visit(points[3]).raise_for_status().json()["balance"] == 3 * unit + 8

    print("S4 concurrent check-in, route completion and ledger checks passed.")


if __name__ == "__main__":
    main()
