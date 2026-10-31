from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from app.domain.learning import Credential, LearningError

Role = Literal["learner", "creator", "admin"]


@dataclass(frozen=True)
class VerifiedIdentity:
    issuer: str
    subject: str
    expires_at: datetime


@dataclass(frozen=True)
class Account:
    id: UUID
    created_at: datetime
    status: str
    roles: tuple[str, ...]

    def require_role(self, role: Role) -> None:
        if self.status != "active" or role not in self.roles:
            raise LearningError("forbidden", "This account does not have the required role.")


@dataclass(frozen=True)
class Principal:
    learner_id: UUID
    expires_at: datetime
    account: Account | None = None
    credential: Credential | None = None


@dataclass(frozen=True)
class LearnerOwnership:
    learner_id: UUID
    claim_key: str | None


@dataclass(frozen=True)
class AccountStatus:
    account: Account
    learner_id: UUID | None
    anonymous_history_available: bool


@dataclass(frozen=True)
class AuthenticatedAccount:
    account: Account
    identity: VerifiedIdentity
