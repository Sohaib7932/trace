"""Immutable repository-knowledge persistence, separate from legacy snapshots."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.repositories.github_projects import GitHubConnectionLease
from app.schemas.project_knowledge import RepositoryKnowledgeSnapshot


class ProjectKnowledgeRepository(Protocol):
    def load(self, connection_id: UUID, sha: str) -> RepositoryKnowledgeSnapshot | None: ...
    def save(
        self, value: RepositoryKnowledgeSnapshot, now: datetime, lease: GitHubConnectionLease
    ) -> bool: ...
