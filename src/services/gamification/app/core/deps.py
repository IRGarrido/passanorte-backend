"""Dependências do serviço gamification: sessão, JWT e visitas validadas (D-13)."""

from __future__ import annotations

from collections.abc import Callable, Generator
from urllib.parse import quote

import jwt
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from shared.errors import ApiError
from shared.internal_client import RouteSnapshot
from shared.security import decode_token


def get_db() -> Generator[Session, None, None]:
    from shared.db import service_session_factory

    factory = service_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


def get_current_user(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise ApiError(code="unauthorized", message="Autenticação necessária.", status_code=401)
    try:
        return decode_token(auth.removeprefix("Bearer ").strip(), expected_type="access")
    except jwt.PyJWTError:
        raise ApiError(code="unauthorized", message="Autenticação necessária.", status_code=401) from None


def require_role(*roles: str) -> Callable:
    def dependency(claims: dict = Depends(get_current_user)) -> dict:
        if claims.get("role") not in roles:
            raise ApiError(code="forbidden", message="Acesso negado para o seu perfil.", status_code=403)
        return claims

    return dependency


def get_route_lookup() -> Callable[[str], RouteSnapshot | None]:
    from shared.internal_client import call_internal
    from shared.settings import Settings

    url = str(Settings.load().catalog_service_url)

    def fetch(route_id: str) -> RouteSnapshot | None:
        data = call_internal(url, "GET", f"/internal/routes/{quote(route_id, safe='')}", missing_ok=True)
        return RouteSnapshot.model_validate(data) if data is not None else None

    return fetch
