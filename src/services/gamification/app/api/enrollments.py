"""Enrollment commands and read-only progress views."""

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.gamification.app.core.deps import get_db, get_route_lookup, require_role
from services.gamification.app.core.rewards import (
    complete_if_ready,
    get_reward_gateway,
    lock,
    operation_result,
    record_intent,
    visited_points,
)
from services.gamification.app.models.enrollment import CreditIntent, EnrollmentStatus, RouteEnrollment
from shared.errors import ApiError
from shared.internal_client import RouteSnapshot
from shared.rewards import RewardReceipt, SignedRewards

router = APIRouter(tags=["enrollments"])
require_tourist = require_role("tourist")
Lookup = Callable[[str], RouteSnapshot | None]
Gateway = Callable[[SignedRewards, bool], RewardReceipt]


def _enrollment(db: Session, user_id: str, route_id: str) -> RouteEnrollment | None:
    return db.scalar(select(RouteEnrollment).where(
        RouteEnrollment.user_id == user_id, RouteEnrollment.route_id == route_id,
    ))


def _body(enrollment: RouteEnrollment, route: RouteSnapshot, visited: set[str]) -> dict:
    done = [point for point in route.points if point in visited]
    pending = [point for point in route.points if point not in visited]
    return {
        "id": enrollment.id, "route_id": route.id, "route_name": route.name, "status": enrollment.status,
        "visited": done, "pending": pending,
        "percent": round(100 * len(done) / len(route.points), 2) if route.points else 0.0,
    }


@router.post("/routes/{route_id}/enrollments", status_code=201)
def enroll(
    route_id: str, claims: dict = Depends(require_tourist), lookup: Lookup = Depends(get_route_lookup),
    db: Session = Depends(get_db), gateway: Gateway = Depends(get_reward_gateway),
) -> dict:
    user_id = claims["sub"]
    lock(db, "route", route_id)
    lock(db, "tourist", user_id)
    route = lookup(route_id)
    if route is None or route.is_removed or not route.is_active:
        raise ApiError("not_found", "Rota indisponivel para inscricao.", 404)
    enrollment = _enrollment(db, user_id, route_id)
    if enrollment is None:
        enrollment = RouteEnrollment(user_id=user_id, route_id=route_id)
        db.add(enrollment)
        db.flush()
    elif enrollment.status == EnrollmentStatus.withdrawn:
        enrollment.status = EnrollmentStatus.in_progress
        enrollment.started_at = datetime.now(UTC)
        enrollment.completed_at = None
    else:
        raise ApiError("already_enrolled", "Voce ja esta inscrito nesta rota.", 409)
    visited = visited_points(db, user_id)
    credit = complete_if_ready(db, enrollment, route, visited)
    intent = record_intent(db, user_id, [credit]) if credit else None
    body = _body(enrollment, route, visited)
    db.commit()
    return {**body, **operation_result(intent, gateway, submit=True)}


@router.delete("/routes/{route_id}/enrollments", status_code=204)
@router.delete("/enrollments/{route_id}", status_code=204)
def withdraw(route_id: str, claims: dict = Depends(require_tourist), db: Session = Depends(get_db)) -> None:
    lock(db, "tourist", claims["sub"])
    enrollment = _enrollment(db, claims["sub"], route_id)
    if enrollment is None:
        raise ApiError("not_found", "Inscricao nao encontrada.", 404)
    enrollment.status = EnrollmentStatus.withdrawn
    db.commit()


@router.get("/enrollments")
def list_enrollments(
    claims: dict = Depends(require_tourist), lookup: Lookup = Depends(get_route_lookup),
    db: Session = Depends(get_db),
) -> dict:
    user_id = claims["sub"]
    enrollments = db.scalars(select(RouteEnrollment).where(
        RouteEnrollment.user_id == user_id, RouteEnrollment.status != EnrollmentStatus.withdrawn,
    ).order_by(RouteEnrollment.started_at, RouteEnrollment.id))
    visited = visited_points(db, user_id)
    items = []
    for enrollment in enrollments:
        route = lookup(enrollment.route_id)
        if route is not None and not route.is_removed:
            items.append(_body(enrollment, route, visited))
    return {"items": items, "total": len(items)}


@router.get("/enrollments/{route_id}")
def get_enrollment(
    route_id: str, claims: dict = Depends(require_tourist), lookup: Lookup = Depends(get_route_lookup),
    db: Session = Depends(get_db),
) -> dict:
    enrollment = _enrollment(db, claims["sub"], route_id)
    route = lookup(route_id) if enrollment and enrollment.status != EnrollmentStatus.withdrawn else None
    if enrollment is None or route is None or route.is_removed:
        raise ApiError("not_found", "Inscricao nao encontrada.", 404)
    return _body(enrollment, route, visited_points(db, claims["sub"]))


def _intent(db: Session, operation_id: str, user_id: str) -> CreditIntent:
    intent = db.get(CreditIntent, operation_id)
    if intent is None or intent.user_id != user_id:
        raise ApiError("not_found", "Operacao nao encontrada.", 404)
    return intent


@router.get("/reward-operations/{operation_id}")
def get_operation(
    operation_id: str, claims: dict = Depends(require_tourist), db: Session = Depends(get_db),
    gateway: Gateway = Depends(get_reward_gateway),
) -> dict:
    return operation_result(_intent(db, operation_id, claims["sub"]), gateway, submit=False)


@router.post("/reward-operations/{operation_id}/retry")
def retry_operation(
    operation_id: str, claims: dict = Depends(require_tourist), db: Session = Depends(get_db),
    gateway: Gateway = Depends(get_reward_gateway),
) -> dict:
    return operation_result(_intent(db, operation_id, claims["sub"]), gateway, submit=True)
