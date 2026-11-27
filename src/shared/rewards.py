"""Wire contract for authenticated, repeatable Gamification credit commands."""

import hashlib
import hmac
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field

from shared.settings import secret


class RewardCredit(BaseModel):
    source_type: Literal["visit", "route"]
    source_id: str = Field(min_length=1, max_length=128)
    amount: int = Field(gt=0, le=2_147_483_647)
    occurred_at: AwareDatetime


class RewardOperation(BaseModel):
    user_id: str = Field(min_length=1, max_length=36)
    credits: list[RewardCredit] = Field(min_length=1)


class SignedRewards(BaseModel):
    rewards: RewardOperation
    signature: str


def sign_rewards(rewards: RewardOperation) -> SignedRewards:
    key = secret("REWARDS_SIGNING_KEY").encode()
    signature = hmac.new(key, rewards.model_dump_json().encode(), hashlib.sha256).hexdigest()
    return SignedRewards(rewards=rewards, signature=signature)


def verify_rewards(command: SignedRewards) -> bool:
    return hmac.compare_digest(sign_rewards(command.rewards).signature, command.signature)


class RewardReceipt(BaseModel):
    confirmed: bool
    balance: int
    # Receipt is a view of the ledger as of the read, not a provider timestamp.
    checked_at: datetime
