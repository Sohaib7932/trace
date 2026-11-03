"""SQL implementation of the Project Learning persistence port.

Every context is short and closed before any provider work. The conditional
state update and database uniqueness constraints retain cross-worker safety.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.core.errors import ApplicationError
from app.db.github_models import (
    GitHubAuthorizationState,
    GitHubInstallationGrant,
    GitHubProjectSnapshot,
    GitHubRepositoryConnection,
)
from app.db.session import Database
from app.schemas.github_projects import ConnectionView, ProjectSnapshot, RepositoryView


class SqlGitHubProjectRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def reserve_state(self, owner: UUID, state_id: UUID, expiry: datetime) -> None:
        with self.database.session() as db, db.begin():
            db.add(
                GitHubAuthorizationState(
                    id=state_id, owner_id=owner, expires_at=expiry, consumed_at=None
                )
            )

    def consume_state(self, owner: UUID, state_id: UUID, now: datetime) -> bool:
        with self.database.session() as db, db.begin():
            changed = db.execute(
                update(GitHubAuthorizationState)
                .where(
                    GitHubAuthorizationState.id == state_id,
                    GitHubAuthorizationState.owner_id == owner,
                    GitHubAuthorizationState.consumed_at.is_(None),
                    GitHubAuthorizationState.expires_at > now,
                )
                .values(consumed_at=now)
            )
            return bool(changed.rowcount == 1)  # type: ignore[attr-defined]

    def bind_installation(
        self, owner: UUID, installation: int, user_id: int, repository_ids: list[int], now: datetime
    ) -> None:
        with self.database.session() as db, db.begin():
            row = db.get(GitHubInstallationGrant, (owner, installation))
            if row is None:
                row = GitHubInstallationGrant(owner_id=owner, installation_id=installation)
                db.add(row)
            row.github_user_id, row.repository_ids = user_id, repository_ids
            row.authorized_at = now

    def installations(self, owner: UUID) -> tuple[int, ...]:
        with self.database.session() as db:
            return tuple(
                db.scalars(
                    select(GitHubInstallationGrant.installation_id)
                    .where(
                        GitHubInstallationGrant.owner_id == owner,
                    )
                    .order_by(GitHubInstallationGrant.installation_id)
                ).all()
            )

    def installation_repository_ids(self, owner: UUID, installation: int) -> tuple[int, ...] | None:
        with self.database.session() as db:
            grant = db.get(GitHubInstallationGrant, (owner, installation))
            return tuple(grant.repository_ids) if grant is not None else None

    @staticmethod
    def _view(row: GitHubRepositoryConnection) -> ConnectionView:
        return ConnectionView(
            id=str(row.id),
            installation_id=row.installation_id,
            repository_id=row.repository_id,
            full_name=row.full_name,
            private=row.private,
        )

    def connect(
        self, owner: UUID, installation: int, chosen: RepositoryView, now: datetime
    ) -> ConnectionView:
        try:
            with self.database.session() as db, db.begin():
                existing = db.scalar(
                    select(GitHubRepositoryConnection).where(
                        GitHubRepositoryConnection.owner_id == owner,
                        GitHubRepositoryConnection.repository_id == chosen.repository_id,
                    )
                )
                if existing is not None:
                    if existing.installation_id != installation:
                        raise ApplicationError("conflict", "Repository installation changed.", 409)
                    return self._view(existing)
                row = GitHubRepositoryConnection(
                    id=uuid4(),
                    owner_id=owner,
                    installation_id=installation,
                    repository_id=chosen.repository_id,
                    full_name=chosen.full_name,
                    private=chosen.private,
                    created_at=now,
                )
                db.add(row)
                db.flush()
                return self._view(row)
        except IntegrityError:
            raise ApplicationError("conflict", "Retry the repository connection.", 409) from None

    def connections(self, owner: UUID) -> tuple[ConnectionView, ...]:
        with self.database.session() as db:
            return tuple(
                self._view(row)
                for row in db.scalars(
                    select(GitHubRepositoryConnection)
                    .where(
                        GitHubRepositoryConnection.owner_id == owner,
                    )
                    .order_by(GitHubRepositoryConnection.created_at)
                ).all()
            )

    def owned_connection(self, owner: UUID, identity: UUID) -> ConnectionView:
        with self.database.session() as db:
            row = db.get(GitHubRepositoryConnection, identity)
            if row is None or row.owner_id != owner:
                raise ApplicationError("not_found", "Connection not found.", 404)
            return self._view(row)

    def load_snapshot(self, identity: UUID, sha: str) -> ProjectSnapshot | None:
        with self.database.session() as db:
            row = db.get(GitHubProjectSnapshot, (identity, sha))
            return ProjectSnapshot.model_validate(row.payload) if row is not None else None

    def save_snapshot(self, value: ProjectSnapshot, now: datetime) -> bool:
        try:
            with self.database.session() as db, db.begin():
                db.add(
                    GitHubProjectSnapshot(
                        connection_id=UUID(value.connection_id),
                        commit_sha=value.commit_sha,
                        digest=value.digest,
                        payload=value.model_dump(mode="json"),
                        created_at=now,
                    )
                )
            return True
        except IntegrityError:
            return False
