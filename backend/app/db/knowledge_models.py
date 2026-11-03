"""Additive immutable archive tables, separate from learner and lesson records."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models import UTCDateTime


class KnowledgeSourceRow(Base):
    __tablename__ = "knowledge_sources"
    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class KnowledgeRevisionRow(Base):
    __tablename__ = "knowledge_revisions"
    __table_args__ = (UniqueConstraint("source_id", "revision"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("knowledge_sources.source_id"), index=True)
    revision: Mapped[str] = mapped_column(String(32))
    creation_key: Mapped[UUID] = mapped_column(Uuid, unique=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    original_sha256: Mapped[str] = mapped_column(String(64))
    normalized_sha256: Mapped[str] = mapped_column(String(64))
    content_sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class KnowledgeEventRow(Base):
    __tablename__ = "knowledge_events"
    __table_args__ = (
        UniqueConstraint("revision_id", "sequence"),
        UniqueConstraint("revision_id", "operation_key"),
        CheckConstraint("sequence >= 0", name="sequence"),
        CheckConstraint(
            "state IN ('ingested','parsed','normalized','chunked','indexed','validated',"
            "'reviewed','approved','published','rejected','revoked','expired')",
            name="state",
        ),
        CheckConstraint(
            "action IN ('ingest','parse','normalize','chunk','index','validate','review',"
            "'approve','adopt_existing_review','publish','reject','revoke','expire')",
            name="action",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    revision_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_revisions.id"), index=True)
    sequence: Mapped[int]
    operation_key: Mapped[UUID] = mapped_column(Uuid)
    previous_event_sha256: Mapped[str | None] = mapped_column(String(64))
    previous_state: Mapped[str | None] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    content_sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class KnowledgeManifestRow(Base):
    __tablename__ = "knowledge_manifests"
    content_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class KnowledgePublicationRow(Base):
    __tablename__ = "knowledge_publications"
    __table_args__ = (CheckConstraint("sequence >= 0", name="sequence"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    sequence: Mapped[int] = mapped_column(unique=True)
    operation_key: Mapped[UUID] = mapped_column(Uuid, unique=True)
    previous_manifest_sha256: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_manifests.content_sha256")
    )
    manifest_sha256: Mapped[str] = mapped_column(ForeignKey("knowledge_manifests.content_sha256"))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    content_sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class KnowledgeIndexRow(Base):
    __tablename__ = "knowledge_indexes"
    index_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    manifest_sha256: Mapped[str] = mapped_column(
        ForeignKey("knowledge_manifests.content_sha256"), index=True
    )
    operation_key: Mapped[UUID] = mapped_column(Uuid, unique=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    embedding_space_sha256: Mapped[str] = mapped_column(String(64))
    model_id: Mapped[str] = mapped_column(String(120))
    dimensions: Mapped[int]
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class KnowledgeReceiptRow(Base):
    __tablename__ = "knowledge_receipts"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    request_id_sha256: Mapped[str] = mapped_column(String(64), index=True)
    manifest_sha256: Mapped[str] = mapped_column(
        ForeignKey("knowledge_manifests.content_sha256"), index=True
    )
    index_sha256: Mapped[str | None] = mapped_column(ForeignKey("knowledge_indexes.index_sha256"))
    content_sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
