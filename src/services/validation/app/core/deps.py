"""Dependências do serviço validation: sessão, JWT e snapshot do catalog (D-05)."""

from __future__ import annotations

from collections.abc import Callable, Generator
from urllib.parse import quote

import jwt
from fastapi import Request
from sqlalchemy.orm import Session

from shared.errors import ApiError
from shared.internal_client import call_internal
from shared.security import decode_token
from shared.settings import Settings


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


def get_catalog_snapshot() -> Callable[[str], dict]:
    """Fetcher do snapshot do ponto no catalog (substituível em testes)."""
    base_url = str(Settings.load().catalog_service_url).rstrip("/")

    def fetch(spot_id: str) -> dict:
        result: dict | None = call_internal(
            base_url, "GET", f"/internal/tourist-spots/{quote(spot_id, safe='')}", missing_ok=True,
        )
        if result is None:
            raise ApiError(code="not_found", message="Ponto turístico não encontrado.", status_code=404)
        return result

    return fetch
