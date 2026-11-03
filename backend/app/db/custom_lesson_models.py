"""Tables for learner-requested lessons. Private to the requesting account.

Stores only what the app needs: the learner's own request fields, the validated lesson,
answer keys (server-side only) and answers. No provider prompts or raw model output.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models import UTCDateTime


def _now() -> datetime:
    return datetime.now(UTC)


class CustomLessonRequestRow(Base):
    __tablename__ = "custom_lesson_requests"
    __table_args__ = (
        UniqueConstraint("account_id", "idempotency_key"),
        CheckConstraint("lesson_count BETWEEN 1 AND 3", name="lesson_count_range"),
        CheckConstraint(
            "status IN ('queued','generating','ready','failed','cancelled','rejected')",
            name="status_values",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(48))
    topic: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(40))
    framework: Mapped[str | None] = mapped_column(String(40))
    level: Mapped[str] = mapped_column(String(16))
    goal: Mapped[str] = mapped_column(String(16))
    lesson_count: Mapped[int] = mapped_column(Integer)
    practice_styles: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class CustomLessonRow(Base):
    __tablename__ = "custom_lessons"
    __table_args__ = (UniqueConstraint("request_id", "position"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    request_id: Mapped[UUID] = mapped_column(
        ForeignKey("custom_lesson_requests.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(120))
    objective: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(40))
    level: Mapped[str] = mapped_column(String(16))
    sections: Mapped[list[dict[str, str]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)


class CustomChallengeRow(Base):
    __tablename__ = "custom_lesson_challenges"
    __table_args__ = (
        UniqueConstraint("lesson_id", "position"),
        CheckConstraint(
            "verification_mode IN ('answer_key','practice_only')", name="verification_values"
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    lesson_id: Mapped[UUID] = mapped_column(
        ForeignKey("custom_lessons.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(24))
    prompt: Mapped[str] = mapped_column(Text)
    code: Mapped[str | None] = mapped_column(Text)
    options: Mapped[list[str]] = mapped_column(JSON)
    hints: Mapped[list[str]] = mapped_column(JSON)
    explanation: Mapped[str] = mapped_column(Text)
    verification_mode: Mapped[str] = mapped_column(String(16))
    # Server-side only. Never serialized to any response.
    correct_option: Mapped[int | None] = mapped_column(Integer)
    model_answer: Mapped[str | None] = mapped_column(Text)


class CustomChallengeAnswerRow(Base):
    __tablename__ = "custom_lesson_answers"
    __table_args__ = (UniqueConstraint("challenge_id", "account_id", "idempotency_key"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    challenge_id: Mapped[UUID] = mapped_column(
        ForeignKey("custom_lesson_challenges.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    correct: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
