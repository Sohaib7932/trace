"""Index orchestration uses ports and releases source reads before external work."""

from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import update

from app.ai.embeddings import BoundedEmbeddingClient
from app.core.embedding_settings import EmbeddingSettings
from app.db import models as m
from app.domain.learning import LearningError
from app.services.knowledge_indexing import KnowledgeIndexingService
from tests.integration.test_knowledge_archive import archive as archive  # noqa: F401
from tests.integration.test_knowledge_archive import publish_corpus
from tests.integration.test_knowledge_index_http import SyntheticLiveWire


class TrackedRepository:
    def __init__(self, repository):
        self.repository, self.active_reads = repository, 0

    @contextmanager
    def read(self):
        with self.repository.read() as store:
            self.active_reads += 1
            try:
                yield store
            finally:
                self.active_reads -= 1

    def write(self):
        return self.repository.write()


def test_index_service_closes_read_transaction_before_embedding_and_replays_without_rpc(archive):
    publish_corpus(archive)
    repository = TrackedRepository(archive.repository)

    def outside_transaction(request):
        assert repository.active_reads == 0
        # A real independent write must commit while the simulated provider runs.
        with repository.write() as store:
            store.require_role(archive.admin.account.id, "admin")

    transport = SyntheticLiveWire(callback=None)
    original_embed = transport.embed

    def embed(request):
        outside_transaction(request)
        return original_embed(request)

    transport.embed = embed
    client = BoundedEmbeddingClient(
        EmbeddingSettings(
            _env_file=None, mode="gemini_free", free_tier_unbilled_project_confirmed=True
        ),
        transport,
    )
    service = KnowledgeIndexingService(
        repository,
        client,
        archive.service,
        clock=lambda: archive.now[0],
        remaining_seconds=lambda: 5,
    )
    try:
        key = str(uuid4())
        first = service.build(key=key, actor=archive.admin)
        assert len(first.passages) == 19 and first.metadata.scope == "production_candidate"
        assert service.build(key=key, actor=archive.admin) == first
        assert len(transport.calls) == 1 and repository.active_reads == 0
    finally:
        client.close()


def test_index_service_rechecks_database_role_before_any_embedding_call(archive):
    transport = SyntheticLiveWire()
    client = BoundedEmbeddingClient(
        EmbeddingSettings(
            _env_file=None, mode="gemini_free", free_tier_unbilled_project_confirmed=True
        ),
        transport,
    )
    service = KnowledgeIndexingService(
        archive.repository,
        client,
        archive.service,
        clock=lambda: archive.now[0],
        remaining_seconds=lambda: 5,
    )
    with archive.database.session() as session, session.begin():
        session.execute(
            update(m.User).where(m.User.id == archive.admin.account.id).values(status="disabled")
        )
    try:
        with pytest.raises(LearningError):
            service.build(key=str(uuid4()), actor=archive.admin)
        assert not transport.calls
    finally:
        client.close()
