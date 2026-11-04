"""Owner-scoped immutable-version instructional guides; independent of learner history."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models import UTCDateTime


class PrivateLearningGuide(Base):
    __tablename__ = "private_learning_guides"
    __table_args__ = (
        UniqueConstraint("owner_id", "creation_key"),
        CheckConstraint("status IN ('generating','ready','unavailable')", name="status"),
        CheckConstraint("version = '1.0.0'", name="version"),
        CheckConstraint(
            "(status = 'ready' AND content IS NOT NULL AND content_sha256 IS NOT NULL "
            "AND source IS NOT NULL AND generation_provenance IS NOT NULL) OR "
            "(status <> 'ready' AND content IS NULL AND content_sha256 IS NULL "
            "AND source IS NULL AND generation_provenance IS NULL)",
            name="content_state",
        ),
        CheckConstraint("source IS NULL OR source IN ('ai','test_fixture')", name="source"),
        Index("ix_private_learning_guides_owner_created", "owner_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    creation_key: Mapped[UUID] = mapped_column(Uuid)
    request_sha256: Mapped[str] = mapped_column(String(64))
    request_payload: Mapped[dict[str, object]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[str] = mapped_column(String(16))
    content: Mapped[dict[str, object] | None] = mapped_column(JSON(none_as_null=True))
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str | None] = mapped_column(String(16))
    generation_provenance: Mapped[dict[str, str | None] | None] = mapped_column(
        JSON(none_as_null=True)
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    reservation_expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
