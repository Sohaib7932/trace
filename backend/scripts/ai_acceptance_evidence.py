"""Private operator proof over explicit metadata columns; never learner content.

Production construction is PostgreSQL-only and requires explicit process config.
Injected disposable databases support offline regression tests. No database writes,
AI clients, keys, schema changes or public diagnostics are introduced here.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.ai.accounting import AllowancePolicy
from app.core.accounting_settings import AccountingSettings
from app.core.ai_settings import GEMINI_MODEL
from app.core.settings import Settings
from app.db import accounting_models as a
from app.db.custom_lesson_models import CustomChallengeRow, CustomLessonRequestRow, CustomLessonRow
from app.db.migrations import expected_heads
from app.db.models import User, UserRole
from app.db.session import Database

type EvidenceCode = Literal[
    "evidence_configuration_required",
    "evidence_unavailable",
    "identity_changed",
    "competing_work",
    "existing_operation",
    "request_mismatch",
    "usage_unknown",
    "provider_unverified",
]


_CODES = frozenset(
    {
        "evidence_configuration_required",
        "evidence_unavailable",
        "identity_changed",
        "competing_work",
        "existing_operation",
        "request_mismatch",
        "usage_unknown",
        "provider_unverified",
    }
)


class EvidenceError(Exception):
    def __init__(self, code: EvidenceCode) -> None:
        self.code = code if code in _CODES else "evidence_unavailable"
        super().__init__("Operator acceptance evidence is unavailable.")


class VerifiedEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    attribution: Literal["unique_account_custom_job_window"] = "unique_account_custom_job_window"
    provider_attempts: StrictInt = Field(default=1, ge=1, le=1)
    provider_mode: Literal["gemini_free"] = "gemini_free"
    requested_model_id: str = GEMINI_MODEL
    returned_model_id: Literal["not_retained"] = "not_retained"
    provider_outcome: Literal["success"] = "success"
    input_tokens: StrictInt = Field(ge=0, le=1_000_000_000)
    output_tokens: StrictInt = Field(ge=0, le=1_000_000_000)
    recorded_cost_microusd: StrictInt = Field(default=0, ge=0, le=0)
    billing_verified: Literal[False] = False

    @model_validator(mode="after")
    def approved_model(self) -> "VerifiedEvidence":
        if self.requested_model_id != GEMINI_MODEL:
            raise ValueError("Acceptance requires the approved model")
        return self


@dataclass(frozen=True)
class EvidenceBaseline:
    owner: UUID = field(repr=False)
    key: UUID = field(repr=False)
    body_hash: str = field(repr=False)
    request_count: int
    attempt_ids: frozenset[UUID] = field(repr=False)


class SqlAcceptanceEvidence:
    def __init__(self, database: Database, policy: AllowancePolicy, *, owned: bool = False) -> None:
        self.database, self.policy, self.owned = database, policy, owned

    def close(self) -> None:
        if self.owned:
            self.database.dispose()

    @contextmanager
    def _read(self) -> Iterator[Session]:
        try:
            with self.database.consistent_read() as session:
                if (
                    frozenset(session.scalars(text("SELECT version_num FROM alembic_version")))
                    != expected_heads()
                ):
                    raise EvidenceError("evidence_unavailable")
                saved = session.get(a.AIControlPolicy, self.policy.scope)
                if saved is not None and (
                    saved.kind != "allowance"
                    or saved.configuration != self.policy.model_dump(mode="json")
                ):
                    raise EvidenceError("evidence_configuration_required")
                yield session
        except EvidenceError:
            raise
        except Exception:
            raise EvidenceError("evidence_unavailable") from None

    @staticmethod
    def _owner(session: Session, owner: UUID) -> None:
        status = session.scalar(select(User.status).where(User.id == owner))
        learner = session.scalar(
            select(UserRole.role).where(UserRole.user_id == owner, UserRole.role == "learner")
        )
        if status != "active" or learner != "learner":
            raise EvidenceError("identity_changed")

    @staticmethod
    def _requests(session: Session, owner: UUID) -> int:
        return (
            session.scalar(
                select(func.count())
                .select_from(CustomLessonRequestRow)
                .where(CustomLessonRequestRow.account_id == owner)
            )
            or 0
        )

    def _attempts(self, session: Session, owner: UUID) -> list[dict[str, object]]:
        subject = sha256(("custom-lessons:" + str(owner)).encode()).hexdigest()
        # The existing cumulative allowance is bounded at 100. Never scan or
        # print an unbounded identity history, even if the database is wrong.
        rows = (
            session.execute(
                select(
                    a.AIProviderAttempt.id,
                    a.AIProviderAttempt.model_id,
                    a.AIProviderUsage.status,
                    a.AIProviderUsage.error_code,
                    a.AIProviderUsage.input_tokens,
                    a.AIProviderUsage.output_tokens,
                    a.AIProviderUsage.accounted_cost_microusd,
                )
                .outerjoin(
                    a.AIProviderUsage, a.AIProviderUsage.attempt_id == a.AIProviderAttempt.id
                )
                .where(
                    a.AIProviderAttempt.scope == self.policy.scope,
                    a.AIProviderAttempt.subject_hash == subject,
                    a.AIProviderAttempt.capability == "generation",
                )
                .limit(101)
            )
            .mappings()
            .all()
        )
        if len(rows) > 100:
            raise EvidenceError("evidence_unavailable")
        return [dict(row) for row in rows]

    def prepare(self, owner: UUID, key: UUID, body_hash: str) -> EvidenceBaseline:
        with self._read() as session:
            self._owner(session, owner)
            existing = session.scalar(
                select(CustomLessonRequestRow.id).where(
                    CustomLessonRequestRow.account_id == owner,
                    CustomLessonRequestRow.idempotency_key == str(key),
                )
            )
            if existing is not None:
                # Resuming an ambiguous earlier run must never submit a new job
                # or invent an observation window that did not include its call.
                raise EvidenceError("existing_operation")
            active = (
                session.scalar(
                    select(func.count())
                    .select_from(CustomLessonRequestRow)
                    .where(
                        CustomLessonRequestRow.account_id == owner,
                        CustomLessonRequestRow.status.in_(("queued", "generating")),
                    )
                )
                or 0
            )
            attempts = self._attempts(session, owner)
            if active or any(row["status"] is None for row in attempts):
                raise EvidenceError("competing_work")
            ids = frozenset(row["id"] for row in attempts if isinstance(row["id"], UUID))
            if len(ids) != len(attempts):
                raise EvidenceError("evidence_unavailable")
            return EvidenceBaseline(owner, key, body_hash, self._requests(session, owner), ids)

    def verify(
        self, baseline: EvidenceBaseline, request_id: UUID, lesson_id: UUID, challenge_count: int
    ) -> VerifiedEvidence:
        with self._read() as session:
            self._owner(session, baseline.owner)
            record = (
                session.execute(
                    select(
                        CustomLessonRequestRow.account_id,
                        CustomLessonRequestRow.idempotency_key,
                        CustomLessonRequestRow.request_hash,
                        CustomLessonRequestRow.status,
                        CustomLessonRequestRow.lesson_count,
                        CustomLessonRequestRow.completed_at,
                    ).where(CustomLessonRequestRow.id == request_id)
                )
                .mappings()
                .one_or_none()
            )
            if record is None or (
                record["account_id"] != baseline.owner
                or record["idempotency_key"] != str(baseline.key)
                or record["request_hash"] != baseline.body_hash
                or record["status"] != "ready"
                or record["lesson_count"] != 1
                or record["completed_at"] is None
            ):
                raise EvidenceError("request_mismatch")
            if self._requests(session, baseline.owner) != baseline.request_count + 1:
                raise EvidenceError("competing_work")
            active = (
                session.scalar(
                    select(func.count())
                    .select_from(CustomLessonRequestRow)
                    .where(
                        CustomLessonRequestRow.account_id == baseline.owner,
                        CustomLessonRequestRow.id != request_id,
                        CustomLessonRequestRow.status.in_(("queued", "generating")),
                    )
                )
                or 0
            )
            if active:
                raise EvidenceError("competing_work")
            lessons = session.execute(
                select(CustomLessonRow.id, CustomLessonRow.account_id).where(
                    CustomLessonRow.request_id == request_id
                )
            ).all()
            if (
                len(lessons) != 1
                or lessons[0].id != lesson_id
                or lessons[0].account_id != baseline.owner
            ):
                raise EvidenceError("request_mismatch")
            count = (
                session.scalar(
                    select(func.count())
                    .select_from(CustomChallengeRow)
                    .where(CustomChallengeRow.lesson_id == lesson_id)
                )
                or 0
            )
            if count != challenge_count or not 3 <= count <= 5:
                raise EvidenceError("request_mismatch")
            attempts = self._attempts(session, baseline.owner)
            ids = {row["id"] for row in attempts}
            new = [row for row in attempts if row["id"] not in baseline.attempt_ids]
            if not baseline.attempt_ids <= ids or len(new) != 1:
                raise EvidenceError("competing_work")
            usage = new[0]
            if (
                usage["model_id"] != GEMINI_MODEL
                or usage["status"] != "success"
                or usage["error_code"] is not None
            ):
                raise EvidenceError("provider_unverified")
            if any(
                usage[name] is None
                for name in ("input_tokens", "output_tokens", "accounted_cost_microusd")
            ):
                raise EvidenceError("usage_unknown")
            if usage["accounted_cost_microusd"] != 0:
                raise EvidenceError("provider_unverified")
            return VerifiedEvidence(
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
            )


def from_environment() -> SqlAcceptanceEvidence:
    """Explicit production PostgreSQL only; reject SQLite BEFORE engine creation."""
    try:
        if (
            not os.environ.get("TRACE_DATABASE_URL")
            or os.environ.get("TRACE_ENVIRONMENT") != "production"
        ):
            raise EvidenceError("evidence_configuration_required")
        settings = Settings(_env_file=None)
        accounting = AccountingSettings(_env_file=None)
        if accounting.mode != "durable" or not settings.database_url.get_secret_value().startswith(
            "postgresql+psycopg://"
        ):
            raise EvidenceError("evidence_configuration_required")
        return SqlAcceptanceEvidence(Database(settings), accounting.policy(), owned=True)
    except EvidenceError:
        raise
    except Exception:
        raise EvidenceError("evidence_configuration_required") from None
