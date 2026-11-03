"""Synthetic immutable histories over approved public copy; never production writes."""

from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

from app.domain.knowledge import (
    ImportedReview,
    KnowledgeEvent,
    KnowledgeHistory,
    KnowledgeManifest,
    KnowledgeRevision,
    canonical_json,
    lexical_index_artifact,
    lexical_index_digest,
    sealed,
    source_chunks,
)
from app.services.support_readiness import support_document_digest
from app.support.archive import ArchivedSupportSnapshot, ArchivedSupportSourceVersion
from app.support.knowledge import load_corpus_package, support_corpus_digest


def identifier(label):
    return str(uuid5(NAMESPACE_URL, "trace-synthetic-knowledge-fixture/" + label))


def revision(*, imported=False, ordinal=0):
    package = load_corpus_package()
    documents = [item.document() for item in package.documents if len(item.passages) >= 2]
    document = documents[ordinal]
    text = canonical_json(document.model_dump(mode="json"))
    digest = support_document_digest(document)
    return sealed(
        KnowledgeRevision,
        id=identifier(f"revision-{ordinal}"),
        source_id=document.source_id,
        revision="2.0.0",
        creation_key=identifier(f"create-{ordinal}"),
        actor_id=identifier("admin"),
        created_at=package.reviewed_at,
        original_json=text,
        original_sha256=digest,
        normalized_json=text,
        normalized_sha256=digest,
        imported_review=ImportedReview(
            reviewer_label="synthetic-historical-reviewer",
            reviewed_at=package.reviewed_at,
            valid_until=package.valid_until,
            package_revision=package.revision,
            package_sha256=support_corpus_digest(package),
            document_sha256=digest,
        )
        if imported
        else None,
    )


def reseal(value, **changes):
    fields = {
        name: getattr(value, name) for name in type(value).model_fields if name != "content_sha256"
    }
    return sealed(type(value), **{**fields, **changes})


def event(record, previous, action, state, **changes):
    sequence = previous.sequence + 1 if previous else 0
    fields = {
        "id": identifier(f"event-{sequence}"),
        "revision_id": record.id,
        "sequence": sequence,
        "operation_key": identifier(f"operation-{sequence}"),
        "command_sha256": "a" * 64,
        "previous_event_sha256": previous.content_sha256 if previous else None,
        "previous_state": previous.state if previous else None,
        "state": state,
        "action": action,
        "actor_id": identifier("admin"),
        "created_at": record.created_at + timedelta(seconds=sequence),
        "reason": "Synthetic immutable history security fixture.",
    }
    if action == "chunk":
        fields["chunks"] = source_chunks(record)
    if action == "index":
        fields["index_sha256"] = lexical_index_digest(record)
        fields["lexical_index"] = lexical_index_artifact(record)
    if action in {"review", "approve", "adopt_existing_review"}:
        fields["reviewed_document_sha256"] = record.normalized_sha256
    if action == "approve":
        fields.update(review_origin="manual", valid_until=record.created_at + timedelta(days=1))
    if action == "adopt_existing_review":
        legacy = record.imported_review
        fields.update(
            review_origin="imported_record",
            valid_until=legacy.valid_until if legacy else record.created_at + timedelta(days=1),
            historical_reviewer_label=legacy.reviewer_label if legacy else "synthetic-reviewer",
            historical_reviewed_at=legacy.reviewed_at if legacy else record.created_at,
        )
    return sealed(KnowledgeEvent, **{**fields, **changes})


def history(*, imported=False, ordinal=0, through="approve"):
    record = revision(imported=imported, ordinal=ordinal)
    transitions = [
        ("ingest", "ingested"),
        ("parse", "parsed"),
        ("normalize", "normalized"),
        ("chunk", "chunked"),
        ("index", "indexed"),
        ("validate", "validated"),
    ]
    if imported:
        transitions.append(("adopt_existing_review", "approved"))
    else:
        transitions.extend((("review", "reviewed"), ("approve", "approved")))
    events = []
    for action, state in transitions:
        events.append(event(record, events[-1] if events else None, action, state))
        if action == through:
            break
    return KnowledgeHistory(revision=record, events=tuple(events))


def source(value=None):
    value = value or history()
    return ArchivedSupportSourceVersion(
        record=value.revision,
        approval=value.approval,
        passages=value.chunks,
        lexical_index_sha256=value.index_sha256,
    )


def manifest(sources):
    return sealed(
        KnowledgeManifest,
        revision_ids=tuple(item.record.id for item in sources),
        revision_sha256=tuple(item.record.content_sha256 for item in sources),
        approval_sha256=tuple(item.approval.content_sha256 for item in sources),
        chunk_ids=tuple(p.chunk_id for item in sources for p in item.passages),
        lexical_index_sha256=tuple(item.lexical_index_sha256 for item in sources),
    )


def snapshot():
    sources = (source(),)
    return ArchivedSupportSnapshot(
        status="prepared",
        evaluated_at=sources[0].approval.created_at + timedelta(seconds=1),
        publication_sequence=0,
        manifest=manifest(sources),
        sources=sources,
    )
