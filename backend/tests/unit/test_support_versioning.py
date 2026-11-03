"""Immutable internal provenance; no real corpus files or providers are changed."""

import hashlib
from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.schemas.support import SupportQuestion
from app.services.support_readiness import support_document_digest
from app.support.knowledge import (
    ReviewedSupportKnowledge,
    load_corpus_package,
    support_corpus_digest,
)
from app.support.versioning import (
    ApprovedSupportPassageVersion,
    SupportKnowledgeSnapshot,
    SupportSnapshotIssue,
    canonical_digest,
)


def sources(package=None, *, clock=None):
    package = package or load_corpus_package()
    return ReviewedSupportKnowledge(
        loader=lambda: package,
        clock=clock or (lambda: package.reviewed_at + timedelta(seconds=1)),
    )


def test_approved_manifest_preserves_every_existing_document_and_passage_digest():
    package = load_corpus_package()
    snapshot = sources(package).snapshot()
    assert snapshot.available and not snapshot.issues
    assert snapshot.package_revision == package.revision
    assert len(snapshot.sources) == 9
    assert sum(len(source.passages) for source in snapshot.sources) == 19
    assert snapshot.manifest_sha256 == snapshot.content_digest()
    for source in snapshot.sources:
        assert source.document_sha256 == package.document_digests[source.document.source_id]
        assert source.document_sha256 == support_document_digest(source.document)
        assert source.reviewed_by == package.reviewed_by
        assert source.reviewed_at == package.reviewed_at
        assert source.valid_until == package.valid_until
        for passage, version in zip(source.document.passages, source.passages, strict=True):
            assert version.passage_sha256 == hashlib.sha256(passage.text.encode()).hexdigest()
            assert version.chunker_version == "authored-passages-v1"
            assert version.overlap_characters == 0
            assert version.audience == "public_customer"


def test_evaluation_time_does_not_change_immutable_manifest_identity():
    package = load_corpus_package()
    first = sources(package).snapshot()
    later = sources(package, clock=lambda: package.reviewed_at + timedelta(minutes=1)).snapshot()
    assert first.evaluated_at != later.evaluated_at
    assert first.manifest_sha256 == later.manifest_sha256
    assert first.sources == later.sources


def test_authored_package_digest_preserves_original_baseline_and_excludes_removal_fence():
    package = load_corpus_package()
    assert support_corpus_digest(package) == (
        "1fa44fda7549fcac866926c07c56c9778deaa8e29955309b1f8bab80c24f5063"
    )
    explicit_default = package.model_copy(update={"revoked_source_ids": ()})
    revoked = package.model_copy(update={"revoked_source_ids": (package.documents[0].source_id,)})
    assert support_corpus_digest(explicit_default) == support_corpus_digest(package)
    assert support_corpus_digest(revoked) == support_corpus_digest(package)
    assert not sources(revoked).snapshot().available


def test_snapshot_is_frozen_and_detached_from_mutable_package_digest_map():
    package = load_corpus_package()
    snapshot = sources(package).snapshot()
    before = snapshot.model_dump(mode="json")
    with pytest.raises(ValidationError):
        snapshot.status = "unavailable"
    with pytest.raises(ValidationError):
        snapshot.sources[0].document.title = "Changed title"
    package.document_digests[package.documents[0].source_id] = "f" * 64
    assert snapshot.model_dump(mode="json") == before
    assert not sources(package).snapshot().available


def test_retrieval_and_exact_citation_reconstruction_are_compatible():
    knowledge = sources()
    snapshot = knowledge.snapshot()
    question = SupportQuestion(question="password recovery expired link")
    assert snapshot.retrieve(question) == knowledge.retrieve(question)
    for match in snapshot.retrieve(question):
        version = snapshot.resolve(match)
        assert version is not None
        assert snapshot.reconstruct(version) == match


@pytest.mark.parametrize(
    "changes",
    [
        {"title": "Substituted title"},
        {"text": "Substituted approved-looking copy"},
        {"source_id": "different-source"},
        {"passage_id": "different-passage"},
        {"approval": "test_fixture"},
    ],
)
def test_index_or_provider_cannot_substitute_authoritative_citation_fields(changes):
    snapshot = sources().snapshot()
    match = snapshot.retrieve(SupportQuestion(question="password recovery"))[0]
    assert snapshot.resolve(match.model_copy(update=changes)) is None


def test_forged_chunk_digest_rejected_and_valid_unknown_identity_abstains():
    snapshot = sources().snapshot()
    version = snapshot.sources[0].passages[0]
    with pytest.raises(ValidationError):
        snapshot.reconstruct(version.model_copy(update={"chunk_id": "f" * 64}))
    changed = version.model_dump(exclude={"chunk_id"})
    changed["source_id"] = "unknown-source"
    forged = ApprovedSupportPassageVersion.model_validate(
        {**changed, "chunk_id": canonical_digest(changed)}
    )
    assert snapshot.reconstruct(forged) is None


@pytest.mark.parametrize("overlap", [False, True, 1, -1, "0"])
def test_chunk_policy_cannot_accept_overlap_or_coercible_metadata(overlap):
    version = sources().snapshot().sources[0].passages[0]
    identity = version.model_dump(exclude={"chunk_id"})
    identity["overlap_characters"] = overlap
    with pytest.raises(ValidationError):
        ApprovedSupportPassageVersion.model_validate(
            {**identity, "chunk_id": canonical_digest(identity)}
        )


def test_revocation_fences_entire_package_without_mutating_previous_snapshot():
    package = load_corpus_package()
    previous = sources(package).snapshot()
    source_id = package.documents[0].source_id
    revoked = package.model_copy(update={"revoked_source_ids": (source_id,)})
    current = sources(revoked).snapshot()
    assert not current.available and not current.sources
    assert current.manifest_sha256 is None
    assert [(issue.source_id, issue.code) for issue in current.issues] == [
        (source_id, "source_revoked")
    ]
    assert current.reconstruct(previous.sources[0].passages[0]) is None
    assert previous.available
    assert package.revoked_source_ids == ()


@pytest.mark.parametrize("revocations", [("unknown-source",), ("trace-overview",) * 2])
def test_invalid_revocation_identifiers_fail_closed(revocations):
    package = load_corpus_package().model_copy(update={"revoked_source_ids": revocations})
    snapshot = sources(package).snapshot()
    assert not snapshot.available
    assert snapshot.issues[0].code == "invalid_package"


def test_expiry_during_provider_work_prevents_reconstruction_from_fresh_manifest():
    package = load_corpus_package()
    now = [package.valid_until - timedelta(microseconds=1)]
    knowledge = sources(package, clock=lambda: now[0])
    previous = knowledge.snapshot()
    version = previous.sources[0].passages[0]
    now[0] = package.valid_until
    current = knowledge.snapshot()
    assert not current.available and not current.sources
    assert len(current.issues) == 9
    assert all(issue.code == "stale" for issue in current.issues)
    assert current.reconstruct(version) is None
    assert current.retrieve(SupportQuestion(question="password recovery")) == ()


def test_readiness_retains_all_safe_source_issues_and_fails_closed_as_a_package():
    package = load_corpus_package()
    changed = package.model_copy(
        update={
            "documents": (
                package.documents[0].model_copy(update={"title": "Changed without review"}),
            )
            + package.documents[1:]
        }
    )
    snapshot = sources(changed, clock=lambda: package.valid_until).snapshot()
    assert not snapshot.available and not snapshot.sources
    assert len(snapshot.issues) == 9
    assert {issue.code for issue in snapshot.issues} == {"content_mismatch", "stale"}


def test_new_approved_content_or_revision_cannot_reuse_old_version_identity():
    package = load_corpus_package()
    previous = sources(package).snapshot()
    source = previous.sources[0]
    index = next(
        i
        for i, document in enumerate(package.documents)
        if document.source_id == source.document.source_id
    )
    changed_document = package.documents[index].model_copy(update={"title": "Reviewed new title"})
    documents = package.documents[:index] + (changed_document,) + package.documents[index + 1 :]
    revised = package.model_copy(
        update={
            "revision": "1.0.1",
            "documents": documents,
            "document_digests": {
                **package.document_digests,
                source.document.source_id: support_document_digest(changed_document.document()),
            },
        }
    )
    current = sources(revised).snapshot()
    assert current.available
    assert current.manifest_sha256 != previous.manifest_sha256
    assert current.reconstruct(source.passages[0]) is None
    assert source.document_sha256 == package.document_digests[source.document.source_id]


@pytest.mark.parametrize("audience", ["private", "staff", "", "PUBLIC_CUSTOMER"])
def test_unapproved_audiences_are_never_treated_as_public(audience):
    snapshot = sources().snapshot(audience=audience)
    assert not snapshot.available and not snapshot.sources
    assert snapshot.issues[0].code == "unsupported_audience"


@pytest.mark.parametrize("exception", [OSError("private-file-path"), RuntimeError("secret-value")])
def test_loader_failures_expose_safe_codes_without_paths_or_diagnostics(exception):
    def unavailable():
        raise exception

    snapshot = ReviewedSupportKnowledge(loader=unavailable).snapshot()
    assert not snapshot.available
    assert snapshot.issues[0].code == "package_unavailable"
    serialized = snapshot.model_dump_json()
    assert "private-file-path" not in serialized and "secret-value" not in serialized


def test_unknown_or_incomplete_snapshot_metadata_is_rejected():
    snapshot = sources().snapshot()
    raw = snapshot.model_dump()
    raw["manifest_sha256"] = "f" * 64
    with pytest.raises(ValidationError):
        SupportKnowledgeSnapshot.model_validate(raw)
    raw = snapshot.model_dump()
    raw["sources"][0]["document_sha256"] = "f" * 64
    with pytest.raises(ValidationError):
        SupportKnowledgeSnapshot.model_validate(raw)


def test_model_copy_cannot_bypass_nested_audience_validation_with_rehashed_metadata():
    snapshot = sources().snapshot()
    source = snapshot.sources[0]
    version = source.passages[0]
    identity = version.model_dump(exclude={"chunk_id"})
    identity["audience"] = "private"
    forged_version = version.model_copy(update={**identity, "chunk_id": canonical_digest(identity)})
    forged_source = source.model_copy(update={"passages": (forged_version,) + source.passages[1:]})
    forged_snapshot = snapshot.model_copy(
        update={"sources": (forged_source,) + snapshot.sources[1:]}
    )
    forged_snapshot = forged_snapshot.model_copy(
        update={"manifest_sha256": forged_snapshot.content_digest()}
    )
    with pytest.raises(ValidationError):
        SupportKnowledgeSnapshot.model_validate(forged_snapshot)


def test_existing_instances_revalidate_safe_issue_codes_and_base_value_guards():
    issue = SupportSnapshotIssue(code="package_unavailable")
    with pytest.raises(ValidationError):
        SupportSnapshotIssue.model_validate(issue.model_copy(update={"code": "private-diagnostic"}))
    snapshot = sources().snapshot()
    for model in (snapshot, snapshot.sources[0], snapshot.sources[0].passages[0], issue):
        assert model.model_config["frozen"]
        assert model.model_config["extra"] == "forbid"
        assert model.model_config["strict"]
        assert model.model_config["hide_input_in_errors"]


@pytest.mark.parametrize(
    "change",
    [
        {"sources": ()},
        {"package_revision": None},
        {"sources": tuple(reversed(sources().snapshot().sources))},
    ],
)
def test_prepared_snapshot_cannot_skip_source_or_manifest_integrity(change):
    snapshot = sources().snapshot()
    with pytest.raises(ValidationError):
        SupportKnowledgeSnapshot.model_validate(snapshot.model_copy(update=change).model_dump())


def test_unavailable_snapshot_cannot_retain_eligible_content():
    snapshot = sources().snapshot()
    raw = snapshot.model_dump()
    raw["status"] = "unavailable"
    with pytest.raises(ValidationError):
        SupportKnowledgeSnapshot.model_validate(raw)


def test_draft_package_and_invalid_clock_have_only_safe_internal_readiness_codes():
    package = load_corpus_package().model_copy(update={"review_status": "draft"})
    draft = sources(package).snapshot()
    assert not draft.available and draft.issues[0].code == "draft"

    def invalid_clock():
        raise RuntimeError("private-diagnostic")

    snapshot = sources(clock=invalid_clock).snapshot()
    assert not snapshot.available and snapshot.issues[0].code == "package_unavailable"
    assert "private-diagnostic" not in snapshot.model_dump_json()
