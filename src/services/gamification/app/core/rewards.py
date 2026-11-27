import os
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from services.gamification.app.core.deps import get_route_lookup
from services.gamification.app.models.enrollment import CreditIntent, EnrollmentStatus, RouteCompletion, RouteEnrollment
from services.validation.app.models.visit import Visit, VisitStatus
from shared.errors import ApiError
from shared.internal_client import RouteSnapshot, call_internal
from shared.messaging import enqueue
from shared.notifications_client import dispatch
from shared.rewards import RewardCredit, RewardOperation, RewardReceipt, SignedRewards, sign_rewards


def lock(db: Session, scope: str, identifier: str) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                   {"key": f"gamification:{scope}:{identifier}"})


def visited_points(db: Session, user_id: str) -> set[str]:
    return set(db.scalars(select(Visit.tourist_spot_id).where(
        Visit.user_id == user_id, Visit.status == VisitStatus.validated,
    )))


def complete_if_ready(
    db: Session, enrollment: RouteEnrollment, route: RouteSnapshot, visited: set[str],
) -> RewardCredit | None:
    if (
        enrollment.status != EnrollmentStatus.in_progress
        or route.is_removed or not route.is_active or not route.points
        or not visited.issuperset(route.points)
    ):
        return None
    previous = db.scalar(select(RouteCompletion).where(
        RouteCompletion.user_id == enrollment.user_id, RouteCompletion.route_id == route.id,
    ))
    now = datetime.now(UTC)
    enrollment.status = EnrollmentStatus.completed
    enrollment.completed_at = previous.completed_at if previous else now
    if previous is not None:
        return None
    completion_id = str(uuid4())
    db.add(RouteCompletion(id=completion_id, user_id=enrollment.user_id, route_id=route.id,
                           reward_amount=route.reward_amount, completed_at=now))
    dispatch(db=db, kind="new_route", source_id=completion_id, user_ids=[enrollment.user_id],
             title="Rota concluída", body="Você concluiu a rota.", payload={"route_id": route.id})
    if route.reward_amount == 0:
        return None
    return RewardCredit(source_type="route", source_id=completion_id, amount=route.reward_amount, occurred_at=now)


def complete_tourist_routes(
    db: Session, user_id: str, lookup: Callable[[str], RouteSnapshot | None],
) -> list[RewardCredit]:
    active = db.scalars(select(RouteEnrollment).where(
        RouteEnrollment.user_id == user_id, RouteEnrollment.status == EnrollmentStatus.in_progress,
    )).all()
    visited = visited_points(db, user_id)
    credits = []
    for enrollment in active:
        route = lookup(enrollment.route_id)
        if route is not None and (credit := complete_if_ready(db, enrollment, route, visited)):
            credits.append(credit)
    return credits


def record_intent(
    db: Session, user_id: str, credits: list[RewardCredit], *, operation_id: str | None = None,
) -> CreditIntent | None:
    if not credits:
        return None
    command = sign_rewards(RewardOperation(user_id=user_id, credits=credits))
    intent = CreditIntent(id=operation_id or str(uuid4()), user_id=user_id, payload=command.model_dump(mode="json"))
    db.add(intent)
    enqueue(db, "rewards.requested", intent.payload)
    return intent


def reconcile_route(db: Session, data: dict) -> None:
    route_id = data["route_id"]
    lock(db, "route", route_id)
    route = get_route_lookup()(route_id)
    if route is None:
        return
    users = db.scalars(select(RouteEnrollment.user_id).where(
        RouteEnrollment.route_id == route_id,
    ).order_by(RouteEnrollment.user_id)).all()
    for user_id in users:
        lock(db, "tourist", user_id)
        enrollment = db.scalar(select(RouteEnrollment).where(
            RouteEnrollment.user_id == user_id, RouteEnrollment.route_id == route_id,
        ))
        if enrollment is None:
            continue
        if route.is_removed:
            enrollment.status = EnrollmentStatus.withdrawn
        elif credit := complete_if_ready(db, enrollment, route, visited_points(db, user_id)):
            record_intent(db, user_id, [credit])


def get_reward_gateway() -> Callable[[SignedRewards, bool], RewardReceipt]:
    base = os.getenv("BENEFITS_SERVICE_URL", "http://benefits:8008")

    def gateway(command: SignedRewards, submit: bool) -> RewardReceipt:
        path = "/internal/rewards" if submit else "/internal/rewards/status"
        return RewardReceipt.model_validate(call_internal(base, "POST", path, json=command.model_dump(mode="json")))

    return gateway


def operation_result(
    intent: CreditIntent | None, gateway: Callable[[SignedRewards, bool], RewardReceipt], *, submit: bool,
) -> dict:
    if intent is None:
        return {"reward_status": "not_applicable", "operation_id": None, "balance": None}
    receipt = None
    try:
        # Re-sign on a direct retry so previously persisted intents survive credential rotation.
        command = sign_rewards(SignedRewards.model_validate(intent.payload).rewards)
        receipt = gateway(command, submit)
    except ApiError as error:
        if error.status_code != 503:
            raise
    return {"reward_status": "confirmed" if receipt and receipt.confirmed else "pending",
            "operation_id": intent.id, "balance": receipt.balance if receipt else None}
