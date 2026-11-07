"""Durable governed customer copy in disposable databases; no real accounts/providers."""

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from app.db import knowledge_models as k
from app.db import models as m
from app.db.knowledge import SqlKnowledgeRepository
from app.db.session import Database
from app.domain.accounts import Account, AuthenticatedAccount, VerifiedIdentity
from app.domain.learning import LearningError
from app.schemas.embeddings import EmbeddingIndexMetadata, UnitEmbedding, text_digest
from app.schemas.support import SupportQuestion, SupportReference, SupportResponse
from app.services.knowledge import KnowledgeGovernanceService
from app.support.database import DatabaseSupportKnowledge
from app.support.embedding_index import EmbeddingIndex, IndexedPassage
from app.support.knowledge import load_corpus_package
from app.support.receipts import VersionedSupportAnswer
from app.support.versioning import canonical_digest


def archive_context(database):
    package = load_corpus_package()
    now = [package.reviewed_at + timedelta(seconds=1)]
    admin_id, learner_id = uuid4(), uuid4()
    with database.session() as session, session.begin():
        for identifier, roles in ((admin_id, ("learner", "admin")), (learner_id, ("learner",))):
            session.add(
                m.User(id=identifier, status="active", created_at=now[0], updated_at=now[0])
            )
            session.flush()
            session.add_all(m.UserRole(user_id=identifier, role=role) for role in roles)

    def principal(identifier, roles):
        return AuthenticatedAccount(
            Account(identifier, now[0], "active", roles),
            VerifiedIdentity(
                "https://synthetic.example.invalid/auth/v1",
                str(identifier),
                now[0] + timedelta(days=60),
            ),
        )

    repository = SqlKnowledgeRepository(database)
    return SimpleNamespace(
        database=database,
        package=package,
        now=now,
        repository=repository,
        admin=principal(admin_id, ("learner", "admin")),
        learner=principal(learner_id, ("learner",)),
        service=KnowledgeGovernanceService(repository, lambda: now[0], lambda: package),
        knowledge=DatabaseSupportKnowledge(repository, lambda: now[0]),
    )


@pytest.fixture
def archive(database):
    return archive_context(database)


def publish_corpus(context):
    histories = context.service.import_reviewed_corpus(
        key=str(uuid4()), actor=context.admin, adopt_existing_review=True
    )
    publication = context.service.publish(
        tuple(history.revision.id for history in histories),
        key=str(uuid4()),
        expected_sequence=-1,
        actor=context.admin,
        reason="Explicit publication of the exact existing approved customer corpus.",
    )
    return histories, publication


def test_default_import_is_durable_validated_without_approval_or_publication(archive, monkeypatch):
    key = str(uuid4())
    histories = archive.service.import_reviewed_corpus(key=key, actor=archive.admin)
    assert len(histories) == 9 and sum(len(h.chunks) for h in histories) == 19
    assert all(history.state == "validated" and history.approval is None for history in histories)
    assert not archive.knowledge.available
    with monkeypatch.context() as patch:
        patch.setattr(archive.repository, "write", forbid_archive_write)
        assert archive.service.import_reviewed_corpus(key=key, actor=archive.admin) == histories
    with archive.database.session() as session:
        assert session.scalar(select(func.count()).select_from(k.KnowledgeRevisionRow)) == 9
        assert session.scalar(select(func.count()).select_from(k.KnowledgePublicationRow)) == 0
        assert session.scalar(select(func.count()).select_from(m.Learner)) == 0
    for history in histories:
        assert history.revision.original_json == history.revision.normalized_json
        assert (
            history.revision.normalized_sha256
            == archive.package.document_digests[history.revision.source_id]
        )
        assert history.revision.imported_review.reviewer_label == archive.package.reviewed_by


def forbid_archive_write():
    pytest.fail(
        "A complete import replay must read the archive without opening a write transaction"
    )


def test_partial_import_resumes_and_published_histories_replay_without_writes(archive, monkeypatch):
    key = str(uuid4())
    import_args = {"key": key, "actor": archive.admin, "adopt_existing_review": True}
    advance = archive.service.advance

    def interrupt_index(*args, **kwargs):
        if kwargs["action"] == "index":
            raise RuntimeError("Synthetic interruption")
        return advance(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(archive.service, "advance", interrupt_index)
        with pytest.raises(RuntimeError, match="Synthetic interruption"):
            archive.service.import_reviewed_corpus(**import_args)

    histories = archive.service.import_reviewed_corpus(**import_args)
    assert len(histories) == 9 and all(history.state == "approved" for history in histories)
    with archive.database.session() as session:
        assert session.scalar(select(func.count()).select_from(k.KnowledgeRevisionRow)) == 9
        assert session.scalar(select(func.count()).select_from(k.KnowledgeEventRow)) == 63
    archive.service.publish(
        tuple(history.revision.id for history in histories),
        key=str(uuid4()),
        expected_sequence=-1,
        actor=archive.admin,
        reason="Publish the exact reviewed corpus after an interrupted import.",
    )

    monkeypatch.setattr(archive.repository, "write", forbid_archive_write)
    replay = archive.service.import_reviewed_corpus(**import_args)
    assert all(history.state == "published" for history in replay)
    assert [history.revision for history in replay] == [history.revision for history in histories]
    assert archive.service.import_reviewed_corpus(key=key, actor=archive.admin) == replay


def test_completed_import_replay_rechecks_the_admin_role(archive):
    key = str(uuid4())
    archive.service.import_reviewed_corpus(key=key, actor=archive.admin)
    with archive.database.session() as session, session.begin():
        session.execute(
            delete(m.UserRole).where(
                m.UserRole.user_id == archive.admin.account.id, m.UserRole.role == "admin"
            )
        )

    with pytest.raises(LearningError) as error:
        archive.service.import_reviewed_corpus(key=key, actor=archive.admin)
    assert error.value.code == "forbidden"


def test_explicit_review_adoption_preserves_attribution_then_separate_publication(archive):
    histories, publication = publish_corpus(archive)
    snapshot = archive.knowledge.snapshot()
    assert snapshot.available and snapshot.manifest_sha256 == publication.manifest_sha256
    assert len(snapshot.sources) == 9 and sum(len(s.passages) for s in snapshot.sources) == 19
    for history in histories:
        current = archive.service.get(history.revision.id, actor=archive.admin)
        assert current.state == "published"
        assert current.approval.review_origin == "imported_record"
        assert current.approval.historical_reviewer_label == archive.package.reviewed_by
        assert current.approval.historical_reviewed_at == archive.package.reviewed_at
        assert current.approval.actor_id == str(archive.admin.account.id)


def versioned_answer(snapshot):
    matches = snapshot.retrieve(SupportQuestion(question="password recovery expired link"))
    match = matches[0]
    return VersionedSupportAnswer(
        response=SupportResponse(
            status="answered",
            message="Relevant approved documentation is quoted below.",
            references=(
                SupportReference(
                    source_id=match.source_id,
                    source_name=match.title,
                    passage_id=match.passage_id,
                    quote=match.text,
                ),
            ),
            source="ai",
        ),
        manifest_sha256=snapshot.manifest_sha256,
        passages=(snapshot.resolve(match),),
    )


def approved_revision(context, document=None, revision="2.0.0"):
    document = document or context.package.documents[0]
    history = context.service.ingest(
        document, revision=revision, key=str(uuid4()), actor=context.admin
    )
    for action in ("parse", "normalize", "chunk", "index", "validate"):
        history = context.service.advance(
            history.revision.id,
            action=action,
            expected_sequence=history.sequence,
            key=str(uuid4()),
            actor=context.admin,
            reason="Explicit deterministic technical checkpoint.",
        )
    history = context.service.advance(
        history.revision.id,
        action="review",
        expected_sequence=history.sequence,
        key=str(uuid4()),
        actor=context.admin,
        reason="Human review of the pinned customer-copy digest.",
        reviewed_document_sha256=history.revision.normalized_sha256,
    )
    return context.service.advance(
        history.revision.id,
        action="approve",
        expected_sequence=history.sequence,
        key=str(uuid4()),
        actor=context.admin,
        reason="Explicit approval with a selected validity boundary.",
        reviewed_document_sha256=history.revision.normalized_sha256,
        valid_until=context.now[0] + timedelta(days=1),
    )


def test_archive_and_publication_survive_new_database_and_service_instances(archive, settings):
    histories, publication = publish_corpus(archive)
    before = archive.knowledge.snapshot()
    archive.database.dispose()
    restarted = Database(settings)
    try:
        repository = SqlKnowledgeRepository(restarted)
        after = DatabaseSupportKnowledge(repository, lambda: archive.now[0]).snapshot()
        assert after == before
        service = KnowledgeGovernanceService(repository, lambda: archive.now[0])
        assert service.get(histories[0].revision.id, actor=archive.admin).state == "published"
        assert after.manifest_sha256 == publication.manifest_sha256
    finally:
        restarted.dispose()


def test_independent_revision_replaces_only_one_source_without_weakening_v1(archive):
    histories, _ = publish_corpus(archive)
    revised = approved_revision(archive, revision="9.0.0")
    selected = tuple(
        revised.revision.id if h.revision.source_id == revised.revision.source_id else h.revision.id
        for h in histories
    )
    archive.service.publish(
        selected,
        key=str(uuid4()),
        expected_sequence=0,
        actor=archive.admin,
        reason="Explicit publication of an independently reviewed source revision.",
    )
    snapshot = archive.knowledge.snapshot()
    assert snapshot.available
    assert {source.revision for source in snapshot.sources} == {"1.0.0", "9.0.0"}
    assert revised.approval.review_origin == "manual"
    assert revised.approval.historical_reviewer_label is None


@pytest.mark.parametrize("forged", [False, True])
def test_ordinary_or_forged_admin_accounts_cannot_ingest(archive, forged):
    actor = archive.learner
    if forged:
        actor = AuthenticatedAccount(
            Account(actor.account.id, actor.account.created_at, "active", ("admin",)),
            actor.identity,
        )
    with pytest.raises(LearningError) as error:
        archive.service.ingest(
            archive.package.documents[0], revision="2.0.0", key=str(uuid4()), actor=actor
        )
    assert error.value.code == "forbidden"
    with archive.database.session() as session:
        assert session.scalar(select(func.count()).select_from(k.KnowledgeRevisionRow)) == 0


@pytest.mark.parametrize("operation", ["get", "advance", "publish"])
def test_database_rechecks_revoked_admin_role(archive, operation):
    history = archive.service.ingest(
        archive.package.documents[0], revision="2.0.0", key=str(uuid4()), actor=archive.admin
    )
    with archive.database.session() as session, session.begin():
        session.execute(
            delete(m.UserRole).where(
                m.UserRole.user_id == archive.admin.account.id, m.UserRole.role == "admin"
            )
        )
    with pytest.raises(LearningError) as error:
        if operation == "get":
            archive.service.get(history.revision.id, actor=archive.admin)
        elif operation == "advance":
            archive.service.advance(
                history.revision.id,
                action="parse",
                expected_sequence=0,
                key=str(uuid4()),
                actor=archive.admin,
                reason="Attempt after role revocation.",
            )
        else:
            archive.service.publish(
                (history.revision.id,),
                key=str(uuid4()),
                expected_sequence=-1,
                actor=archive.admin,
                reason="Attempt after role revocation.",
            )
    assert error.value.code == "forbidden"


def test_technical_validation_does_not_allow_publication_or_approval_without_review(archive):
    (history, *_) = archive.service.import_reviewed_corpus(key=str(uuid4()), actor=archive.admin)
    with pytest.raises(LearningError):
        archive.service.publish(
            (history.revision.id,),
            key=str(uuid4()),
            expected_sequence=-1,
            actor=archive.admin,
            reason="Cannot publish technical validation alone.",
        )
    with pytest.raises(LearningError):
        archive.service.advance(
            history.revision.id,
            action="approve",
            expected_sequence=5,
            key=str(uuid4()),
            actor=archive.admin,
            reason="Cannot bypass human review.",
            reviewed_document_sha256=history.revision.normalized_sha256,
            valid_until=archive.now[0] + timedelta(days=1),
        )
    assert not archive.knowledge.available


def test_transition_keys_are_idempotent_and_changed_inputs_conflict(archive):
    history = archive.service.ingest(
        archive.package.documents[0], revision="2.0.0", key=str(uuid4()), actor=archive.admin
    )
    key = str(uuid4())
    result = archive.service.advance(
        history.revision.id,
        action="parse",
        expected_sequence=0,
        key=key,
        actor=archive.admin,
        reason="Parse the exact source snapshot.",
    )
    assert (
        archive.service.advance(
            history.revision.id,
            action="parse",
            expected_sequence=0,
            key=key,
            actor=archive.admin,
            reason="Parse the exact source snapshot.",
        )
        == result
    )
    with pytest.raises(LearningError, match="different inputs"):
        archive.service.advance(
            history.revision.id,
            action="parse",
            expected_sequence=0,
            key=key,
            actor=archive.admin,
            reason="Changed operation reason.",
        )


def test_publication_is_idempotent_and_requires_expected_global_revision(archive):
    histories = archive.service.import_reviewed_corpus(
        key=str(uuid4()), actor=archive.admin, adopt_existing_review=True
    )
    ids, key = tuple(h.revision.id for h in histories), str(uuid4())
    first = archive.service.publish(
        ids,
        key=key,
        expected_sequence=-1,
        actor=archive.admin,
        reason="Explicit reviewed publication.",
    )
    assert (
        archive.service.publish(
            ids,
            key=key,
            expected_sequence=-1,
            actor=archive.admin,
            reason="Explicit reviewed publication.",
        )
        == first
    )
    with pytest.raises(LearningError):
        archive.service.publish(
            ids,
            key=str(uuid4()),
            expected_sequence=-1,
            actor=archive.admin,
            reason="Stale concurrent publication.",
        )


@pytest.mark.parametrize("terminal", ["revoke", "expire"])
def test_revoked_or_expired_sources_immediately_fence_whole_manifest_and_keep_history(
    archive, terminal
):
    histories, _ = publish_corpus(archive)
    old = archive.knowledge.snapshot()
    history = archive.service.get(histories[0].revision.id, actor=archive.admin)
    if terminal == "expire":
        archive.now[0] = archive.package.valid_until
    else:
        archive.service.advance(
            history.revision.id,
            action="revoke",
            expected_sequence=history.sequence,
            key=str(uuid4()),
            actor=archive.admin,
            reason="Explicit immediate source removal fence.",
        )
    current = archive.knowledge.snapshot()
    assert not current.available and not current.sources
    assert current.reconstruct(old.sources[0].passages[0]) is None
    assert (
        archive.service.get(history.revision.id, actor=archive.admin).revision == history.revision
    )


def test_release_receipt_is_durable_minimal_and_server_identified(archive):
    publish_corpus(archive)
    answer = versioned_answer(archive.knowledge.snapshot())
    correlation = "synthetic-private-correlation"
    first = archive.service.authorize_release(answer, actor=archive.learner, request_id=correlation)
    second = archive.service.authorize_release(
        answer, actor=archive.learner, request_id=correlation
    )
    assert first.id != second.id and first.request_id_sha256 == second.request_id_sha256
    assert first.status == "release_authorized"
    assert archive.service.get_receipt(first.id, actor=archive.admin) == first
    serialized = first.model_dump_json()
    for forbidden in (
        correlation,
        answer.response.references[0].quote,
        str(archive.learner.account.id),
    ):
        assert forbidden not in serialized
    with pytest.raises(LearningError):
        archive.service.get_receipt(first.id, actor=archive.learner)


def test_release_receipt_retry_is_idempotent_but_cannot_bypass_revocation(archive):
    publish_corpus(archive)
    snapshot = archive.knowledge.snapshot()
    answer = versioned_answer(snapshot)
    first = archive.service.authorize_release(
        answer, actor=archive.learner, request_id="same-correlation"
    )
    assert (
        archive.service.authorize_release(
            answer, actor=archive.learner, request_id="same-correlation", receipt_id=first.id
        )
        == first
    )
    with pytest.raises(LearningError):
        archive.service.authorize_release(
            answer, actor=archive.learner, request_id="changed-correlation", receipt_id=first.id
        )
    selected_source = next(
        s for s in snapshot.sources if s.record.source_id == answer.passages[0].source_id
    )
    history = archive.service.get(selected_source.record.id, actor=archive.admin)
    archive.service.advance(
        history.revision.id,
        action="revoke",
        expected_sequence=history.sequence,
        key=str(uuid4()),
        actor=archive.admin,
        reason="Revoked before a release retry.",
    )
    with pytest.raises(LearningError, match="changed before"):
        archive.service.authorize_release(
            answer, actor=archive.learner, request_id="same-correlation", receipt_id=first.id
        )


def test_lock_wait_resamples_expiry_before_authorized_release(archive):
    publish_corpus(archive)
    answer = versioned_answer(archive.knowledge.snapshot())

    class DelayedRepository:
        def read(self):
            return archive.repository.read()

        @contextmanager
        def write(self):
            with archive.repository.write() as store:
                archive.now[0] = archive.package.valid_until
                yield store

    delayed = KnowledgeGovernanceService(DelayedRepository(), lambda: archive.now[0])
    with pytest.raises(LearningError):
        delayed.authorize_release(answer, actor=archive.learner, request_id="expiry-race")
    with archive.database.session() as session:
        assert session.scalar(select(func.count()).select_from(k.KnowledgeReceiptRow)) == 0


def test_expiry_during_receipt_persistence_rolls_back_release(archive):
    publish_corpus(archive)
    answer = versioned_answer(archive.knowledge.snapshot())

    class ExpiringStore:
        def __init__(self, store):
            self.store = store

        def __getattr__(self, name):
            return getattr(self.store, name)

        def put_receipt(self, receipt):
            self.store.put_receipt(receipt)
            archive.now[0] = archive.package.valid_until

    class ExpiringRepository:
        def read(self):
            return archive.repository.read()

        @contextmanager
        def write(self):
            with archive.repository.write() as store:
                yield ExpiringStore(store)

    expiring = KnowledgeGovernanceService(ExpiringRepository(), lambda: archive.now[0])
    with pytest.raises(LearningError, match="expired before"):
        expiring.authorize_release(answer, actor=archive.learner, request_id="insert-expiry")
    with archive.database.session() as session:
        assert session.scalar(select(func.count()).select_from(k.KnowledgeReceiptRow)) == 0


def test_concurrent_revocation_and_release_are_serialized_without_provider_lock(archive):
    publish_corpus(archive)
    snapshot = archive.knowledge.snapshot()
    answer = versioned_answer(snapshot)
    selected = next(
        s for s in snapshot.sources if s.record.source_id == answer.passages[0].source_id
    )
    history = archive.service.get(selected.record.id, actor=archive.admin)
    barrier = Barrier(2)

    def release():
        barrier.wait()
        try:
            return archive.service.authorize_release(
                answer, actor=archive.learner, request_id="concurrent-release"
            )
        except LearningError as error:
            return error.code

    def revoke():
        barrier.wait()
        return archive.service.advance(
            history.revision.id,
            action="revoke",
            expected_sequence=history.sequence,
            key=str(uuid4()),
            actor=archive.admin,
            reason="Concurrent revocation serialized before release.",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        release_future, revoke_future = pool.submit(release), pool.submit(revoke)
        receipt, revoked = release_future.result(), revoke_future.result()
    assert revoked.state == "revoked" and not archive.knowledge.available
    with archive.database.session() as session:
        assert session.scalar(select(func.count()).select_from(k.KnowledgeReceiptRow)) == (
            0 if receipt == "conflict" else 1
        )


@pytest.mark.parametrize(
    "table",
    [
        k.KnowledgeSourceRow,
        k.KnowledgeRevisionRow,
        k.KnowledgeEventRow,
        k.KnowledgeManifestRow,
        k.KnowledgePublicationRow,
        k.KnowledgeReceiptRow,
    ],
)
@pytest.mark.parametrize("action", ["update", "delete"])
def test_database_prevents_archive_history_rewrite_and_deletion(archive, table, action):
    publish_corpus(archive)
    archive.service.authorize_release(
        versioned_answer(archive.knowledge.snapshot()),
        actor=archive.learner,
        request_id="immutable-receipt",
    )
    with pytest.raises(IntegrityError), archive.database.session() as session, session.begin():
        if action == "delete":
            session.execute(delete(table))
        else:
            column = next(
                column for column in table.__table__.columns if column.name == "created_at"
            )
            session.execute(update(table).values({column.name: archive.now[0]}))


def synthetic_index(snapshot, now, *, source="ai", scope="production_candidate", offset=0):
    """Counterfactual trusted-provider receipt for persistence contracts, never live evidence."""
    metadata = EmbeddingIndexMetadata(created_at=now, source=source, scope=scope)
    passages = []
    for ordinal, version in enumerate(
        version for source in snapshot.sources for version in source.passages
    ):
        match = snapshot.reconstruct(version)
        values = tuple(1.0 if n == (ordinal + offset) % 768 else 0.0 for n in range(768))
        passages.append(
            IndexedPassage(
                version=version,
                space_sha256=metadata.profile.space_sha256,
                input_sha256=text_digest(match.title + "\n\n" + match.text),
                vector=UnitEmbedding.from_raw(values),
            )
        )
    fields = {
        "metadata": metadata.model_dump(mode="json"),
        "manifest_sha256": snapshot.manifest_sha256,
        "passages": [passage.model_dump(mode="json") for passage in passages],
    }
    return EmbeddingIndex.model_validate_json(
        json.dumps({**fields, "index_sha256": canonical_digest(fields)})
    )


def test_document_vectors_and_version_provenance_are_durable_and_reindex_preserves_old_receipt(
    archive,
):
    publish_corpus(archive)
    snapshot = archive.knowledge.snapshot()
    first = synthetic_index(snapshot, archive.now[0])
    key = str(uuid4())
    assert archive.service.store_index(first, key=key, actor=archive.admin) == first
    assert archive.service.store_index(first, key=key, actor=archive.admin) == first
    bound_answer = VersionedSupportAnswer.model_validate(
        versioned_answer(snapshot).model_dump(warnings=False)
        | {"retrieval_profile": "hybrid", "index_sha256": first.index_sha256}
    )
    receipt = archive.service.authorize_release(
        bound_answer,
        actor=archive.learner,
        request_id="semantic-release",
        retrieval_profile="hybrid",
        index_sha256=first.index_sha256,
    )
    assert receipt.index_sha256 == first.index_sha256
    assert receipt.embedding_space_sha256 == first.metadata.profile.space_sha256
    assert len(receipt.selected_vector_sha256) == 1
    second = synthetic_index(snapshot, archive.now[0], offset=1)
    archive.service.store_index(second, key=str(uuid4()), actor=archive.admin)
    with archive.repository.read() as store:
        assert store.index(first.index_sha256) == first
        assert store.index(second.index_sha256) == second
        assert store.receipt(receipt.id) == receipt
    assert (
        archive.knowledge.snapshot() == snapshot
    )  # Storage did not activate a different retriever.
    assert all(p.vector.vector_sha256 for p in first.passages)
    with pytest.raises(IntegrityError), archive.database.session() as session, session.begin():
        session.execute(delete(k.KnowledgeIndexRow))


@pytest.mark.parametrize(
    "source,scope",
    [("test_fixture", "production_candidate"), ("ai", "benchmark"), ("test_fixture", "benchmark")],
)
def test_benchmark_or_fixture_indexes_cannot_be_promoted_into_durable_production_artifacts(
    archive, source, scope
):
    publish_corpus(archive)
    expected = (
        ValidationError
        if source == "test_fixture" and scope == "production_candidate"
        else LearningError
    )
    with pytest.raises(expected):
        index = synthetic_index(
            archive.knowledge.snapshot(), archive.now[0], source=source, scope=scope
        )
        archive.service.store_index(index, key=str(uuid4()), actor=archive.admin)
    with archive.database.session() as session:
        assert session.scalar(select(func.count()).select_from(k.KnowledgeIndexRow)) == 0


def test_stale_manifest_or_missing_index_cannot_authorize_semantic_release(archive):
    publish_corpus(archive)
    answer = versioned_answer(archive.knowledge.snapshot())
    with pytest.raises(LearningError):
        archive.service.authorize_release(
            answer,
            actor=archive.learner,
            request_id="missing-index",
            retrieval_profile="semantic",
            index_sha256="f" * 64,
        )
