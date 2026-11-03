"""Append-only policy, admission and provider accounting history."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models import UTCDateTime


class AIControlPolicy(Base):
    __tablename__ = "ai_control_policies"
    __table_args__ = (CheckConstraint("kind IN ('allowance','admission')", name="kind"),)
    scope: Mapped[str] = mapped_column(String(96), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    configuration: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class AIProviderAttempt(Base):
    __tablename__ = "ai_provider_attempts"
    __table_args__ = (
        CheckConstraint(
            "capability IN ('generation','tutor','support','embedding')", name="capability"
        ),
        CheckConstraint("estimated_input_bytes >= 0", name="input_bound"),
        CheckConstraint("item_count BETWEEN 1 AND 128", name="items"),
        Index("ix_ai_provider_attempt_scope_window", "scope", "window_start"),
        Index("ix_ai_provider_attempt_scope_subject", "scope", "subject_hash"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    scope: Mapped[str] = mapped_column(ForeignKey("ai_control_policies.scope"))
    capability: Mapped[str] = mapped_column(String(16))
    model_id: Mapped[str] = mapped_column(String(128))
    subject_hash: Mapped[str] = mapped_column(String(64))
    estimated_input_bytes: Mapped[int]
    item_count: Mapped[int]
    admitted_at: Mapped[datetime] = mapped_column(UTCDateTime())
    window_start: Mapped[datetime] = mapped_column(UTCDateTime())


class AIProviderUsage(Base):
    __tablename__ = "ai_provider_usage"
    __table_args__ = (
        CheckConstraint(
            "status IN ('success','refusal','truncated','timeout','error','unknown')", name="status"
        ),
        CheckConstraint("input_tokens IS NULL OR input_tokens >= 0", name="input_tokens"),
        CheckConstraint("output_tokens IS NULL OR output_tokens >= 0", name="output_tokens"),
        CheckConstraint(
            "provider_duration_ms IS NULL OR provider_duration_ms >= 0", name="duration"
        ),
        CheckConstraint(
            "accounted_cost_microusd IS NULL OR accounted_cost_microusd >= 0", name="known_cost"
        ),
    )
    attempt_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_provider_attempts.id"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(32))
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    provider_duration_ms: Mapped[int | None]
    accounted_cost_microusd: Mapped[int | None]
    completed_at: Mapped[datetime] = mapped_column(UTCDateTime())


class AIAdmissionLease(Base):
    __tablename__ = "ai_admission_leases"
    __table_args__ = (
        Index("ix_ai_admission_scope_window", "scope", "window_start"),
        Index("ix_ai_admission_scope_subject", "scope", "subject_hash"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    scope: Mapped[str] = mapped_column(ForeignKey("ai_control_policies.scope"))
    subject_hash: Mapped[str] = mapped_column(String(64))
    admitted_at: Mapped[datetime] = mapped_column(UTCDateTime())
    window_start: Mapped[datetime] = mapped_column(UTCDateTime())


class AIAdmissionRelease(Base):
    __tablename__ = "ai_admission_releases"
    lease_id: Mapped[UUID] = mapped_column(ForeignKey("ai_admission_leases.id"), primary_key=True)
    released_at: Mapped[datetime] = mapped_column(UTCDateTime())


class AIControlReconciliation(Base):
    __tablename__ = "ai_control_reconciliations"
    __table_args__ = (
        CheckConstraint("target_kind IN ('provider','admission')", name="target_kind"),
        UniqueConstraint("target_kind", "target_id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    target_kind: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[UUID] = mapped_column(Uuid)
    operator_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
