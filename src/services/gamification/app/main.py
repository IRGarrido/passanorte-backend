"""App FastAPI do serviço gamification (T011)."""

from fastapi import FastAPI

from services.gamification.app.api import enrollments
from services.gamification.app.core.rewards import reconcile_route
from services.validation.app.api import internal, visits
from shared.app import create_app
from shared.messaging import ConsumerSpec


def create_test_app() -> FastAPI:
    """App completo para testes de contrato (dependências sobrescritáveis)."""
    return create_app(
        "gamification", routers=[enrollments.router, visits.router],
        consumers=[ConsumerSpec("gamification", "catalog.route_changed", reconcile_route, transactional=True)],
        development_routers=[internal.router],
    )


app = create_test_app()
