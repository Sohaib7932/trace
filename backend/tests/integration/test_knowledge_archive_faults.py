"""Fail-closed persisted-read faults without bypassing guards or changing stored rows."""

import json
from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm.attributes import set_committed_value

from app.db import knowledge_models as k
from app.domain.knowledge import KnowledgeEvent, sealed
from app.domain.learning import LearningError
from app.schemas.support import SupportQuestion
from app.services.knowledge import KnowledgeGovernanceService
from app.services.support import SupportService
from app.support.database import DatabaseSupportKnowledge
from app.support.receipts import VersionedSupportAnswer
from tests.integration.test_knowledge_archive import archive as archive  # noqa: F401
from tests.integration.test_knowledge_archive import (
    publish_corpus,
    synthetic_index,
    versioned_answer,
)


class FaultedReadRepository:
    """Simulate a driver returning corrupted metadata, never persist test corruption."""

    def __init__(self, repository, corrupt):
        self.repository, self.corrupt = repository, corrupt
        self.fault_count = 0

    @contextmanager
    def _scope(self, write):
        scope = self.repository.write if write else self.repository.read
        with scope() as store:

            def loaded(session, row):
                if self.corrupt(row):
                    self.fault_count += 1

            event.listen(store.session, "loaded_as_persistent", loaded)
            try:
                yield store
            finally:
                # Committed-value injection changes only this session's received
                # row. It never queues an UPDATE or disables an immutable guard.
                assert not store.session.dirty
                event.remove(store.session, "loaded_as_persistent", loaded)

    def read(self):
        return self._scope(False)

    def write(self):
        return self._scope(True)


class ForbiddenAssistant:
    def select(self, *args, **kwargs):
        pytest.fail("Corrupt or unavailable sources reached a provider")


def corrupt_source_row(kind, row):
    targets = {
        "revision": (k.KnowledgeRevisionRow, "normalized_sha256", "f" * 64),
        "event": (k.KnowledgeEventRow, "sequence", 1000),
        "manifest": (k.KnowledgeManifestRow, "content_sha256", "f" * 64),
        "publication": (k.KnowledgePublicationRow, "manifest_sha256", "f" * 64),
    }
    if kind in targets:
        model, column, value = targets[kind]
        if isinstance(row, model):
            assert json.loads(json.dumps(row.payload)) == row.payload
            set_committed_value(row, column, value)
            return True
    elif (
        isinstance(row, k.KnowledgeEventRow)
        and row.action == "chunk"
        and len(row.payload["chunks"]) > 1
    ):
        original = KnowledgeEvent.model_validate_json(json.dumps(row.payload))
        changed = sealed(
            KnowledgeEvent,
            **(
                original.model_dump(exclude={"content_sha256"})
                | {"chunks": tuple(reversed(original.chunks))}
            ),
        )
        # The individual event is fully valid and its fingerprint matches its
        # normalized column. Source/chunk/event-chain integrity must still reject it.
        set_committed_value(row, "payload", changed.model_dump(mode="json"))
        set_committed_value(row, "content_sha256", changed.content_sha256)
        return True
    return False


@pytest.mark.parametrize("kind", ["revision", "event", "manifest", "publication", "chunk"])
def test_valid_json_with_mismatched_persisted_source_metadata_never_releases_quotes(archive, kind):
    publish_corpus(archive)
    assert archive.knowledge.available
    repository = FaultedReadRepository(
        archive.repository, lambda row: corrupt_source_row(kind, row)
    )
    knowledge = DatabaseSupportKnowledge(repository, lambda: archive.now[0])
    snapshot = knowledge.snapshot()
    assert not snapshot.available and snapshot.sources == () and snapshot.manifest_sha256 is None
    assert [issue.code for issue in snapshot.issues] == ["package_unavailable"]
    response = SupportService(ForbiddenAssistant(), knowledge).answer(
        SupportQuestion(question="password recovery expired link")
    )
    assert response.status == "unavailable" and response.references == ()
    assert "payload" not in response.model_dump_json() and repository.fault_count >= 1
    assert archive.knowledge.available  # The actual immutable stored rows were untouched.


@pytest.mark.parametrize("kind", ["index", "receipt"])
def test_valid_derived_json_with_mismatched_sql_metadata_cannot_authorize_release(archive, kind):
    publish_corpus(archive)
    snapshot = archive.knowledge.snapshot()
    index = synthetic_index(snapshot, archive.now[0])
    archive.service.store_index(index, key=str(uuid4()), actor=archive.admin)
    answer = VersionedSupportAnswer.model_validate(
        versioned_answer(snapshot).model_dump(warnings=False)
        | {"retrieval_profile": "hybrid", "index_sha256": index.index_sha256}
    )
    receipt = archive.service.authorize_release(
        answer,
        actor=archive.learner,
        request_id="derived-integrity-test",
        retrieval_profile="hybrid",
        index_sha256=index.index_sha256,
    )

    def corrupt(row):
        if kind == "index" and isinstance(row, k.KnowledgeIndexRow):
            assert json.loads(json.dumps(row.payload)) == row.payload
            set_committed_value(row, "model_id", "corrupted-model-metadata")
            return True
        if kind == "receipt" and isinstance(row, k.KnowledgeReceiptRow):
            assert json.loads(json.dumps(row.payload)) == row.payload
            set_committed_value(row, "request_id_sha256", "f" * 64)
            return True
        return False

    repository = FaultedReadRepository(archive.repository, corrupt)
    service = KnowledgeGovernanceService(repository, lambda: archive.now[0])
    with pytest.raises(LearningError) as error:
        service.authorize_release(
            answer,
            actor=archive.learner,
            request_id="derived-integrity-test",
            receipt_id=receipt.id if kind == "receipt" else None,
            retrieval_profile="hybrid",
            index_sha256=index.index_sha256,
        )
    assert error.value.code == "conflict"
    assert str(error.value) == "Knowledge archive integrity failed."
    assert repository.fault_count >= 1
    with archive.repository.read() as store:
        assert store.index(index.index_sha256) == index
        assert store.receipt(receipt.id) == receipt
    with archive.database.session() as session:
        assert session.scalar(select(func.count()).select_from(k.KnowledgeReceiptRow)) == 1


def test_repository_database_exception_is_sanitized_and_support_has_no_quotes(archive, monkeypatch):
    publish_corpus(archive)
    private = "synthetic-private-storage-failure-canary"

    def unavailable_session():
        raise SQLAlchemyError(private)

    with monkeypatch.context() as patch:
        patch.setattr(archive.database, "session", unavailable_session)
        with pytest.raises(LearningError) as error, archive.repository.read():
            pytest.fail("An unavailable database yielded a repository session")
        assert error.value.code == "dependency_unavailable"
        assert str(error.value) == "Knowledge storage is unavailable."
        assert private not in str(error.value)
        snapshot = archive.knowledge.snapshot()
        assert not snapshot.available and snapshot.sources == ()
        assert private not in snapshot.model_dump_json()
        response = SupportService(ForbiddenAssistant(), archive.knowledge).answer(
            SupportQuestion(question="password recovery expired link")
        )
        assert response.status == "unavailable" and response.references == ()
        assert private not in response.model_dump_json()
    assert archive.knowledge.available
