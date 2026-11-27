"""Tourist check-in, result-only persistence, and reward confirmation."""

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from services.gamification.app.core.deps import get_route_lookup, require_role
from services.gamification.app.core.rewards import (
    complete_tourist_routes,
    get_reward_gateway,
    lock,
    operation_result,
    record_intent,
)
from services.gamification.app.models.enrollment import CreditIntent
from services.validation.app.core.deps import get_catalog_snapshot, get_db
from services.validation.app.core.haversine import haversine_m
from services.validation.app.core.propagator import get_propagator
from services.validation.app.models.visit import Visit, VisitStatus
from shared.errors import ApiError
from shared.internal_client import RouteSnapshot
from shared.rewards import RewardCredit, RewardReceipt, SignedRewards
from shared.settings import Settings

router = APIRouter(tags=["visits"])
require_tourist = require_role("tourist")


class VisitCreate(BaseModel):
    tourist_spot_id: str = Field(min_length=1, max_length=36)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=1_000_000)


def _validated_visit(db: Session, user_id: str, spot_id: str) -> Visit | None:
    return db.scalar(select(Visit).where(
        Visit.user_id == user_id, Visit.tourist_spot_id == spot_id, Visit.status == VisitStatus.validated,
    ))


def _serialise(visit: Visit) -> dict:
    return {
        "id": visit.id, "user_id": visit.user_id, "tourist_spot_id": visit.tourist_spot_id, "status": visit.status,
        "distance_m": float(visit.distance_m), "accuracy_m": float(visit.accuracy_m) if visit.accuracy_m is not None
        else None, "occurred_at": str(visit.occurred_at),
    }


def _repeat(
    db: Session, visit: Visit, gateway: Callable[[SignedRewards, bool], RewardReceipt],
) -> JSONResponse:
    previous = _serialise(visit)
    intent = db.get(CreditIntent, visit.id)
    db.commit()
    return JSONResponse(status_code=200, content={
        **previous, "already_visited": True, **operation_result(intent, gateway, submit=True),
    })


@router.post("/visits", status_code=201, response_model=None)
def mark_visit(
    payload: VisitCreate, claims: dict = Depends(require_tourist),
    snapshot_for: Callable[[str], dict] = Depends(get_catalog_snapshot),
    propagate: Callable = Depends(get_propagator),
    lookup: Callable[[str], RouteSnapshot | None] = Depends(get_route_lookup),
    gateway: Callable[[SignedRewards, bool], RewardReceipt] = Depends(get_reward_gateway),
    db: Session = Depends(get_db),
) -> JSONResponse:
    user_id = claims["sub"]
    lock(db, "tourist", user_id)
    existing = _validated_visit(db, user_id, payload.tourist_spot_id)
    if existing is not None:
        return _repeat(db, existing, gateway)
    if payload.latitude is None or payload.longitude is None or payload.accuracy_m is None:
        raise ApiError("gps_unavailable", "Informe latitude, longitude e precisao do GPS.", 422)

    spot = snapshot_for(payload.tourist_spot_id)
    if spot["status"] != "open":
        raise ApiError("spot_closed", "O ponto precisa estar aberto para check-in.", 422)
    settings = Settings.load()
    radius = spot.get("tolerance_radius_m") or settings.checkin_radius_m
    limit = radius + settings.checkin_tolerance_m
    distance = haversine_m(payload.latitude, payload.longitude, float(spot["latitude"]), float(spot["longitude"]))
    accepted = distance <= limit
    now = datetime.now(UTC)
    visit = Visit(
        user_id=user_id, tourist_spot_id=payload.tourist_spot_id, distance_m=round(distance, 2),
        accuracy_m=round(payload.accuracy_m, 2), status=VisitStatus.validated if accepted else VisitStatus.rejected,
        occurred_at=now,
    )
    if not accepted:
        db.add(visit)
        db.commit()
        return JSONResponse(status_code=422, content={
            "status": "rejected", "distance_m": round(distance, 2), "tolerance_m": limit,
        })
    db.add(visit)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = _validated_visit(db, user_id, payload.tourist_spot_id)
        if existing is None:
            raise
        return _repeat(db, existing, gateway)

    credits = complete_tourist_routes(db, user_id, lookup)
    credits.insert(0, RewardCredit(
        source_type="visit", source_id=visit.id, amount=settings.visit_reward_amount, occurred_at=now,
    ))
    intent = record_intent(db, user_id, credits, operation_id=visit.id)
    fact = {
        "user_id": user_id, "tourist_spot_id": visit.tourist_spot_id, "occurred_at": now.isoformat(),
        "spot_name": spot.get("name"), "latitude": spot["latitude"], "longitude": spot["longitude"],
    }
    if propagate is get_propagator():
        propagate(fact, db=db)
    else:
        propagate(fact)
    result = _serialise(visit)
    db.commit()
    reward = operation_result(intent, gateway, submit=True)
    return JSONResponse(
        status_code=201 if reward["reward_status"] == "confirmed" else 202,
        content={**result, "already_visited": False, "tolerance_m": limit, **reward},
    )


@router.get("/visits")
def list_visits(claims: dict = Depends(require_tourist), db: Session = Depends(get_db)) -> dict:
    visits = db.scalars(select(Visit).where(Visit.user_id == claims["sub"], Visit.status == VisitStatus.validated)
                       .order_by(Visit.occurred_at.desc(), Visit.id))
    items = [_serialise(visit) for visit in visits]
    return {"items": items, "total": len(items)}


@router.get("/visits/{spot_id}")
def get_visit(spot_id: str, claims: dict = Depends(require_tourist), db: Session = Depends(get_db)) -> dict:
    visit = _validated_visit(db, claims["sub"], spot_id)
    if visit is None:
        raise ApiError("not_found", "Visitacao nao encontrada.", 404)
    return _serialise(visit)
