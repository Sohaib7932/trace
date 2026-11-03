"""Audit metadata and display attribution cannot diverge from the bound answer."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.db.knowledge_models import KnowledgeReceiptRow
from app.domain.learning import LearningError
from app.support.receipts import VersionedSupportAnswer
from tests.integration.test_knowledge_archive import archive as archive  # noqa: F401
from tests.integration.test_knowledge_archive import (
    publish_corpus,
    synthetic_index,
    versioned_answer,
)


@pytest.mark.parametrize("mismatch", ["upgrade", "downgrade", "different_index", "title"])
def test_release_receipt_rejects_relabelled_retrieval_or_forged_source_title(archive, mismatch):
    publish_corpus(archive)
    snapshot = archive.knowledge.snapshot()
    index = synthetic_index(snapshot, archive.now[0])
    archive.service.store_index(index, key=str(uuid4()), actor=archive.admin)
    raw = versioned_answer(snapshot).model_dump(mode="json")
    kwargs = {}
    if mismatch == "upgrade":
        kwargs = {"retrieval_profile": "hybrid", "index_sha256": index.index_sha256}
    elif mismatch in {"downgrade", "different_index"}:
        raw.update(retrieval_profile="hybrid", index_sha256=index.index_sha256)
        if mismatch == "different_index":
            kwargs = {"retrieval_profile": "hybrid", "index_sha256": "0" * 64}
    else:
        raw["response"]["references"][0]["source_name"] = "A different approved-looking source"
    bound = VersionedSupportAnswer.model_validate(raw)
    with pytest.raises(LearningError) as error:
        archive.service.authorize_release(
            bound, actor=archive.learner, request_id="synthetic-binding-check", **kwargs
        )
    assert error.value.code == "conflict"
    with archive.database.session() as session:
        assert session.scalar(select(func.count()).select_from(KnowledgeReceiptRow)) == 0
