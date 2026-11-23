"""Smoke tests against a development S2 stack through Kong."""
from __future__ import annotations

import argparse
import ssl
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://localhost:8443")
    parser.add_argument("--ca", type=Path, default=Path("secrets/edge.crt"))
    parser.add_argument("--email", required=True)
    parser.add_argument("--password-file", type=Path, default=Path("secrets/admin-password"))
    parser.add_argument("--chatbot", action="store_true")
    args = parser.parse_args()
    base = args.url.rstrip("/")
    domains = ["auth", "catalog", "gamification", "benefits", "insights", "notifications"]
    if args.chatbot:
        domains.append("chatbot")
    context = ssl.create_default_context(cafile=str(args.ca))
    with httpx.Client(base_url=base, verify=context, timeout=10) as client:
        for domain in domains:
            schema = client.get(f"/openapi/{domain}.json").raise_for_status().json()
            assert schema["servers"][0]["url"] == base
            assert f"/openapi/{domain}.json" in client.get(f"/docs/{domain}").raise_for_status().text
            assert not any("/internal/" in path for path in schema["paths"])
        response = client.get("/api/v1/categories").raise_for_status()
        assert "items" in response.json() and response.headers.get("X-Request-Id")
        assert client.get("/api/v1/me").status_code == 401
        assert client.get("/api/v1/internal/users/missing").status_code == 404
        token = client.post("/api/v1/session", json={
            "email": args.email, "password": args.password_file.read_text().strip(),
        }).raise_for_status().json()["access_token"]
        authorization = {"Authorization": f"Bearer {token}"}
        client.get("/api/v1/me", headers=authorization).raise_for_status()
        for path in ("balance", "coupons"):
            assert client.get(f"/api/v1/me/{path}").status_code == 401
            response = client.get(f"/api/v1/me/{path}", headers=authorization)
            assert response.status_code == 404 and response.json()["detail"] == "Not Found"
    print("Kong, TLS, Swagger, JWT and S2 route reservation checks passed.")


if __name__ == "__main__":
    main()
