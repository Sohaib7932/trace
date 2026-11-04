"""Short SQL transactions for immutable knowledge artifacts; no network calls."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.core.errors import ApplicationError
from app.core.github_errors import unavailable
from app.db.github_models import GitHubInstallationGrant, GitHubRepositoryConnection
from app.db.project_knowledge_models import GitHubRepositoryKnowledge
from app.db.session import Database
from app.repositories.github_projects import GitHubConnectionLease
from app.schemas.project_knowledge import RepositoryKnowledgeSnapshot
from app.services.project_ingestion import knowledge_digest


class SqlProjectKnowledgeRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def load(self, connection_id: UUID, sha: str) -> RepositoryKnowledgeSnapshot | None:
        with self.database.session() as session:
            row = session.get(GitHubRepositoryKnowledge, (connection_id, sha))
            if row is None:
                return None
            try:
                value = RepositoryKnowledgeSnapshot.model_validate(row.payload)
                if (
                    value.connection_id != str(connection_id)
                    or value.commit_sha != sha
                    or value.digest != row.digest
                    or knowledge_digest(value) != row.digest
                ):
                    raise ValueError()
            except ValueError:
                raise unavailable() from None
            return value

    def save(
        self, value: RepositoryKnowledgeSnapshot, now: datetime, lease: GitHubConnectionLease
    ) -> bool:
        if knowledge_digest(value) != value.digest:
            raise unavailable()
        if (
            value.connection_id != lease.connection.id
            or value.repository.repository_id != lease.connection.repository_id
            or value.repository.full_name != lease.connection.full_name
            or value.repository.private != lease.connection.private
        ):
            raise unavailable()
        try:
            with self.database.session() as session, session.begin():
                # Short row locks serialize finalization with disconnect/reauthorization.
                # No provider or network call occurs inside this transaction.
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
                    .values(authorization_revision=GitHubInstallationGrant.authorization_revision)
                )
                connection = session.execute(
                    update(GitHubRepositoryConnection)
                    .where(
                        GitHubRepositoryConnection.id == UUID(value.connection_id),
                        GitHubRepositoryConnection.owner_id == lease.owner_id,
                        GitHubRepositoryConnection.connection_revision == lease.connection_revision,
                        GitHubRepositoryConnection.disconnected_at.is_(None),
                    )
                    .values(connection_revision=GitHubRepositoryConnection.connection_revision)
                )
                if grant.rowcount != 1 or connection.rowcount != 1:  # type: ignore[attr-defined]
                    raise ApplicationError("conflict", "Repository authorization changed.", 409)
                session.add(
                    GitHubRepositoryKnowledge(
                        connection_id=UUID(value.connection_id),
                        commit_sha=value.commit_sha,
                        digest=value.digest,
                        payload=value.model_dump(mode="json"),
                        created_at=now,
                    )
                )
            return True
        except IntegrityError:
            # Only an identical durable artifact can satisfy an idempotent replay.
            existing = self.load(UUID(value.connection_id), value.commit_sha)
            if existing is None or existing.digest != value.digest:
                raise unavailable() from None
            return False
