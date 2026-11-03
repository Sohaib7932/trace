"""Actual disposable PostgreSQL archive checks; never connects to a hosted database."""

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.db import knowledge_models as k
from app.db.knowledge import SqlKnowledgeRepository
from app.services.knowledge import KnowledgeGovernanceService
from app.support.database import DatabaseSupportKnowledge
from tests.integration.test_knowledge_archive import (
    archive_context,
    publish_corpus,
    versioned_answer,
)


def test_postgresql_import_publication_release_and_new_service_readback(database):
    context = archive_context(database)
    histories, publication = publish_corpus(context)
    receipt = context.service.authorize_release(
        versioned_answer(context.knowledge.snapshot()),
        actor=context.learner,
        request_id="disposable-postgres-proof",
    )
    repository = SqlKnowledgeRepository(database)
    restarted = DatabaseSupportKnowledge(repository, lambda: context.now[0]).snapshot()
    assert restarted.available and restarted.manifest_sha256 == publication.manifest_sha256
    assert len(restarted.sources) == 9
    service = KnowledgeGovernanceService(repository, lambda: context.now[0])
    assert service.get_receipt(receipt.id, actor=context.admin) == receipt
    assert service.get(histories[0].revision.id, actor=context.admin).state == "published"
    with pytest.raises(IntegrityError), database.session() as session, session.begin():
        session.execute(delete(k.KnowledgeRevisionRow))
    with database.session() as session:
        assert len(session.scalars(select(k.KnowledgeRevisionRow)).all()) == 9
