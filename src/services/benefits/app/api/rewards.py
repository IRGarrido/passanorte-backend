from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from services.benefits.app.api.partners import get_db
from services.benefits.app.models import LedgerEntry
from services.benefits.app.models.ledger import Wallet
from shared.errors import ApiError
from shared.rbac import require_role
from shared.rewards import RewardOperation, RewardReceipt, SignedRewards, verify_rewards

router = APIRouter(tags=["wallet"])


def balance(db: Session, user_id: str) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(LedgerEntry.amount), 0))
                         .where(LedgerEntry.tourist_id == user_id)) or 0)


@router.get("/me/balance")
def get_balance(claims: dict = Depends(require_role("tourist")), db: Session = Depends(get_db)) -> dict:
    return {"balance": balance(db, claims["sub"]), "currency": "guarana"}


def _authenticated(command: SignedRewards) -> RewardOperation:
    if not verify_rewards(command):
        raise ApiError("invalid_producer", "Produtor de créditos não autorizado.", 403)
    return command.rewards


def _receipt(db: Session, rewards: RewardOperation) -> RewardReceipt:
    # A single SQL statement gives the balance and per-source confirmation on the same snapshot.
    rows = db.execute(select(LedgerEntry.source_type, LedgerEntry.source_id, LedgerEntry.amount)
                      .where(LedgerEntry.tourist_id == rewards.user_id)).all()
    posted = {(kind, source): amount for kind, source, amount in rows}
    return RewardReceipt(
        confirmed=all(posted.get((credit.source_type, credit.source_id)) == credit.amount
                      for credit in rewards.credits),
        balance=sum(posted.values()), checked_at=datetime.now(UTC),
    )


def apply_rewards(db: Session, payload: dict) -> RewardReceipt:
    rewards = _authenticated(SignedRewards.model_validate(payload))
    insert = postgres_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    db.execute(insert(Wallet).values(tourist_id=rewards.user_id).on_conflict_do_nothing())
    db.scalar(select(Wallet).where(Wallet.tourist_id == rewards.user_id).with_for_update())
    for credit in rewards.credits:
        db.execute(insert(LedgerEntry).values(id=str(uuid4()), tourist_id=rewards.user_id, **credit.model_dump())
                   .on_conflict_do_nothing(index_elements=["source_type", "source_id"]))
    receipt = _receipt(db, rewards)
    if not receipt.confirmed:
        raise ApiError("reward_conflict", "Origem de crédito inconsistente.", 409)
    return receipt


@router.post("/internal/rewards", include_in_schema=False)
def post_rewards(command: SignedRewards, db: Session = Depends(get_db)) -> RewardReceipt:
    receipt = apply_rewards(db, command.model_dump())
    db.commit()
    return receipt


@router.post("/internal/rewards/status", include_in_schema=False)
def reward_status(command: SignedRewards, db: Session = Depends(get_db)) -> RewardReceipt:
    return _receipt(db, _authenticated(command))
