"""Authoritative source hydration fails closed for stale, forged or missing data."""

from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.domain.learning import LearningError
from app.schemas.support import SupportQuestion
from app.support.archive import ArchivedSupportSnapshot, ArchivedSupportSourceVersion
from app.support.database import DatabaseSupportKnowledge, archive_snapshot
from app.support.versioning import (
    ApprovedSupportPassageVersion,
    SupportSnapshotIssue,
    canonical_digest,
)
from tests.knowledge_guard_fixtures import history, identifier, manifest, reseal, snapshot, source


@pytest.mark.parametrize(
    "change",
    [
        "wrong_revision",
        "nonapproval_event",
        "false_review_digest",
        "reordered_chunks",
        "wrong_index",
    ],
)
def test_archived_source_rejects_rehashed_but_unapproved_or_mismatched_members(change):
    original = source()
    fields = original.model_dump()
    if change == "wrong_revision":
        fields["approval"] = reseal(original.approval, revision_id=identifier("different-revision"))
    elif change == "nonapproval_event":
        fields["approval"] = reseal(original.approval, action="review")
    elif change == "false_review_digest":
        fields["approval"] = reseal(original.approval, reviewed_document_sha256="f" * 64)
    elif change == "reordered_chunks":
        fields["passages"] = tuple(reversed(original.passages))
    else:
        fields["lexical_index_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="exact approved revision"):
        ArchivedSupportSourceVersion.model_validate(fields)


@pytest.mark.parametrize("exposed", ["sources", "manifest", "missing_issue"])
def test_unavailable_snapshot_cannot_retain_approved_content_or_hide_the_failure(exposed):
    valid = snapshot()
    fields = {
        "status": "unavailable",
        "evaluated_at": valid.evaluated_at,
        "issues": (SupportSnapshotIssue(code="stale"),),
    }
    if exposed == "missing_issue":
        fields["issues"] = ()
    else:
        fields[exposed] = getattr(valid, exposed)
    with pytest.raises(ValidationError, match="cannot expose eligible sources"):
        ArchivedSupportSnapshot.model_validate(fields)


@pytest.mark.parametrize(
    "changes",
    [
        {"sources": ()},
        {"manifest": None},
        {"issues": (SupportSnapshotIssue(code="stale"),)},
        {"publication_sequence": -1},
    ],
)
def test_prepared_snapshot_requires_complete_issue_free_explicit_publication(changes):
    fields = {**snapshot().model_dump(), **changes}
    with pytest.raises(ValidationError, match="explicitly published manifest"):
        ArchivedSupportSnapshot.model_validate(fields)


def test_prepared_snapshot_rejects_duplicate_and_noncanonical_source_order():
    first, second = source(history(ordinal=0)), source(history(ordinal=1))
    for sources in (
        (first, first),
        tuple(sorted((first, second), key=lambda s: s.record.source_id, reverse=True)),
    ):
        fields = snapshot().model_dump()
        fields["sources"] = sources
        with pytest.raises(ValidationError, match="unique and ordered"):
            ArchivedSupportSnapshot.model_validate(fields)


@pytest.mark.parametrize(
    "field",
    ["revision_ids", "revision_sha256", "approval_sha256", "chunk_ids", "lexical_index_sha256"],
)
def test_prepared_snapshot_rejects_a_resealed_manifest_substituting_any_member(field):
    valid = snapshot()
    replacement = (identifier("different-revision"),) if field == "revision_ids" else ("f" * 64,)
    altered = reseal(valid.manifest, **{field: replacement})
    with pytest.raises(ValidationError, match="exact current approved manifest"):
        ArchivedSupportSnapshot.model_validate({**valid.model_dump(), "manifest": altered})


@pytest.mark.parametrize("condition", ["expired", "future_approval", "missing_expiry"])
def test_snapshot_cannot_serve_expired_future_or_open_ended_approval(condition):
    valid = snapshot()
    fields = valid.model_dump()
    if condition == "expired":
        fields["evaluated_at"] = valid.sources[0].valid_until
    elif condition == "future_approval":
        fields["evaluated_at"] = valid.sources[0].approval.created_at - timedelta(seconds=1)
    else:
        original = valid.sources[0]
        altered = ArchivedSupportSourceVersion.model_validate(
            {**original.model_dump(), "approval": reseal(original.approval, valid_until=None)}
        )
        fields["sources"] = (altered,)
        fields["manifest"] = manifest((altered,))
    with pytest.raises(ValidationError, match="exact current approved manifest"):
        ArchivedSupportSnapshot.model_validate(fields)


@pytest.mark.parametrize(
    "changes",
    [
        {"title": "Unapproved title"},
        {"text": "Unapproved quote"},
        {"source_id": "different-source"},
    ],
)
def test_citation_hydration_never_accepts_substituted_text_title_or_source(changes):
    valid = snapshot()
    match = valid.reconstruct(valid.sources[0].passages[0])
    assert valid.resolve(match) == valid.sources[0].passages[0]
    assert valid.resolve(match.model_copy(update=changes)) is None


def test_unknown_well_formed_chunk_identity_abstains_instead_of_reusing_current_text():
    valid = snapshot()
    fields = valid.sources[0].passages[0].model_dump(exclude={"chunk_id"})
    fields["revision"] = "9.9.9"
    unknown = ApprovedSupportPassageVersion.model_validate(
        {**fields, "chunk_id": canonical_digest(fields)}
    )
    assert valid.reconstruct(unknown) is None


class Store:
    def __init__(self, value=None):
        self.history_value = value or history()
        self.manifest_value = manifest((source(),))
        self.publication = SimpleNamespace(
            manifest_sha256=self.manifest_value.content_sha256, sequence=0
        )

    def current_publication(self):
        return self.publication

    def manifest(self, digest):
        return self.manifest_value

    def history(self, revision_id):
        return self.history_value


@pytest.mark.parametrize("missing", ["manifest", "history"])
def test_missing_published_members_fail_instead_of_falling_back_to_historical_copy(missing):
    store = Store()
    setattr(store, missing + "_value", None)
    with pytest.raises(LearningError) as error:
        archive_snapshot(store, snapshot().evaluated_at)
    assert error.value.code == "conflict"


@pytest.mark.parametrize(
    "condition,code",
    [("unapproved", "unapproved"), ("future", "future_review"), ("expired", "stale")],
)
def test_current_eligibility_fence_withholds_all_source_content(condition, code):
    store = Store(history(through="validate") if condition == "unapproved" else history())
    now = snapshot().evaluated_at
    if condition == "future":
        now = store.history_value.approval.created_at - timedelta(seconds=1)
    elif condition == "expired":
        now = store.history_value.approval.valid_until
    result = archive_snapshot(store, now)
    assert not result.available and not result.sources and result.manifest is None
    assert {issue.code for issue in result.issues} == {code}


class Repository:
    def __init__(self, store=None, *, fail=False):
        self.store, self.fail, self.reads = store or Store(), fail, 0

    @contextmanager
    def read(self):
        self.reads += 1
        if self.fail:
            raise RuntimeError("synthetic-private-repository-error")
        yield self.store


def test_private_audience_never_reads_the_repository():
    repository = Repository(fail=True)
    knowledge = DatabaseSupportKnowledge(repository, lambda: snapshot().evaluated_at)
    result = knowledge.snapshot(audience="private_admin")
    assert {issue.code for issue in result.issues} == {"unsupported_audience"}
    assert not result.available and repository.reads == 0


def test_repository_failure_is_sanitized_and_does_not_fall_back_to_packaged_sources():
    knowledge = DatabaseSupportKnowledge(Repository(fail=True))
    result = knowledge.snapshot()
    assert not result.available and not result.sources and result.manifest is None
    assert {issue.code for issue in result.issues} == {"package_unavailable"}
    assert "synthetic-private-repository-error" not in result.model_dump_json()
    assert not knowledge.available
    assert knowledge.retrieve(SupportQuestion(question="Trace learning cycle")) == ()


def test_database_adapter_retrieval_uses_only_the_current_exact_snapshot():
    repository = Repository()
    valid = snapshot()
    knowledge = DatabaseSupportKnowledge(repository, lambda: valid.evaluated_at)
    question = SupportQuestion(question="Trace Python FastAPI learning cycle")
    assert knowledge.available
    assert knowledge.retrieve(question) == valid.retrieve(question)
    repository.store.publication = None
    assert not knowledge.available and knowledge.retrieve(question) == ()
