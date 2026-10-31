from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.db.base import Base


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("UTC-aware timestamp required")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


class Row:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=lambda: datetime.now(UTC))


class WriteGate(Base):
    __tablename__ = "write_gate"
    id: Mapped[int] = mapped_column(primary_key=True)


class Learner(Row, Base):
    __tablename__ = "learners"


class LearnerCredential(Row, Base):
    __tablename__ = "learner_credentials"
    learner_id: Mapped[UUID] = mapped_column(ForeignKey("learners.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class User(Row, Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("status IN ('active','disabled')", name="status"),)
    status: Mapped[str] = mapped_column(String(16), default="active")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class AuthSubject(Row, Base):
    __tablename__ = "auth_subjects"
    __table_args__ = (UniqueConstraint("issuer", "subject"),)
    issuer: Mapped[str] = mapped_column(String(512))
    subject: Mapped[str] = mapped_column(String(36))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime())


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (CheckConstraint("role IN ('learner','creator','admin')", name="role"),)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), primary_key=True)


class RoleGrantEvent(Row, Base):
    __tablename__ = "role_grant_events"
    __table_args__ = (CheckConstraint("role IN ('creator','admin')", name="role"),)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    operator: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(String(1000))


class AccountLearner(Base):
    __tablename__ = "account_learners"
    __table_args__ = (
        CheckConstraint(
            "(claim_key IS NULL) = (claimed_credential_id IS NULL)", name="claim_receipt"
        ),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    learner_id: Mapped[UUID] = mapped_column(ForeignKey("learners.id"), unique=True)
    claim_key: Mapped[str | None] = mapped_column(String(36))
    claimed_credential_id: Mapped[UUID | None] = mapped_column(ForeignKey("learner_credentials.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class AccountActionLimit(Base):
    __tablename__ = "account_action_limits"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    action: Mapped[str] = mapped_column(String(32), primary_key=True)
    window: Mapped[int] = mapped_column()
    count: Mapped[int] = mapped_column()


class Lesson(Base):
    __tablename__ = "lessons"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)


class LessonVersion(Row, Base):
    __tablename__ = "lesson_versions"
    __table_args__ = (UniqueConstraint("lesson_id", "version"),)
    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id"), index=True)
    version: Mapped[str] = mapped_column(String(32))
    public_content: Mapped[dict[str, str]] = mapped_column(JSON)
    expected_field: Mapped[str] = mapped_column(String(16))
    prediction_answer: Mapped[str] = mapped_column(String(32))
    content_hash: Mapped[str] = mapped_column(String(64))


class LearningSession(Row, Base):
    __tablename__ = "learning_sessions"
    __table_args__ = (
        UniqueConstraint("learner_id", "idempotency_key"),
        CheckConstraint(
            (
                "state IN ('awaiting_prediction','ready_for_attempt','verification"
                "_pending','needs_revision','completed','abandoned')"
            ),
            name="state",
        ),
        CheckConstraint(
            "(state = 'completed') = (completed_at IS NOT NULL)", name="completion_time"
        ),
    )
    learner_id: Mapped[UUID] = mapped_column(ForeignKey("learners.id"), index=True)
    lesson_version_id: Mapped[UUID] = mapped_column(ForeignKey("lesson_versions.id"))
    state: Mapped[str] = mapped_column(String(32))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Prediction(Row, Base):
    __tablename__ = "predictions"
    session_id: Mapped[UUID] = mapped_column(ForeignKey("learning_sessions.id"), unique=True)
    selected_answer: Mapped[str] = mapped_column(String(32))
    reasoning: Mapped[str] = mapped_column(String(2000))
    idempotency_key: Mapped[str] = mapped_column(String(64))


class Attempt(Row, Base):
    __tablename__ = "attempts"
    __table_args__ = (
        UniqueConstraint("session_id", "number"),
        UniqueConstraint("session_id", "idempotency_key"),
        UniqueConstraint("id", "session_id"),
        CheckConstraint("number > 0", name="positive_number"),
        CheckConstraint("field_name IN ('body','content','flat','nested')", name="supported_field"),
        CheckConstraint("hints_before >= 0 AND hints_before <= 3", name="hint_count"),
    )
    session_id: Mapped[UUID] = mapped_column(ForeignKey("learning_sessions.id"), index=True)
    number: Mapped[int]
    field_name: Mapped[str] = mapped_column(String(16))
    explanation: Mapped[str] = mapped_column(String(2000))
    hints_before: Mapped[int]
    idempotency_key: Mapped[str] = mapped_column(String(64))


class TutorInteraction(Row, Base):
    __tablename__ = "tutor_interactions"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence"),
        UniqueConstraint("session_id", "idempotency_key"),
        ForeignKeyConstraint(["attempt_id", "session_id"], ["attempts.id", "attempts.session_id"]),
        CheckConstraint("sequence BETWEEN 1 AND 3", name="hint_limit"),
        CheckConstraint("status IN ('delivered','error')", name="status"),
    )
    session_id: Mapped[UUID] = mapped_column(ForeignKey("learning_sessions.id"), index=True)
    attempt_id: Mapped[UUID | None] = mapped_column(Uuid)
    sequence: Mapped[int]
    text: Mapped[str | None] = mapped_column(String(2400))
    status: Mapped[str] = mapped_column(String(16))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32))
    fixture: Mapped[str] = mapped_column(String(32))
    prompt_version: Mapped[str] = mapped_column(String(64))
    interaction_type: Mapped[str] = mapped_column(String(16))


class VerificationRun(Row, Base):
    __tablename__ = "verification_runs"
    __table_args__ = (
        UniqueConstraint("attempt_id", "idempotency_key"),
        ForeignKeyConstraint(["attempt_id", "session_id"], ["attempts.id", "attempts.session_id"]),
        CheckConstraint("status IN ('pending','passed','failed','error')", name="status"),
        CheckConstraint("(status = 'pending') = (completed_at IS NULL)", name="completion_time"),
    )
    session_id: Mapped[UUID] = mapped_column(ForeignKey("learning_sessions.id"), index=True)
    attempt_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    status: Mapped[str] = mapped_column(String(16))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    feedback: Mapped[str] = mapped_column(String(2000))


class VerificationCheck(Row, Base):
    __tablename__ = "verification_checks"
    __table_args__ = (UniqueConstraint("run_id", "code"),)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("verification_runs.id"), index=True)
    code: Mapped[str] = mapped_column(String(40))
    matched: Mapped[bool] = mapped_column(Boolean)
    expected: Mapped[str] = mapped_column(String(4000))
    observed: Mapped[str] = mapped_column(String(8000))
    source: Mapped[str] = mapped_column(String(40))


class LearningEvent(Row, Base):
    __tablename__ = "learning_events"
    session_id: Mapped[UUID] = mapped_column(ForeignKey("learning_sessions.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    reference_id: Mapped[UUID | None] = mapped_column(Uuid)


class RuntimeNote(Row, Base):
    __tablename__ = "runtime_notes"
    run_id: Mapped[UUID] = mapped_column(ForeignKey("verification_runs.id"), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(String(2000))


class RuntimeTask(Row, Base):
    __tablename__ = "runtime_tasks"
    __table_args__ = (CheckConstraint("priority IN ('low','normal','high')", name="priority"),)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("verification_runs.id"), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    priority: Mapped[str] = mapped_column(String(16))


class RetrievalCheckpoint(Row, Base):
    __tablename__ = "retrieval_checkpoints"
    __table_args__ = (
        UniqueConstraint("transfer_session_id", "ordinal"),
        CheckConstraint("ordinal IN (1,2)", name="ordinal"),
    )
    transfer_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_sessions.id"), index=True
    )
    ordinal: Mapped[int]
    question_id: Mapped[str] = mapped_column(String(64))
    question_hash: Mapped[str] = mapped_column(String(64))
    due_at: Mapped[datetime] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class RetrievalAttempt(Row, Base):
    __tablename__ = "retrieval_attempts"
    __table_args__ = (
        UniqueConstraint("checkpoint_id", "number"),
        UniqueConstraint("checkpoint_id", "idempotency_key"),
        CheckConstraint("number > 0", name="positive_number"),
        CheckConstraint("selection IN ('a','b','c')", name="selection"),
    )
    checkpoint_id: Mapped[UUID] = mapped_column(ForeignKey("retrieval_checkpoints.id"), index=True)
    number: Mapped[int]
    selection: Mapped[str] = mapped_column(String(1))
    reasoning: Mapped[str] = mapped_column(String(2000))
    correct: Mapped[bool] = mapped_column(Boolean)
    feedback: Mapped[str] = mapped_column(String(2000))
    idempotency_key: Mapped[str] = mapped_column(String(64))
