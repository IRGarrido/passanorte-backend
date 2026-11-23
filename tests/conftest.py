"""Fixtures compartilhadas de teste: banco em memória por serviço (T010).

Cada teste usa um engine SQLite em memória (paridade de comportamento com
PostgreSQL nos limites deste escopo; integração ponta a ponta usa
docker-compose/quickstart). O barramento de eventos (RabbitMQ) é simulado
pelo fixture `events`: captura as publicações e `replay()` entrega os
eventos capturados aos handlers do serviço alvo — "fast-forward do broker".
"""

from __future__ import annotations

import atexit
import os
import secrets
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.orm import Session

sys.path.insert(0, "src")


_test_keys = tempfile.TemporaryDirectory()
atexit.register(_test_keys.cleanup)
_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_key_dir = Path(_test_keys.name)
(_key_dir / "test.pem").write_bytes(_key.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
# Private file outside public directory, preventing accidental exposure to verifiers.
_private = _key_dir / "signing.key"
_private.write_bytes(_key.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
for _name in (
    "DATABASE_URL_FILE", "RABBITMQ_URL", "RABBITMQ_URL_FILE", "JWT_PRIVATE_KEY",
    "PII_ENCRYPTION_KEY_FILE", "PII_HMAC_KEY_FILE",
):
    os.environ.pop(_name, None)
os.environ["JWT_ISSUER"] = "passanorte"
os.environ["JWT_AUDIENCE"] = "passanorte-api"
os.environ["ACCESS_TOKEN_MINUTES"] = "15"
os.environ["REFRESH_TOKEN_DAYS"] = "7"
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["JWT_ACTIVE_KID"] = "test"
os.environ["JWT_PUBLIC_KEYS_DIR"] = str(_key_dir)
os.environ["JWT_PRIVATE_KEY_FILE"] = str(_private)
os.environ["PII_HMAC_KEY"] = secrets.token_urlsafe(48)
os.environ["PII_ENCRYPTION_KEY"] = Fernet.generate_key().decode()


from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from shared import messaging  # noqa: E402
from shared.db import (  # noqa: E402
    Base,  # noqa: E402
    make_session_factory,  # noqa: E402
)

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.fixture
def db_session() -> Iterator[Session]:
    # SQLite em memória compartilhado entre threads (TestClient roda em outra thread)
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def events() -> Iterator[list[dict[str, Any]]]:
    """Captura toda publicação do barramento (RABBITMQ_URL nunca é lido aqui)."""
    published: list[dict[str, Any]] = []

    def capture(event_type: str, data: dict, request_id: str | None) -> None:
        published.append({"type": event_type, "data": data, "request_id": request_id})

    messaging.set_publisher(capture)
    yield published
    messaging.set_publisher(None)


@pytest.fixture
def replay(events: list[dict[str, Any]]) -> Callable[..., None]:
    """Reproduz no serviço alvo os eventos capturados (o broker "acontece")."""

    def apply(service: str, db: Session) -> None:
        rest: list[dict[str, Any]] = []
        for event in events:
            if not _deliver(service, db, event):
                rest.append(event)
        events[:] = rest

    return apply


def _deliver(service: str, db: Session, event: dict[str, Any]) -> bool:
    if service == "insights":
        from services.insights.app.core import handlers as insights_handlers

        if event["type"] == "visit.validated":
            insights_handlers.ingest_visit_fact(db, event["data"])
            return True
        if event["type"] == "access.registered":
            insights_handlers.ingest_access(db, event["data"])
            return True
    elif service == "notifications":
        from services.notifications.app.core import dispatcher

        if event["type"] == "notification.dispatch":
            dispatcher.apply_dispatch(db, event["data"])
            return True
    elif service == "chatbot":
        from services.chatbot.app.core import indexer

        if event["type"] == "catalog.index.refresh":
            indexer.refresh_from_payload(db, event["data"])
            return True
    return False
