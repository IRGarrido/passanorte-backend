"""Route definitions owned by the catalog."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from services.catalog.app.core.deps import get_db, require_role
from services.catalog.app.models.audit import AuditLog
from services.catalog.app.models.route import Route, RoutePoint
from services.catalog.app.models.spot import Category, SpotStatus, TouristSpot
from shared.audit import record_audit
from shared.errors import ApiError
from shared.internal_client import RouteSnapshot
from shared.messaging import enqueue

router = APIRouter(tags=["routes"])
require_admin = require_role("admin")
Identifier = Annotated[str, StringConstraints(min_length=1, max_length=36)]


class RouteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    points: list[Identifier] = Field(min_length=2, max_length=100)
    category_ids: list[Identifier] = Field(min_length=1, max_length=100)
    reward_amount: int = Field(ge=0, le=2_147_483_647)
    is_active: bool = True


class RouteUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    points: list[Identifier] | None = Field(default=None, min_length=2, max_length=100)
    category_ids: list[Identifier] | None = Field(default=None, min_length=1, max_length=100)
    reward_amount: int | None = Field(default=None, ge=0, le=2_147_483_647)
    is_active: bool | None = None


def _points(route: Route) -> list[str]:
    return [point.tourist_spot_id for point in route.points if point.is_active]


def _body(route: Route) -> dict:
    return {
        "id": route.id, "name": route.name, "description": route.description, "points": _points(route),
        "category_ids": route.category_ids, "reward_amount": route.reward_amount, "is_active": route.is_active,
    }


def route_changed(db: Session, route_id: str) -> None:
    enqueue(db, "catalog.route_changed", {"route_id": route_id})


def _find(db: Session, route_id: str, *, lock: bool = False) -> Route:
    route = db.get(Route, route_id, with_for_update=lock)
    if route is None or route.is_removed:
        raise ApiError("not_found", "Rota nao encontrada.", 404)
    return route


def _validate(db: Session, points: list[str], categories: list[str]) -> None:
    if len(points) < 2 or len(set(points)) != len(points):
        raise ApiError("invalid_route_points", "A rota exige ao menos dois pontos distintos.", 422)
    valid_spots = db.query(TouristSpot.id).filter(
        TouristSpot.id.in_(points), TouristSpot.is_removed.is_(False),
        TouristSpot.status != SpotStatus.permanently_closed,
    ).order_by(TouristSpot.id).with_for_update().all()
    if len(valid_spots) != len(points):
        raise ApiError("invalid_route_points", "Todos os pontos da rota precisam estar disponiveis.", 422)
    active_count = db.query(Category).filter(Category.id.in_(categories), Category.is_active.is_(True)).count()
    if not categories or active_count != len(categories):
        raise ApiError("invalid_categories", "Selecione temas distintos e ativos.", 422)


def _make_points(points: list[str]) -> list[RoutePoint]:
    return [RoutePoint(tourist_spot_id=spot_id, position=index) for index, spot_id in enumerate(points)]


@router.get("/routes")
def list_routes(db: Session = Depends(get_db)) -> dict:
    routes = db.query(Route).options(selectinload(Route.points)).filter(
        Route.is_active.is_(True), Route.is_removed.is_(False),
    ).order_by(Route.name, Route.id)
    items = [_body(route) for route in routes]
    return {"items": items, "total": len(items)}


@router.get("/routes/{route_id}")
def get_route(route_id: str, db: Session = Depends(get_db)) -> dict:
    route = _find(db, route_id)
    if not route.is_active:
        raise ApiError("not_found", "Rota nao encontrada.", 404)
    return _body(route)


@router.get("/admin/routes", dependencies=[Depends(require_admin)])
def list_admin_routes(db: Session = Depends(get_db)) -> dict:
    routes = db.query(Route).options(selectinload(Route.points)).filter(
        Route.is_removed.is_(False),
    ).order_by(Route.name, Route.id)
    return {"items": [_body(route) for route in routes]}


@router.post("/routes", status_code=201)
def create_route(payload: RouteCreate, claims: dict = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    _validate(db, payload.points, payload.category_ids)
    route = Route(**payload.model_dump(exclude={"points"}), points=_make_points(payload.points))
    db.add(route)
    db.flush()
    record_audit(db, AuditLog, actor_id=claims["sub"], action="create_route", entity="route", entity_id=route.id)
    db.commit()
    return _body(route)


@router.patch("/routes/{route_id}")
def update_route(
    route_id: str, payload: RouteUpdate, claims: dict = Depends(require_admin), db: Session = Depends(get_db),
) -> dict:
    route = _find(db, route_id, lock=True)
    if payload.points is not None or payload.category_ids is not None or payload.is_active is True:
        _validate(db, payload.points or _points(route), payload.category_ids or route.category_ids)
    fields = payload.model_dump(exclude_none=True, exclude={"points"})
    if "description" in payload.model_fields_set:
        fields["description"] = payload.description
    for field, value in fields.items():
        setattr(route, field, value)
    if payload.points is not None:
        route.points.clear()
        db.flush()
        route.points = _make_points(payload.points)
    record_audit(db, AuditLog, actor_id=claims["sub"], action="update_route", entity="route", entity_id=route_id)
    route_changed(db, route_id)
    db.commit()
    return _body(route)


@router.delete("/routes/{route_id}", status_code=204)
def remove_route(route_id: str, claims: dict = Depends(require_admin), db: Session = Depends(get_db)) -> None:
    route = _find(db, route_id, lock=True)
    route.is_active = False
    route.is_removed = True
    record_audit(db, AuditLog, actor_id=claims["sub"], action="remove_route", entity="route", entity_id=route_id)
    route_changed(db, route_id)
    db.commit()


@router.get("/internal/routes/{route_id}", include_in_schema=False)
def internal_route(route_id: str, db: Session = Depends(get_db)) -> RouteSnapshot:
    route = db.scalars(
        select(Route).where(Route.id == route_id).options(joinedload(Route.points)),
    ).unique().one_or_none()
    if route is None:
        raise ApiError("not_found", "Rota nao encontrada.", 404)
    return RouteSnapshot(
        id=route.id, name=route.name, is_active=route.is_active, is_removed=route.is_removed,
        reward_amount=route.reward_amount, points=_points(route),
    )
