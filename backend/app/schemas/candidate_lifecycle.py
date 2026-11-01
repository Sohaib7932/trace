"""Internal immutable provenance; technical, human and production review are distinct."""

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StrictInt, model_validator

from app.domain.lesson_spec import validate_lesson_spec
from app.domain.lesson_spec.canonical import canonical_bytes
from app.domain.lesson_spec.fields import (
    Digest,
    Items,
    No,
    Prose,
    Value,
    VersionId,
    VersionReference,
)
from app.schemas.candidate_validation import CandidateValidationResult
from app.schemas.generation import GenerationRequest, TransportMetadata
from app.schemas.generation_admission import AdmissionAccepted
from app.schemas.lesson_composition import (
    ComposedLessonCandidate,
    CompositionIdentity,
    CompositionMetadata,
    TrustedLessonBlueprint,
)

type CandidateState = Literal[
    "composed",
    "validated",
    "validation_unavailable",
    "human_reviewed",
    "production_approved",
    "rejected",
]
type CandidateAction = Literal[
    "created", "validation", "human_review", "production_approval", "reject"
]
type SnapshotJSON = Annotated[str, Field(min_length=2, max_length=65536)]


def json_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


class CandidateSnapshot(Value):
    id: VersionId
    generation_request_id: VersionId
    creation_key: VersionId
    created_at: AwareDatetime
    generation_origin: Literal["mock", "provider"] = "mock"
    identity: CompositionIdentity
    source_blueprint: VersionReference
    request_json: SnapshotJSON = Field(repr=False)
    admitted_json: SnapshotJSON = Field(repr=False)
    blueprint_json: SnapshotJSON = Field(repr=False)
    transfer_target_json: SnapshotJSON | None = Field(repr=False)
    definition_json: SnapshotJSON = Field(repr=False)
    metadata: CompositionMetadata = Field(repr=False)
    transport: TransportMetadata
    raw_output_sha256: Digest
    request_sha256: Digest
    admitted_sha256: Digest
    composition_sha256: Digest
    release_eligible: No = False

    def context(
        self,
    ) -> tuple[
        ComposedLessonCandidate,
        GenerationRequest,
        AdmissionAccepted,
        TrustedLessonBlueprint,
        CompositionIdentity,
        TrustedLessonBlueprint | None,
    ]:
        request = GenerationRequest.model_validate_json(self.request_json)
        admitted = AdmissionAccepted.model_validate_json(self.admitted_json)
        source = TrustedLessonBlueprint(
            template_family=request.template_family,
            definition=validate_lesson_spec(self.blueprint_json),
        )
        target = (
            TrustedLessonBlueprint(
                template_family="tasks-nested-v1",
                definition=validate_lesson_spec(self.transfer_target_json),
            )
            if self.transfer_target_json is not None
            else None
        )
        definition = validate_lesson_spec(self.definition_json)
        candidate = ComposedLessonCandidate(
            definition=definition,
            canonical_digest=definition.content_sha256,
            canonical_definition_bytes=canonical_bytes(definition),
            metadata=self.metadata,
        )
        return candidate, request, admitted, source, self.identity, target

    def composition_fingerprint(self) -> str:
        return json_digest(
            {
                "identity": self.identity.model_dump(mode="json"),
                "request": self.request_sha256,
                "admission": self.admitted_sha256,
                "blueprint": self.source_blueprint.model_dump(mode="json"),
                "transfer": self.transfer_target_json,
                "definition": self.definition_json,
                "metadata": self.metadata.model_dump(mode="json"),
                "transport": self.transport.model_dump(mode="json"),
                "raw_output_sha256": self.raw_output_sha256,
                "generation_origin": self.generation_origin,
            }
        )

    @model_validator(mode="after")
    def integrity(self) -> Self:
        candidate, request, admitted, source, identity, target = self.context()
        if (
            self.definition_json.encode("utf-8") != candidate.canonical_definition_bytes
            or (self.blueprint_json.encode("utf-8") != canonical_bytes(source.definition))
            or (
                target is not None
                and (
                    self.transfer_target_json is None
                    or self.transfer_target_json.encode("utf-8")
                    != canonical_bytes(target.definition)
                )
            )
        ):
            raise ValueError("Candidate definitions must retain their exact canonical snapshots")
        if (
            self.request_json != request.model_dump_json()
            or self.admitted_json != admitted.model_dump_json()
        ):
            raise ValueError("Candidate composition inputs must retain their validated snapshots")
        if (
            self.source_blueprint != source.reference()
            or candidate.metadata.blueprint != source.reference()
        ):
            raise ValueError("Candidate provenance does not match its source blueprint")
        if self.request_sha256 != json_digest(request.model_dump(mode="json")) or (
            self.admitted_sha256 != json_digest(admitted.model_dump(mode="json"))
        ):
            raise ValueError("Candidate composition inputs do not match their digests")
        definition = candidate.definition
        if self.id != identity.version_id:
            raise ValueError("Candidate storage identity must match the reserved version identity")
        if (definition.lesson_id, definition.version_id, definition.version) != (
            identity.lesson_id,
            identity.version_id,
            identity.version,
        ):
            raise ValueError("Candidate identity does not match its immutable definition")
        if self.composition_sha256 != self.composition_fingerprint():
            raise ValueError("Candidate provenance fingerprint does not match")
        return self


class CandidateEvent(Value):
    id: VersionId
    candidate_id: VersionId
    revision: Annotated[StrictInt, Field(ge=0)]
    operation_key: VersionId
    command_sha256: Digest
    action: CandidateAction
    previous_state: CandidateState | None
    state: CandidateState
    created_at: AwareDatetime
    actor_id: VersionId | None = None
    reason: Prose
    reviewed_blueprint_sha256: Digest | None = None
    validation: CandidateValidationResult | None = Field(default=None, repr=False)
    release_eligible: No = False

    @model_validator(mode="after")
    def receipt_consistency(self) -> Self:
        if (self.action == "validation") != (self.validation is not None):
            raise ValueError("Only validation events contain a gate receipt")
        if self.validation is not None:
            expected = {"validated": "validated", "unavailable": "validation_unavailable"}.get(
                self.validation.status, "rejected"
            )
            if self.state != expected:
                raise ValueError("Validation state must match the actual gate result")
        if (
            self.action in {"human_review", "production_approval", "reject"}
            and self.actor_id is None
        ):
            raise ValueError("Human decisions require an identified administrator")
        if self.action in {"created", "validation"} and self.actor_id is not None:
            raise ValueError("System lifecycle events cannot claim a human decision")
        if (self.action == "production_approval") != (self.reviewed_blueprint_sha256 is not None):
            raise ValueError("Only production approval records source review attestation")
        return self


class CandidateHistory(Value):
    snapshot: CandidateSnapshot = Field(repr=False)
    events: Items[CandidateEvent] = Field(min_length=1, repr=False)
    release_eligible: No = False

    @property
    def state(self) -> CandidateState:
        return self.events[-1].state

    @property
    def revision(self) -> int:
        return self.events[-1].revision

    @property
    def review_status(self) -> Literal["pending", "reviewed", "approved", "rejected"]:
        if self.state == "production_approved":
            return "approved"
        if self.state == "human_reviewed":
            return "reviewed"
        return "rejected" if self.state == "rejected" else "pending"

    @model_validator(mode="after")
    def ordered_bound_events(self) -> Self:
        previous: CandidateState | None = None
        previous_time = self.snapshot.created_at
        for revision, event in enumerate(self.events):
            if event.candidate_id != self.snapshot.id or event.revision != revision:
                raise ValueError("Candidate audit events must be ordered and identity-bound")
            if event.previous_state != previous:
                raise ValueError("Candidate audit chain is inconsistent")
            if event.created_at < previous_time:
                raise ValueError("Candidate audit timestamps must preserve chronological order")
            allowed = (
                event.action == "created"
                and revision == 0
                and event.state == "composed"
                or event.action == "validation"
                and previous in {"composed", "validation_unavailable"}
                and event.state in {"validated", "validation_unavailable", "rejected"}
                or event.action == "human_review"
                and previous == "validated"
                and event.state == "human_reviewed"
                or event.action == "production_approval"
                and previous == "human_reviewed"
                and event.state == "production_approved"
                or event.action == "reject"
                and previous in {"validated", "human_reviewed"}
                and event.state == "rejected"
            )
            if not allowed:
                raise ValueError("Candidate audit contains an invalid transition")
            if event.action == "production_approval" and (
                self.snapshot.generation_origin == "mock"
                or event.reviewed_blueprint_sha256 != self.snapshot.source_blueprint.content_sha256
            ):
                raise ValueError("Production review requires the exact non-mock source attestation")
            if event.validation is not None and (
                event.validation.identity != self.snapshot.identity
                or event.validation.content_sha256 != self.snapshot.context()[0].canonical_digest
            ):
                raise ValueError("Validation receipt belongs to another immutable candidate")
            previous = event.state
            previous_time = event.created_at
        return self
