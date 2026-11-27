from datetime import UTC, datetime

import pytest

from services.benefits.app.api.rewards import apply_rewards
from services.gamification.app.core.rewards import complete_if_ready
from services.gamification.app.models.enrollment import RouteCompletion, RouteEnrollment
from shared.errors import ApiError
from shared.internal_client import RouteSnapshot
from shared.rewards import RewardCredit, RewardOperation, sign_rewards


def test_rewards_are_idempotent_and_reject_payload_changes(db_session):
    operation = RewardOperation(user_id="tourist", credits=[
        RewardCredit(source_type="visit", source_id="v", amount=1, occurred_at=datetime.now(UTC)),
    ])
    signed = sign_rewards(operation)
    for _ in range(2):
        receipt = apply_rewards(db_session, signed.model_dump(mode="json"))
        db_session.commit()
        assert receipt.confirmed and receipt.balance == 1
    operation.credits[0].amount = 9
    with pytest.raises(ApiError, match="Produtor"):
        apply_rewards(db_session, signed.model_dump(mode="json"))
    with pytest.raises(ApiError) as error:
        apply_rewards(db_session, sign_rewards(operation).model_dump(mode="json"))
    assert error.value.status_code == 409
    db_session.rollback()


def test_zero_valid_points_never_complete_a_route(db_session):
    enrollment = RouteEnrollment(user_id="u", route_id="r")
    db_session.add(enrollment)
    db_session.flush()
    route = RouteSnapshot(id="r", name="Rota", is_active=True, reward_amount=4, points=[])
    assert complete_if_ready(db_session, enrollment, route, set()) is None
    assert db_session.query(RouteCompletion).count() == 0
