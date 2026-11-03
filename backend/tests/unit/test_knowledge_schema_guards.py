"""Adversarial persisted-history input must not forge approval or provenance."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.domain.knowledge import KnowledgeHistory, KnowledgeReleaseReceipt, sealed
from tests.knowledge_guard_fixtures import (
    event,
    history,
    identifier,
    manifest,
    reseal,
    revision,
    source,
)


def check_changed_event(value, position, **changes):
    events = value.events[:position] + (reseal(value.events[position], **changes),)
    return KnowledgeHistory(revision=value.revision, events=events)


def test_modified_revision_is_rejected_even_before_a_history_is_released():
    record = revision()
    tampered = record.model_dump()
    tampered["actor_id"] = identifier("forged-actor")
    with pytest.raises(ValidationError, match="fingerprint"):
        type(record).model_validate(tampered)


@pytest.mark.parametrize("field", ["original_json", "normalized_sha256"])
def test_resealing_does_not_authorize_noncanonical_copy_or_false_document_digest(field):
    record = revision()
    value = record.original_json + " " if field == "original_json" else "f" * 64
    with pytest.raises(ValidationError, match="exact canonical approved-copy"):
        reseal(record, **{field: value})


@pytest.mark.parametrize(
    "changes",
    [
        {"revision_id": identifier("different-revision")},
        {"sequence": 4},
        {"previous_event_sha256": "f" * 64},
        {"previous_state": "approved"},
    ],
)
def test_rehashed_event_cannot_change_history_identity_or_order(changes):
    with pytest.raises(ValidationError, match="ordered and identity-bound"):
        check_changed_event(history(), 1, **changes)


def test_rehashed_event_cannot_backdate_before_the_source_revision():
    value = history()
    with pytest.raises(ValidationError, match="ordered and identity-bound"):
        check_changed_event(value, 1, created_at=value.revision.created_at - timedelta(seconds=1))


def test_rejection_is_allowed_for_unapproved_copy_but_cannot_rewrite_an_approval():
    for through, allowed in (("validate", True), ("approve", False)):
        value = history(through=through)
        rejection = event(value.revision, value.events[-1], "reject", "rejected")
        if allowed:
            assert (
                KnowledgeHistory(revision=value.revision, events=(*value.events, rejection)).state
                == "rejected"
            )
        else:
            with pytest.raises(ValidationError, match="transition is not permitted"):
                KnowledgeHistory(revision=value.revision, events=(*value.events, rejection))


@pytest.mark.parametrize(
    "position,changes,message",
    [
        (3, {"chunks": ()}, "Only chunking"),
        (4, {"index_sha256": None}, "deterministic build proof"),
        (4, {"lexical_index": None}, "explicit immutable artifact"),
        (6, {"reviewed_document_sha256": "f" * 64}, "exact immutable document digest"),
        (1, {"reviewed_document_sha256": "f" * 64}, "Only human decisions"),
        (7, {"valid_until": None}, "validity window and origin"),
        (7, {"review_origin": None}, "validity window and origin"),
        (7, {"review_origin": "imported_record"}, "cannot claim historical"),
        (7, {"historical_reviewer_label": "forged-reviewer"}, "cannot claim historical"),
        (6, {"review_origin": "manual"}, "Only approvals"),
        (7, {"operation_key": identifier("operation-0")}, "identities must be unique"),
    ],
)
def test_rehashed_lifecycle_events_cannot_forge_proof_or_human_review(position, changes, message):
    with pytest.raises(ValidationError, match=message):
        check_changed_event(history(), position, **changes)


def test_expired_approval_and_substituted_lexical_build_are_rejected():
    value = history()
    with pytest.raises(ValidationError, match="validity window and origin"):
        check_changed_event(value, 7, valid_until=value.events[7].created_at)
    artifact = reseal(
        value.events[4].lexical_index, source_revision_id=identifier("different-revision")
    )
    with pytest.raises(ValidationError, match="exact immutable source/chunk"):
        check_changed_event(value, 4, lexical_index=artifact, index_sha256=artifact.content_sha256)


@pytest.mark.parametrize("imported", [False, True])
def test_historical_review_cannot_be_invented_or_reattributed(imported):
    value = history(imported=imported, through="validate")
    adoption = event(value.revision, value.events[-1], "adopt_existing_review", "approved")
    if imported:
        adoption = reseal(adoption, historical_reviewer_label="different-historical-reviewer")
    with pytest.raises(ValidationError, match="genuine historical attribution"):
        KnowledgeHistory(revision=value.revision, events=(*value.events, adoption))


@pytest.mark.parametrize("change", ["missing_passage", "reordered_passages"])
def test_rehashed_chunking_cannot_drop_or_reorder_approved_passages(change):
    value = history(through="chunk")
    chunks = value.chunks[:-1] if change == "missing_passage" else tuple(reversed(value.chunks))
    with pytest.raises(ValidationError, match="exactly one chunk|immutable source revision"):
        check_changed_event(value, 3, chunks=chunks)


@pytest.mark.parametrize("change", ["duplicate_revision", "duplicate_chunk", "missing_approval"])
def test_published_manifest_rejects_duplicate_or_incomplete_references(change):
    sources = (source(history(ordinal=0)), source(history(ordinal=1)))
    value = manifest(sources)
    updates = {
        "duplicate_revision": {"revision_ids": (value.revision_ids[0],) * 2},
        "duplicate_chunk": {"chunk_ids": (value.chunk_ids[0],) * 2},
        "missing_approval": {"approval_sha256": value.approval_sha256[:1]},
    }[change]
    with pytest.raises(ValidationError, match="unique and complete"):
        reseal(value, **updates)


def receipt(**changes):
    value = source()
    return sealed(
        KnowledgeReleaseReceipt,
        **{
            "id": identifier("release"),
            "created_at": value.approval.created_at,
            "request_id_sha256": "a" * 64,
            "manifest_sha256": manifest((value,)).content_sha256,
            "publication_sequence": 0,
            "passages": value.passages[:1],
            **changes,
        },
    )


def test_release_receipt_rejects_duplicate_evidence_and_lexical_semantic_misattribution():
    version = source().passages[0]
    with pytest.raises(ValidationError, match="references must be unique"):
        receipt(passages=(version, version))
    for changes in (
        {"index_sha256": "b" * 64},
        {"embedding_space_sha256": "b" * 64},
        {"selected_vector_sha256": ("b" * 64,)},
    ):
        with pytest.raises(ValidationError, match="Lexical receipts cannot claim"):
            receipt(**changes)


@pytest.mark.parametrize(
    "missing", ["index_sha256", "embedding_space_sha256", "selected_vector_sha256"]
)
def test_semantic_receipt_rejects_missing_index_space_or_selected_vector_identity(missing):
    fields = {
        "retrieval_profile": "hybrid",
        "index_sha256": "b" * 64,
        "embedding_space_sha256": "c" * 64,
        "selected_vector_sha256": ("d" * 64,),
    }
    fields[missing] = () if missing == "selected_vector_sha256" else None
    with pytest.raises(ValidationError, match="exact index, space and selected vector"):
        receipt(**fields)
