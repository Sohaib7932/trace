"""Bounded derived indexing through ports; no HTTP, SQL adapter or provider SDK."""

import hashlib
from collections.abc import Callable
from typing import Protocol

from app.core.embedding_settings import EmbeddingSettings
from app.core.errors import ApplicationError
from app.domain.accounts import AuthenticatedAccount
from app.domain.clock import Clock, utc_now
from app.domain.learning import LearningError
from app.repositories.knowledge import KnowledgeRepository
from app.schemas.embeddings import EmbeddingBatchResult, EmbeddingPurpose
from app.services.knowledge import KnowledgeGovernanceService
from app.support.database import archive_snapshot
from app.support.embedding_index import EmbeddingIndex, compose_index, document_inputs


class KnowledgeEmbeddingClient(Protocol):
    @property
    def settings(self) -> EmbeddingSettings: ...

    def embed(
        self,
        texts: tuple[str, ...],
        purpose: EmbeddingPurpose,
        *,
        timeout_seconds: float | None = None,
        subject: str | None = None,
    ) -> EmbeddingBatchResult: ...


class KnowledgeIndexingService:
    def __init__(
        self,
        repository: KnowledgeRepository,
        embeddings: KnowledgeEmbeddingClient,
        governance: KnowledgeGovernanceService,
        *,
        clock: Clock = utc_now,
        remaining_seconds: Callable[[], float],
    ) -> None:
        self.repository, self.embeddings, self.governance = repository, embeddings, governance
        self.clock, self.remaining_seconds = clock, remaining_seconds

    def build(self, *, key: str, actor: AuthenticatedAccount) -> EmbeddingIndex:
        # Reuse the governance authority, including expiry, before acquiring work.
        now = self.governance._actor(actor)
        try:
            with self.repository.read() as store:
                store.require_role(actor.account.id, "admin")
                prior = store.index_by_key(key)
                snapshot = archive_snapshot(store, now) if prior is None else None
        except LearningError:
            raise
        except Exception:
            raise ApplicationError(
                "dependency_unavailable", "Published knowledge is unavailable.", 503
            ) from None
        # Replay performs no additional embedding RPC and still checks current permission.
        if prior is not None:
            return self.governance.store_index(prior, key=key, actor=actor)
        if self.embeddings.settings.mode != "gemini_free":
            raise ApplicationError(
                "dependency_unavailable", "Live embedding indexing is disabled.", 503
            )
        if snapshot is None or not snapshot.available:
            raise ApplicationError(
                "dependency_unavailable", "Published knowledge is unavailable.", 503
            )
        inputs = document_inputs(snapshot)
        if len(inputs) > 100:
            raise ApplicationError(
                "dependency_unavailable", "Knowledge exceeds the indexing batch limit.", 503
            )
        # The consistent read has closed. No database transaction spans this RPC.
        embedded = self.embeddings.embed(
            inputs,
            "document",
            timeout_seconds=self.remaining_seconds(),
            subject="knowledge-index:" + hashlib.sha256(str(actor.account.id).encode()).hexdigest(),
        )
        if embedded.status != "success":
            raise ApplicationError(
                "dependency_unavailable", "Embedding provider is unavailable.", 503
            )
        index = compose_index(
            snapshot, embedded, created_at=self.clock(), scope="production_candidate"
        )
        # Fresh account, manifest and approval checks occur in a short transaction.
        return self.governance.store_index(index, key=key, actor=actor)
