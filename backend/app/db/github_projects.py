"""SQL implementation of the Project Learning persistence port.

Every context is short and closed before any provider work. The conditional
state update and database uniqueness constraints retain cross-worker safety.
"""

import json
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ApplicationError
from app.core.github_errors import unavailable
from app.db.github_models import (
    GitHubAuthorizationState,
    GitHubInstallationGrant,
    GitHubProjectLearningPath,
    GitHubProjectSnapshot,
    GitHubRepositoryConnection,
)
from app.db.session import Database
from app.domain.project_learning import canonical_digest, validate_learning_path
from app.repositories.github_projects import GitHubAuthorizationGrant, GitHubConnectionLease
from app.schemas.github_projects import (
    ConnectionView,
    ProjectLearningPath,
    ProjectSnapshot,
    RepositoryView,
)


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
        self,
        owner: UUID,
        installation: int,
        user_id: int,
        repository_ids: list[int],
        now: datetime,
        *,
        token_ciphertext: str,
        credential_expires_at: datetime,
    ) -> GitHubAuthorizationGrant:
        with self.database.session() as db, db.begin():
            changed = db.execute(
                update(GitHubInstallationGrant)
                .where(
                    GitHubInstallationGrant.owner_id == owner,
                    GitHubInstallationGrant.installation_id == installation,
                )
                .values(
                    github_user_id=user_id,
                    repository_ids=repository_ids,
                    authorized_at=now,
                    authorization_revision=GitHubInstallationGrant.authorization_revision + 1,
                    token_ciphertext=token_ciphertext,
                    credential_expires_at=credential_expires_at,
                    disconnected_at=None,
                )
            )
            if changed.rowcount == 0:  # type: ignore[attr-defined]
                row = GitHubInstallationGrant(
                    owner_id=owner,
                    installation_id=installation,
                    authorization_revision=1,
                    github_user_id=user_id,
                    repository_ids=repository_ids,
                    authorized_at=now,
                    token_ciphertext=token_ciphertext,
                    credential_expires_at=credential_expires_at,
                    disconnected_at=None,
                )
                db.add(row)
            db.flush()
            result = db.get(GitHubInstallationGrant, (owner, installation))
            if result is None:
                raise self._changed()
            return self._grant(result)

    @staticmethod
    def _changed() -> ApplicationError:
        return ApplicationError("github_access_changed", "GitHub access changed. Reconnect.", 409)

    @staticmethod
    def _grant(row: GitHubInstallationGrant) -> GitHubAuthorizationGrant:
        return GitHubAuthorizationGrant(
            owner_id=row.owner_id,
            installation_id=row.installation_id,
            github_user_id=row.github_user_id,
            repository_ids=tuple(row.repository_ids),
            token_ciphertext=row.token_ciphertext,
            credential_expires_at=row.credential_expires_at,
            disconnected_at=row.disconnected_at,
            authorization_revision=row.authorization_revision,
        )

    def authorization_grant(
        self, owner: UUID, installation: int
    ) -> GitHubAuthorizationGrant | None:
        with self.database.session() as db:
            row = db.get(GitHubInstallationGrant, (owner, installation))
            return self._grant(row) if row is not None else None

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
            status="disconnected" if row.disconnected_at is not None else "connected",
        )

    def connect(
        self,
        owner: UUID,
        installation: int,
        chosen: RepositoryView,
        now: datetime,
        *,
        authorization_revision: int,
    ) -> ConnectionView:
        try:
            with self.database.session() as db, db.begin():
                locked = db.execute(
                    update(GitHubInstallationGrant)
                    .where(
                        GitHubInstallationGrant.owner_id == owner,
                        GitHubInstallationGrant.installation_id == installation,
                        GitHubInstallationGrant.authorization_revision == authorization_revision,
                        GitHubInstallationGrant.disconnected_at.is_(None),
                        GitHubInstallationGrant.credential_expires_at > now,
                    )
                    .values(authorization_revision=authorization_revision)
                )
                if locked.rowcount != 1:  # type: ignore[attr-defined]
                    raise self._changed()
                existing = db.scalar(
                    select(GitHubRepositoryConnection).where(
                        GitHubRepositoryConnection.owner_id == owner,
                        GitHubRepositoryConnection.repository_id == chosen.repository_id,
                    )
                )
                if existing is not None:
                    if existing.installation_id != installation:
                        raise ApplicationError("conflict", "Repository installation changed.", 409)
                    if (
                        existing.disconnected_at is not None
                        or existing.full_name != chosen.full_name
                    ):
                        existing.disconnected_at = None
                        existing.connection_revision += 1
                        existing.full_name, existing.private = chosen.full_name, chosen.private
                        db.flush()
                    return self._view(existing)
                row = GitHubRepositoryConnection(
                    id=uuid4(),
                    owner_id=owner,
                    installation_id=installation,
                    repository_id=chosen.repository_id,
                    full_name=chosen.full_name,
                    private=chosen.private,
                    created_at=now,
                    connection_revision=1,
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

    def connection_lease(self, owner: UUID, identity: UUID) -> GitHubConnectionLease:
        with self.database.session() as db:
            row = db.get(GitHubRepositoryConnection, identity)
            if row is None or row.owner_id != owner:
                raise ApplicationError("not_found", "Connection not found.", 404)
            grant = db.get(GitHubInstallationGrant, (owner, row.installation_id))
            if grant is None:
                raise self._changed()
            return GitHubConnectionLease(
                owner_id=owner,
                connection=self._view(row),
                authorization_revision=grant.authorization_revision,
                connection_revision=row.connection_revision,
            )

    def lease_current(self, lease: GitHubConnectionLease, now: datetime) -> bool:
        with self.database.session() as db:
            connection = db.get(GitHubRepositoryConnection, UUID(lease.connection.id))
            grant = db.get(
                GitHubInstallationGrant, (lease.owner_id, lease.connection.installation_id)
            )
            return bool(
                connection is not None
                and connection.owner_id == lease.owner_id
                and connection.connection_revision == lease.connection_revision
                and connection.disconnected_at is None
                and grant is not None
                and grant.authorization_revision == lease.authorization_revision
                and grant.disconnected_at is None
                and grant.credential_expires_at is not None
                and grant.credential_expires_at > now
                and grant.token_ciphertext
            )

    def disconnect_installation(self, owner: UUID, installation: int, now: datetime) -> None:
        with self.database.session() as db, db.begin():
            db.execute(
                update(GitHubInstallationGrant)
                .where(
                    GitHubInstallationGrant.owner_id == owner,
                    GitHubInstallationGrant.installation_id == installation,
                    GitHubInstallationGrant.disconnected_at.is_(None),
                )
                .values(
                    authorization_revision=GitHubInstallationGrant.authorization_revision + 1,
                    disconnected_at=now,
                    token_ciphertext=None,
                )
            )
            if db.get(GitHubInstallationGrant, (owner, installation)) is None:
                raise ApplicationError("not_found", "Connection not found.", 404)

    def disconnect_connection(self, owner: UUID, identity: UUID, now: datetime) -> ConnectionView:
        with self.database.session() as db, db.begin():
            db.execute(
                update(GitHubRepositoryConnection)
                .where(
                    GitHubRepositoryConnection.id == identity,
                    GitHubRepositoryConnection.owner_id == owner,
                    GitHubRepositoryConnection.disconnected_at.is_(None),
                )
                .values(
                    connection_revision=GitHubRepositoryConnection.connection_revision + 1,
                    disconnected_at=now,
                )
            )
            row = db.get(GitHubRepositoryConnection, identity)
            if row is None or row.owner_id != owner:
                raise ApplicationError("not_found", "Connection not found.", 404)
            return self._view(row)

    def load_snapshot(self, identity: UUID, sha: str) -> ProjectSnapshot | None:
        with self.database.session() as db:
            row = db.get(GitHubProjectSnapshot, (identity, sha))
            return ProjectSnapshot.model_validate(row.payload) if row is not None else None

    def save_snapshot(
        self, value: ProjectSnapshot, now: datetime, *, lease: GitHubConnectionLease
    ) -> bool:
        if value.connection_id != lease.connection.id:
            raise self._changed()
        try:
            with self.database.session() as db, db.begin():
                grant = db.execute(
                    update(GitHubInstallationGrant)
                    .where(
                        GitHubInstallationGrant.owner_id == lease.owner_id,
                        GitHubInstallationGrant.installation_id == lease.connection.installation_id,
                        GitHubInstallationGrant.authorization_revision
                        == lease.authorization_revision,
                        GitHubInstallationGrant.disconnected_at.is_(None),
                        GitHubInstallationGrant.credential_expires_at > now,
                    )
                    .values(authorization_revision=lease.authorization_revision)
                )
                connection = db.execute(
                    update(GitHubRepositoryConnection)
                    .where(
                        GitHubRepositoryConnection.id == UUID(value.connection_id),
                        GitHubRepositoryConnection.owner_id == lease.owner_id,
                        GitHubRepositoryConnection.connection_revision == lease.connection_revision,
                        GitHubRepositoryConnection.disconnected_at.is_(None),
                    )
                    .values(connection_revision=lease.connection_revision)
                )
                if grant.rowcount != 1 or connection.rowcount != 1:  # type: ignore[attr-defined]
                    raise self._changed()
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

    @staticmethod
    def _learning_snapshot(session: Session, identity: UUID, sha: str) -> ProjectSnapshot:
        row = session.get(GitHubProjectSnapshot, (identity, sha))
        if row is None:
            raise ValueError("A generated path requires its pinned source snapshot")
        value = ProjectSnapshot.model_validate(row.payload)
        if (
            value.connection_id != str(identity)
            or value.commit_sha != sha
            or value.digest != row.digest
        ):
            raise ValueError("Stored snapshot identity does not match its row")
        return value

    def save_learning_path(
        self, value: ProjectLearningPath, *, lease: GitHubConnectionLease, now: datetime
    ) -> None:
        try:
            checked = ProjectLearningPath.model_validate_json(value.model_dump_json())
            if (
                checked.status != "ready"
                or checked.id is None
                or checked.generation is None
                or now.tzinfo is None
                or now.utcoffset() is None
                or checked.generation.generated_at > now
            ):
                raise ValueError("Only a complete generated result can be archived")
            identity, connection_id = UUID(checked.id), UUID(lease.connection.id)
            payload = checked.model_dump(mode="json")
            payload_digest = canonical_digest(payload)
            with self.database.session() as session, session.begin():
                # Enter through short write admission. Disconnect/reauthorization
                # cannot race a later insert, and no provider work runs here.
                grant = session.execute(
                    update(GitHubInstallationGrant)
                    .where(
                        GitHubInstallationGrant.owner_id == lease.owner_id,
                        GitHubInstallationGrant.installation_id == lease.connection.installation_id,
                        GitHubInstallationGrant.authorization_revision
                        == lease.authorization_revision,
                        GitHubInstallationGrant.disconnected_at.is_(None),
                        GitHubInstallationGrant.credential_expires_at > now,
                    )
                    .values(authorization_revision=lease.authorization_revision)
                )
                connection = session.execute(
                    update(GitHubRepositoryConnection)
                    .where(
                        GitHubRepositoryConnection.id == connection_id,
                        GitHubRepositoryConnection.owner_id == lease.owner_id,
                        GitHubRepositoryConnection.installation_id
                        == lease.connection.installation_id,
                        GitHubRepositoryConnection.connection_revision == lease.connection_revision,
                        GitHubRepositoryConnection.disconnected_at.is_(None),
                    )
                    .values(connection_revision=lease.connection_revision)
                )
                if grant.rowcount != 1 or connection.rowcount != 1:  # type: ignore[attr-defined]
                    raise self._changed()
                snapshot = self._learning_snapshot(session, connection_id, checked.commit_sha)
                validate_learning_path(checked, snapshot)
                existing = session.get(GitHubProjectLearningPath, identity)
                if existing is not None:
                    if (
                        existing.owner_id != lease.owner_id
                        or existing.connection_id != connection_id
                        or existing.commit_sha != checked.commit_sha
                        or existing.snapshot_digest != checked.snapshot_digest
                        or existing.generated_at != checked.generation.generated_at
                        or existing.payload_digest != payload_digest
                        or existing.payload != payload
                    ):
                        raise ValueError(
                            "A path identity already has a different immutable payload"
                        )
                    return
                session.add(
                    GitHubProjectLearningPath(
                        id=identity,
                        owner_id=lease.owner_id,
                        connection_id=connection_id,
                        commit_sha=checked.commit_sha,
                        snapshot_digest=checked.snapshot_digest,
                        payload=payload,
                        payload_digest=payload_digest,
                        generated_at=checked.generation.generated_at,
                    )
                )
            # Transaction context has committed before the service can release it.
        except ApplicationError:
            raise
        except Exception:
            raise unavailable() from None

    def load_learning_path(
        self, owner: UUID, identity: UUID, sha: str
    ) -> ProjectLearningPath | None:
        try:
            with self.database.session() as session:
                row = session.scalar(
                    select(GitHubProjectLearningPath)
                    .join(
                        GitHubRepositoryConnection,
                        GitHubRepositoryConnection.id == GitHubProjectLearningPath.connection_id,
                    )
                    .where(
                        GitHubProjectLearningPath.owner_id == owner,
                        GitHubRepositoryConnection.owner_id == owner,
                        GitHubProjectLearningPath.connection_id == identity,
                        GitHubProjectLearningPath.commit_sha == sha,
                    )
                    .order_by(
                        GitHubProjectLearningPath.generated_at.desc(),
                        GitHubProjectLearningPath.id.desc(),
                    )
                    .limit(1)
                )
                if row is None:
                    return None
                value = ProjectLearningPath.model_validate_json(json.dumps(row.payload))
                if (
                    value.status != "ready"
                    or value.id != str(row.id)
                    or value.commit_sha != row.commit_sha
                    or value.snapshot_digest != row.snapshot_digest
                    or value.generation is None
                    or value.generation.generated_at != row.generated_at
                    or canonical_digest(row.payload) != row.payload_digest
                ):
                    raise ValueError("Stored path identity or digest is inconsistent")
                snapshot = self._learning_snapshot(session, identity, sha)
                validate_learning_path(value, snapshot)
                return value
        except ApplicationError:
            raise
        except Exception:
            raise unavailable() from None
