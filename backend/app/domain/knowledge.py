"""Immutable customer-document history; approval and publication are separate facts."""

import hashlib
import json
from typing import Annotated, Any, Literal, Self, cast

from pydantic import AfterValidator, AwareDatetime, ConfigDict, Field, StrictInt, model_validator

from app.domain.lesson_spec.fields import Digest, Items, LocalId, Summary, Value, Version, VersionId
from app.schemas.support import SupportDocument, customer_reference
from app.services.support_readiness import support_document_digest
from app.support.versioning import ApprovedSupportPassageVersion, canonical_digest

type KnowledgeState = Literal[
    "ingested",
    "parsed",
    "normalized",
    "chunked",
    "indexed",
    "validated",
    "reviewed",
    "approved",
    "published",
    "rejected",
    "revoked",
    "expired",
]
type KnowledgeAction = Literal[
    "ingest",
    "parse",
    "normalize",
    "chunk",
    "index",
    "validate",
    "review",
    "approve",
    "adopt_existing_review",
    "publish",
    "reject",
    "revoke",
    "expire",
]
type Sequence = Annotated[StrictInt, Field(ge=0)]
type DocumentJSON = Annotated[str, Field(min_length=2, max_length=16384)]
type KnowledgeReason = Annotated[Summary, AfterValidator(customer_reference)]


def canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


class Fingerprinted(Value):
    model_config = ConfigDict(revalidate_instances="always")
    content_sha256: Digest

    def payload_digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json", exclude={"content_sha256"}))

    @model_validator(mode="after")
    def fingerprint_integrity(self) -> Self:
        if self.content_sha256 != self.payload_digest():
            raise ValueError("Immutable knowledge payload does not match its fingerprint")
        return self


def sealed[T: Fingerprinted](model: type[T], **fields: object) -> T:
    # A local draft only computes its fingerprint. It is fully revalidated before
    # return/persistence, matching the existing candidate-snapshot convention.
    draft = model.model_construct(content_sha256="0" * 64, **cast(dict[str, Any], fields))
    payload = draft.model_dump(mode="json", warnings=False)
    payload["content_sha256"] = draft.payload_digest()
    return model.model_validate_json(canonical_json(payload))


class ImportedReview(Value):
    model_config = ConfigDict(revalidate_instances="always")
    origin: Literal["imported_record"] = "imported_record"
    reviewer_label: LocalId
    reviewed_at: AwareDatetime
    valid_until: AwareDatetime
    package_revision: Version
    package_sha256: Digest
    document_sha256: Digest


class KnowledgeRevision(Fingerprinted):
    id: VersionId
    source_id: LocalId
    revision: Version
    creation_key: VersionId
    actor_id: VersionId
    created_at: AwareDatetime
    source_kind: Literal["trace_customer_authored"] = "trace_customer_authored"
    audience: Literal["public_customer"] = "public_customer"
    original_json: DocumentJSON = Field(repr=False)
    original_sha256: Digest
    normalized_json: DocumentJSON = Field(repr=False)
    normalized_sha256: Digest
    parser_version: Literal["support-document-json-v1"] = "support-document-json-v1"
    normalizer_version: Literal["identity-text-v1"] = "identity-text-v1"
    imported_review: ImportedReview | None = None

    def document(self) -> SupportDocument:
        return SupportDocument.model_validate_json(self.normalized_json)

    @model_validator(mode="after")
    def exact_copy(self) -> Self:
        original = SupportDocument.model_validate_json(self.original_json)
        document = self.document()
        expected = canonical_json(document.model_dump(mode="json"))
        if (
            document.source_id != self.source_id
            or document.approval != "approved_customer_safe"
            or original != document
            or self.original_json != expected
            or self.normalized_json != expected
            or self.original_sha256 != support_document_digest(original)
            or self.normalized_sha256 != support_document_digest(document)
            or (
                self.imported_review is not None
                and self.imported_review.document_sha256 != self.normalized_sha256
            )
        ):
            raise ValueError(
                "Source text and normalization must retain exact canonical approved-copy shape"
            )
        return self


class LexicalIndexArtifact(Fingerprinted):
    schema_version: Literal["knowledge-lexical-index-v1"] = "knowledge-lexical-index-v1"
    algorithm: Literal["shared-word-overlap-v1"] = "shared-word-overlap-v1"
    source_revision_id: VersionId
    document_sha256: Digest
    chunk_ids: Items[Digest] = Field(min_length=1, max_length=8)


class KnowledgeEvent(Fingerprinted):
    id: VersionId
    revision_id: VersionId
    sequence: Sequence
    operation_key: VersionId
    command_sha256: Digest
    previous_event_sha256: Digest | None
    previous_state: KnowledgeState | None
    state: KnowledgeState
    action: KnowledgeAction
    actor_id: VersionId
    created_at: AwareDatetime
    reason: KnowledgeReason
    chunks: Items[ApprovedSupportPassageVersion] = Field(default=(), max_length=8)
    index_sha256: Digest | None = None
    lexical_index: LexicalIndexArtifact | None = Field(default=None, repr=False)
    reviewed_document_sha256: Digest | None = None
    review_origin: Literal["manual", "imported_record"] | None = None
    historical_reviewer_label: LocalId | None = None
    historical_reviewed_at: AwareDatetime | None = None
    valid_until: AwareDatetime | None = None


def source_chunks(revision: KnowledgeRevision) -> tuple[ApprovedSupportPassageVersion, ...]:
    result = []
    for ordinal, passage in enumerate(revision.document().passages):
        identity = dict(
            source_id=revision.source_id,
            revision=revision.revision,
            document_sha256=revision.normalized_sha256,
            passage_id=passage.passage_id,
            passage_sha256=hashlib.sha256(passage.text.encode("utf-8")).hexdigest(),
            chunker_version="authored-passages-v1",
            chunk_ordinal=ordinal,
            overlap_characters=0,
            audience="public_customer",
        )
        result.append(
            ApprovedSupportPassageVersion.model_validate(
                {**identity, "chunk_id": canonical_digest(identity)}
            )
        )
    return tuple(result)


def lexical_index_artifact(revision: KnowledgeRevision) -> LexicalIndexArtifact:
    return sealed(
        LexicalIndexArtifact,
        source_revision_id=revision.id,
        document_sha256=revision.normalized_sha256,
        chunk_ids=tuple(chunk.chunk_id for chunk in source_chunks(revision)),
    )


def lexical_index_digest(revision: KnowledgeRevision) -> str:
    return lexical_index_artifact(revision).content_sha256


class KnowledgeHistory(Value):
    model_config = ConfigDict(revalidate_instances="always")
    revision: KnowledgeRevision = Field(repr=False)
    events: Items[KnowledgeEvent] = Field(min_length=1, max_length=512, repr=False)

    @property
    def state(self) -> KnowledgeState:
        return self.events[-1].state

    @property
    def sequence(self) -> int:
        return self.events[-1].sequence

    @property
    def chunks(self) -> tuple[ApprovedSupportPassageVersion, ...]:
        return next((event.chunks for event in self.events if event.action == "chunk"), ())

    @property
    def approval(self) -> KnowledgeEvent | None:
        return next(
            (
                event
                for event in reversed(self.events)
                if event.action in {"approve", "adopt_existing_review"}
            ),
            None,
        )

    @property
    def index_sha256(self) -> str | None:
        return next((event.index_sha256 for event in self.events if event.action == "index"), None)

    @model_validator(mode="after")
    def lifecycle(self) -> Self:
        simple = {
            "parse": ("ingested", "parsed"),
            "normalize": ("parsed", "normalized"),
            "chunk": ("normalized", "chunked"),
            "index": ("chunked", "indexed"),
            "validate": ("indexed", "validated"),
            "review": ("validated", "reviewed"),
            "approve": ("reviewed", "approved"),
            "adopt_existing_review": ("validated", "approved"),
            "publish": ("approved", "published"),
        }
        previous: KnowledgeEvent | None = None
        previous_time = self.revision.created_at
        for sequence, event in enumerate(self.events):
            if (
                event.revision_id != self.revision.id
                or event.sequence != sequence
                or event.previous_event_sha256 != (previous.content_sha256 if previous else None)
                or event.previous_state != (previous.state if previous else None)
                or event.created_at < previous_time
            ):
                raise ValueError(
                    "Knowledge lifecycle history must remain ordered and identity-bound"
                )
            if event.action == "ingest":
                valid = sequence == 0 and event.state == "ingested"
            elif event.action == "reject":
                valid = (
                    previous is not None
                    and previous.state
                    in {
                        "ingested",
                        "parsed",
                        "normalized",
                        "chunked",
                        "indexed",
                        "validated",
                        "reviewed",
                    }
                    and event.state == "rejected"
                )
            elif event.action in {"revoke", "expire"}:
                valid = (
                    previous is not None
                    and previous.state in {"approved", "published"}
                    and event.state == {"revoke": "revoked", "expire": "expired"}[event.action]
                )
            else:
                valid = (
                    event.action in simple
                    and (event.previous_state, event.state) == simple[event.action]
                )
            if not valid:
                raise ValueError("Knowledge lifecycle transition is not permitted")
            if (event.action == "chunk") != bool(event.chunks):
                raise ValueError("Only chunking records exact immutable passage versions")
            if (event.action == "index") != (event.index_sha256 is not None):
                raise ValueError("Indexing must record its deterministic build proof")
            if (event.action == "index") != (event.lexical_index is not None):
                raise ValueError("Indexing must preserve its explicit immutable artifact")
            if event.lexical_index is not None and (
                event.lexical_index != lexical_index_artifact(self.revision)
                or event.index_sha256 != event.lexical_index.content_sha256
            ):
                raise ValueError("Index artifact must match exact immutable source/chunk inputs")
            if event.action in {"review", "approve", "adopt_existing_review"}:
                if event.reviewed_document_sha256 != self.revision.normalized_sha256:
                    raise ValueError("Review must attest the exact immutable document digest")
            elif event.reviewed_document_sha256 is not None:
                raise ValueError("Only human decisions may attest a review digest")
            if event.action in {"approve", "adopt_existing_review"}:
                if (
                    event.valid_until is None
                    or event.valid_until <= event.created_at
                    or event.review_origin is None
                ):
                    raise ValueError(
                        "Approval requires an explicit current validity window and origin"
                    )
                if event.action == "adopt_existing_review":
                    legacy = self.revision.imported_review
                    if legacy is None or (
                        event.review_origin,
                        event.historical_reviewer_label,
                        event.historical_reviewed_at,
                        event.valid_until,
                    ) != (
                        "imported_record",
                        legacy.reviewer_label,
                        legacy.reviewed_at,
                        legacy.valid_until,
                    ):
                        raise ValueError(
                            "Imported review must retain the genuine historical attribution"
                        )
                elif (
                    event.review_origin != "manual"
                    or event.historical_reviewer_label is not None
                    or event.historical_reviewed_at is not None
                ):
                    raise ValueError(
                        "A new manual approval cannot claim historical review attribution"
                    )
            elif any(
                value is not None
                for value in (
                    event.valid_until,
                    event.review_origin,
                    event.historical_reviewer_label,
                    event.historical_reviewed_at,
                )
            ):
                raise ValueError("Only approvals may contain review attribution and validity")
            previous, previous_time = event, event.created_at
        if len({event.operation_key for event in self.events}) != len(self.events):
            raise ValueError("Knowledge operation identities must be unique")
        if self.index_sha256 is not None and self.index_sha256 != lexical_index_digest(
            self.revision
        ):
            raise ValueError("Index proof must bind the deterministic existing lexical index")
        if self.chunks:
            document = self.revision.document()
            if len(self.chunks) != len(document.passages):
                raise ValueError("Every authored passage requires exactly one chunk")
            if self.chunks != source_chunks(self.revision):
                raise ValueError("Chunk identity must match the immutable source revision")
        return self


class KnowledgeManifest(Fingerprinted):
    schema_version: Literal["knowledge-manifest-v2"] = "knowledge-manifest-v2"
    revision_ids: Items[VersionId] = Field(min_length=1, max_length=32)
    revision_sha256: Items[Digest] = Field(min_length=1, max_length=32)
    approval_sha256: Items[Digest] = Field(min_length=1, max_length=32)
    chunk_ids: Items[Digest] = Field(min_length=1, max_length=256)
    lexical_index_sha256: Items[Digest] = Field(min_length=1, max_length=32)
    audience: Literal["public_customer"] = "public_customer"

    @model_validator(mode="after")
    def complete_manifest(self) -> Self:
        if (
            len(set(self.revision_ids)) != len(self.revision_ids)
            or len(set(self.chunk_ids)) != len(self.chunk_ids)
            or not (
                len(self.revision_ids)
                == len(self.revision_sha256)
                == len(self.approval_sha256)
                == len(self.lexical_index_sha256)
            )
        ):
            raise ValueError("Published manifest references must be unique and complete")
        return self


class KnowledgePublication(Fingerprinted):
    id: VersionId
    sequence: Sequence
    operation_key: VersionId
    command_sha256: Digest
    previous_manifest_sha256: Digest | None
    manifest_sha256: Digest
    actor_id: VersionId
    created_at: AwareDatetime
    reason: KnowledgeReason


class KnowledgeReleaseReceipt(Fingerprinted):
    schema_version: Literal["knowledge-release-receipt-v1"] = "knowledge-release-receipt-v1"
    id: VersionId
    created_at: AwareDatetime
    request_id_sha256: Digest
    manifest_sha256: Digest
    publication_sequence: Sequence
    status: Literal["release_authorized"] = "release_authorized"
    passages: Items[ApprovedSupportPassageVersion] = Field(min_length=1, max_length=3)
    retrieval_profile: Literal["lexical", "semantic", "hybrid"] = "lexical"
    index_sha256: Digest | None = None
    embedding_space_sha256: Digest | None = None
    selected_vector_sha256: Items[Digest] = Field(default=(), max_length=3)

    @model_validator(mode="after")
    def exact_selection(self) -> Self:
        if len({version.chunk_id for version in self.passages}) != len(self.passages):
            raise ValueError("Receipt references must be unique")
        if self.retrieval_profile == "lexical":
            if (
                self.index_sha256 is not None
                or self.embedding_space_sha256 is not None
                or self.selected_vector_sha256
            ):
                raise ValueError("Lexical receipts cannot claim semantic index provenance")
        elif (
            self.index_sha256 is None
            or self.embedding_space_sha256 is None
            or len(self.selected_vector_sha256) != len(self.passages)
        ):
            raise ValueError(
                "Semantic receipts require exact index, space and selected vector identities"
            )
        return self
