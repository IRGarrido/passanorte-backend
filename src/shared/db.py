"""Banco compartilhado: Base declarativa, engine e sessão por serviço (T011).

Cada microsserviço aponta DATABASE_URL para o SEU database (Princípio I).
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from shared.settings import Settings


class Base(DeclarativeBase):
    pass


def database_url() -> str:
    url = Settings.load().database_url.get_secret_value()
    return url


def create_service_engine(echo: bool = False):
    return create_engine(database_url(), echo=echo, pool_pre_ping=True, hide_parameters=True)


def make_session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@lru_cache(maxsize=1)
def service_session_factory() -> sessionmaker[Session]:
    """One pool per service process, shared by HTTP dependencies and consumers."""
    return make_session_factory(create_service_engine())
