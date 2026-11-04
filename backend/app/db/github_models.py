"""Private owner-bound GitHub grants and immutable pinned snapshots; no tokens."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models import UTCDateTime


class GitHubAuthorizationState(Base):
    __tablename__ = "github_authorization_states"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class GitHubInstallationGrant(Base):
    __tablename__ = "github_installation_grants"
    __table_args__ = (
        CheckConstraint("installation_id > 0 AND github_user_id > 0", name="positive_ids"),
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    installation_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    github_user_id: Mapped[int] = mapped_column(BigInteger)
    repository_ids: Mapped[list[int]] = mapped_column(JSON)
    authorized_at: Mapped[datetime] = mapped_column(UTCDateTime())
    token_ciphertext: Mapped[str | None] = mapped_column(Text())
    credential_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    disconnected_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    authorization_revision: Mapped[int] = mapped_column(default=1, server_default="1")


class GitHubRepositoryConnection(Base):
    __tablename__ = "github_repository_connections"
    __table_args__ = (
        UniqueConstraint("owner_id", "repository_id"),
        ForeignKeyConstraint(
            ["owner_id", "installation_id"],
            ["github_installation_grants.owner_id", "github_installation_grants.installation_id"],
        ),
        CheckConstraint("repository_id > 0 AND installation_id > 0", name="positive_ids"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    installation_id: Mapped[int] = mapped_column(BigInteger)
    repository_id: Mapped[int] = mapped_column(BigInteger)
    full_name: Mapped[str] = mapped_column(String(201))
    private: Mapped[bool] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    disconnected_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    connection_revision: Mapped[int] = mapped_column(default=1, server_default="1")


class GitHubProjectSnapshot(Base):
    __tablename__ = "github_project_snapshots"
    __table_args__ = (
        CheckConstraint("length(commit_sha) = 40 AND length(digest) = 64", name="digest_lengths"),
    )
    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("github_repository_connections.id"), primary_key=True
    )
    commit_sha: Mapped[str] = mapped_column(String(40), primary_key=True)
    digest: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
