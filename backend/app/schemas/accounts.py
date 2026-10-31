from datetime import datetime
from uuid import UUID

from app.schemas.learning import Contract


class AccountResponse(Contract):
    user_id: UUID
    created_at: datetime
    status: str
    roles: list[str]
    learner_id: UUID | None
    anonymous_history_available: bool


class AccountLearnerResponse(Contract):
    learner_id: UUID | None


class ClaimResponse(Contract):
    learner_id: UUID
    claimed: bool
