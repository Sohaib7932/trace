"""Persistence port for App state, grants, owned connections and pinned snapshots."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.schemas.github_projects import ConnectionView, ProjectSnapshot, RepositoryView


@dataclass(frozen=True)
class GitHubAuthorizationGrant:
    owner_id: UUID
    installation_id: int
    github_user_id: int
    repository_ids: tuple[int, ...]
    credential_expires_at: datetime | None
    disconnected_at: datetime | None
    authorization_revision: int
    token_ciphertext: str | None = field(repr=False)


@dataclass(frozen=True)
class GitHubConnectionLease:
    owner_id: UUID
    connection: ConnectionView
    authorization_revision: int
    connection_revision: int


class GitHubProjectRepository(Protocol):
    def reserve_state(self, owner: UUID, state_id: UUID, expiry: datetime) -> None: ...
    def consume_state(self, owner: UUID, state_id: UUID, now: datetime) -> bool: ...
    def bind_installation(
        self,
        owner: UUID,
        installation: int,
        user_id: int,
        repository_ids: list[int],
        now: datetime,
        *,
        token_ciphertext: str,
        credential_expires_at: datetime,
    ) -> GitHubAuthorizationGrant: ...
    def authorization_grant(
        self, owner: UUID, installation: int
    ) -> GitHubAuthorizationGrant | None: ...
    def installations(self, owner: UUID) -> tuple[int, ...]: ...
    def installation_repository_ids(
        self, owner: UUID, installation: int
    ) -> tuple[int, ...] | None: ...
    def connect(
        self,
        owner: UUID,
        installation: int,
        chosen: RepositoryView,
        now: datetime,
        *,
        authorization_revision: int,
    ) -> ConnectionView: ...
    def connections(self, owner: UUID) -> tuple[ConnectionView, ...]: ...
    def owned_connection(self, owner: UUID, identity: UUID) -> ConnectionView: ...
    def connection_lease(self, owner: UUID, identity: UUID) -> GitHubConnectionLease: ...
    def lease_current(self, lease: GitHubConnectionLease, now: datetime) -> bool: ...
    def disconnect_installation(self, owner: UUID, installation: int, now: datetime) -> None: ...
    def disconnect_connection(
        self, owner: UUID, identity: UUID, now: datetime
    ) -> ConnectionView: ...
    def load_snapshot(self, identity: UUID, sha: str) -> ProjectSnapshot | None: ...
    def save_snapshot(
        self, value: ProjectSnapshot, now: datetime, *, lease: GitHubConnectionLease
    ) -> bool: ...
