"""Separate immutable V2 repository artifacts; historical V1 hashes stay pinned."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models import UTCDateTime


class GitHubRepositoryKnowledge(Base):
    __tablename__ = "github_repository_knowledge"
    __table_args__ = (
        CheckConstraint("length(commit_sha) = 40 AND length(digest) = 64", name="digest_lengths"),
    )
    connection_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("github_repository_connections.id"), primary_key=True
    )
    commit_sha: Mapped[str] = mapped_column(String(40), primary_key=True)
    digest: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
