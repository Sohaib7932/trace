"""Internal observations of trusted records, never grades or authorization claims.

Only the server extractor establishes source ownership, timestamps and runtime
provenance. These immutable values additionally reject inconsistent projections.
No constructor creates identities, timestamps, persisted events or assistance.
"""

from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StrictBool, StrictInt, model_validator

from app.domain.lesson_spec.fields import Digest, Items, Value
from app.schemas.learner_evidence import UTCInstant


class Competency(StrEnum):
    PREDICTION = "prediction"
    INVESTIGATION = "investigation"
    MODIFICATION = "modification"
    DEBUGGING = "debugging"
    VERIFICATION = "verification"
    TRANSFER = "transfer"


class EvidenceQuery(Value):
    owner_learner_id: UUID = Field(repr=False)
    session_id: UUID = Field(repr=False)
    start_at: UTCInstant
    end_at: UTCInstant
    as_of: UTCInstant
    max_records: Annotated[StrictInt, Field(ge=1, le=10000)]

    @model_validator(mode="after")
    def ordered_window(self) -> Self:
        if not self.start_at < self.end_at <= self.as_of:
            raise ValueError("Require an increasing window ending no later than as_of")
        return self


class LessonPin(Value):
    version_id: UUID
    lesson_id: Literal["fastapi-payload-mismatch", "fastapi-nested-payload-transfer"]
    version: Literal["1.0.0"]
    content_hash: Digest


class RetrievalQuestionPin(Value):
    question_id: Literal["shipping-contract-v1", "report-contract-v1"]
    content_hash: Digest


class SourceReference(Value):
    kind: Literal[
        "prediction",
        "attempt",
        "verification_run",
        "verification_check",
        "hint_operation",
        "tutor_interaction",
        "retrieval_checkpoint",
        "retrieval_attempt",
    ]
    record_id: UUID = Field(repr=False)


def _unique_refs(refs: tuple[SourceReference, ...]) -> None:
    keys = [(ref.kind, ref.record_id) for ref in refs]
    if len(keys) != len(set(keys)):
        raise ValueError("Source references cannot be repeated")


class AssistanceContext(Value):
    category: Literal["independent", "authored_hint_assisted", "tutor_assisted", "unknown"]
    requested_before: Items[SourceReference] = Field(max_length=3)
    delivered_before: Items[SourceReference] = Field(max_length=3)

    @model_validator(mode="after")
    def supported_assistance(self) -> Self:
        # There is no authored-hint viewing or independent-work attestation record.
        if self.category in {"independent", "authored_hint_assisted"}:
            raise ValueError("The current source records cannot establish this assistance claim")
        if (self.category == "tutor_assisted") != bool(self.delivered_before):
            raise ValueError("Tutor assistance requires recorded delivered guidance")
        if any(ref.kind != "hint_operation" for ref in self.requested_before):
            raise ValueError("Exact help request references must identify reservations")
        if any(ref.kind != "tutor_interaction" for ref in self.delivered_before):
            raise ValueError("Delivered help must identify final tutor interactions")
        _unique_refs(self.requested_before)
        _unique_refs(self.delivered_before)
        return self


class ObservedCheck(Value):
    source: SourceReference
    code: Literal[
        "http_status", "api_response", "validation", "row_count", "stored_values", "execution"
    ]
    matched: StrictBool
    origin: Literal["asgi_http", "fresh_database_read", "verifier", "server_lifecycle"]

    @model_validator(mode="after")
    def source_category(self) -> Self:
        if self.source.kind != "verification_check":
            raise ValueError("A verification observation must reference a persisted check")
        expected = (
            {"asgi_http"}
            if self.code in {"http_status", "api_response", "validation"}
            else {"fresh_database_read"}
            if self.code in {"row_count", "stored_values"}
            else {"verifier", "server_lifecycle"}
        )
        if self.origin not in expected:
            raise ValueError("Check category does not match its trusted evidence origin")
        if self.code == "execution" and self.matched:
            raise ValueError("Execution checks record an infrastructure failure")
        return self


class EngineeringObservation(Value):
    id: UUID
    schema_version: Literal["engineering-evidence-v1"]
    owner_learner_id: UUID = Field(repr=False)
    session_id: UUID = Field(repr=False)
    lesson: LessonPin
    competency: Competency
    event_type: Literal[
        "prediction_submitted",
        "modification_submitted",
        "verification_finished",
        "debugging_recovery_observed",
        "transfer_completed",
    ]
    outcome: Literal["success", "failure", "unknown", "unavailable"]
    basis: Literal["direct", "indirect"]
    occurred_at: UTCInstant
    source: SourceReference
    related_sources: Items[SourceReference] = Field(max_length=20)
    assistance: AssistanceContext
    checks: Items[ObservedCheck] = Field(max_length=5)

    @model_validator(mode="after")
    def consistent_observation(self) -> Self:
        expected = {
            "prediction_submitted": (Competency.PREDICTION, "prediction", "direct"),
            "modification_submitted": (Competency.MODIFICATION, "attempt", "direct"),
            "verification_finished": (Competency.VERIFICATION, "verification_run", "direct"),
            "debugging_recovery_observed": (Competency.DEBUGGING, "verification_run", "indirect"),
            "transfer_completed": (Competency.TRANSFER, "verification_run", "direct"),
        }[self.event_type]
        if (self.competency, self.source.kind, self.basis) != expected:
            raise ValueError("Observation classification must match its source event")
        _unique_refs((self.source, *self.related_sources))
        _unique_refs(tuple(check.source for check in self.checks))
        codes = [check.code for check in self.checks]
        if len(codes) != len(set(codes)):
            raise ValueError("A runtime evidence category cannot be repeated")
        is_runtime = self.source.kind == "verification_run"
        if is_runtime != bool(self.checks):
            raise ValueError("Only completed runtime observations contain verification checks")
        if self.event_type == "prediction_submitted":
            if self.outcome not in {"success", "failure"}:
                raise ValueError("A recorded answer has a deterministic observed outcome")
        elif self.event_type == "modification_submitted":
            if self.outcome != "unknown":
                raise ValueError("Submission alone does not establish modification correctness")
        elif self.event_type == "verification_finished":
            if self.outcome not in {"success", "failure", "unavailable"}:
                raise ValueError("A finished run has an observed result or infrastructure failure")
        elif self.outcome != "success":
            raise ValueError("Recovery and transfer events require observed successful execution")
        if is_runtime and self.outcome in {"success", "failure"}:
            if set(codes) != {
                "http_status",
                "api_response",
                "validation",
                "row_count",
                "stored_values",
            }:
                raise ValueError("Graded runtime results require all five real evidence categories")
            if (self.outcome == "success") != all(check.matched for check in self.checks):
                raise ValueError("Runtime outcome must agree with the actual evidence checks")
        if is_runtime and not any(ref.kind == "attempt" for ref in self.related_sources):
            raise ValueError("Runtime evidence must retain its modification attempt reference")
        if self.event_type == "debugging_recovery_observed" and not any(
            ref.kind == "verification_run" for ref in self.related_sources
        ):
            raise ValueError("Recovery must retain the earlier failed runtime reference")
        if self.event_type == "transfer_completed" and (
            self.lesson.lesson_id != "fastapi-nested-payload-transfer"
        ):
            raise ValueError("Only the pinned Tasks lesson supplies transfer completion")
        return self


class HintEvidence(Value):
    id: UUID
    schema_version: Literal["engineering-evidence-v1"]
    owner_learner_id: UUID = Field(repr=False)
    session_id: UUID = Field(repr=False)
    lesson: LessonPin
    event_type: Literal["hint_requested", "hint_finalized"]
    outcome: Literal["requested", "delivered", "error"]
    occurred_at: UTCInstant
    source: SourceReference

    @model_validator(mode="after")
    def consistent_event(self) -> Self:
        if self.event_type == "hint_requested":
            if (self.source.kind, self.outcome) != ("hint_operation", "requested"):
                raise ValueError("A help request is a reservation, never a delivery claim")
        elif self.source.kind != "tutor_interaction" or self.outcome == "requested":
            raise ValueError("A finalized hint must identify its delivered or error interaction")
        return self


class RetrievalEvidence(Value):
    """A recorded recall/diagnosis answer, without an engineering competency claim."""

    id: UUID
    schema_version: Literal["engineering-evidence-v1"]
    owner_learner_id: UUID = Field(repr=False)
    session_id: UUID = Field(repr=False)
    lesson: LessonPin
    event_type: Literal["retrieval_answered"]
    outcome: Literal["success", "failure"]
    occurred_at: UTCInstant
    source: SourceReference
    checkpoint: SourceReference
    question: RetrievalQuestionPin
    assistance: AssistanceContext

    @model_validator(mode="after")
    def consistent_retrieval(self) -> Self:
        if self.lesson.lesson_id != "fastapi-nested-payload-transfer":
            raise ValueError("Retrieval answers must retain their source Tasks lesson pin")
        if (
            self.source.kind != "retrieval_attempt"
            or self.checkpoint.kind != "retrieval_checkpoint"
        ):
            raise ValueError("Retrieval evidence requires its original answer and checkpoint")
        if (
            self.assistance.category != "unknown"
            or self.assistance.requested_before
            or self.assistance.delivered_before
        ):
            raise ValueError("The current records do not capture help for a retrieval answer")
        return self


type CoverageLimitation = Literal[
    "selected_outcome_only",
    "investigation_not_recorded",
    "finite_mapping_only",
    "code_patch_not_recorded",
    "runtime_outcome_separate",
    "recovery_chronology_only",
    "diagnosis_not_recorded",
    "outgoing_transfer_not_recorded",
    "exact_notes_parent_not_pinned",
]


class EvidenceCoverage(Value):
    """Current instrumentation support and event presence, never a learner score."""

    competency: Competency
    availability: Literal["direct", "partial", "unavailable"]
    observed_in_window: StrictBool
    limitations: Items[CoverageLimitation] = Field(max_length=4)

    @model_validator(mode="after")
    def supported_presence(self) -> Self:
        if self.availability == "unavailable" and self.observed_in_window:
            raise ValueError("Uninstrumented competencies cannot claim recorded observations")
        if len(self.limitations) != len(set(self.limitations)):
            raise ValueError("An instrumentation limitation cannot be repeated")
        return self


def coverage_profile(
    lesson: LessonPin, observed: frozenset[Competency]
) -> tuple[EvidenceCoverage, ...]:
    """Server-owned capture capabilities for the actual supported legacy lessons.

    Direct/partial/unavailable describe instrumentation, not successful evidence.
    Presence only means an observation exists, including unknown or unavailable
    runtime results. Auxiliary hint and retrieval records never establish it.
    """
    checked = LessonPin.model_validate(lesson.model_dump(warnings=False))
    if any(not isinstance(competency, Competency) for competency in observed):
        raise ValueError("Coverage requires the established competency taxonomy")
    rows = (
        (Competency.PREDICTION, "direct", ("selected_outcome_only",)),
        (Competency.INVESTIGATION, "unavailable", ("investigation_not_recorded",)),
        (
            Competency.MODIFICATION,
            "partial",
            ("finite_mapping_only", "code_patch_not_recorded", "runtime_outcome_separate"),
        ),
        (
            Competency.DEBUGGING,
            "partial",
            ("recovery_chronology_only", "diagnosis_not_recorded"),
        ),
        (Competency.VERIFICATION, "direct", ()),
        (
            Competency.TRANSFER,
            "unavailable" if checked.lesson_id == "fastapi-payload-mismatch" else "partial",
            (
                "outgoing_transfer_not_recorded"
                if checked.lesson_id == "fastapi-payload-mismatch"
                else "exact_notes_parent_not_pinned",
            ),
        ),
    )
    return tuple(
        EvidenceCoverage.model_validate(
            {
                "competency": competency,
                "availability": availability,
                "observed_in_window": competency in observed,
                "limitations": limitations,
            }
        )
        for competency, availability, limitations in rows
    )


class EngineeringEvidenceBatch(Value):
    query: EvidenceQuery = Field(repr=False)
    lesson: LessonPin
    coverage: Items[EvidenceCoverage] = Field(min_length=6, max_length=6)
    observations: Items[EngineeringObservation] = Field(max_length=10000)
    hint_events: Items[HintEvidence] = Field(max_length=10000)
    retrieval_events: Items[RetrievalEvidence] = Field(max_length=10000)

    @model_validator(mode="after")
    def bounded_cohort(self) -> Self:
        records: tuple[EngineeringObservation | HintEvidence | RetrievalEvidence, ...] = (
            *self.observations,
            *self.hint_events,
            *self.retrieval_events,
        )
        if len(records) > self.query.max_records:
            raise ValueError("Evidence exceeds the explicit combined record limit")
        ids = [record.id for record in records]
        source_events = [
            (record.event_type, record.source.kind, record.source.record_id) for record in records
        ]
        if len(ids) != len(set(ids)) or len(source_events) != len(set(source_events)):
            raise ValueError("The same observation cannot be emitted more than once")
        if any(record.lesson != self.lesson for record in records):
            raise ValueError("A session cannot mix pinned lesson definitions")
        actual = {item.competency: item for item in self.coverage}
        observed = frozenset(item.competency for item in self.observations)
        expected = {item.competency: item for item in coverage_profile(self.lesson, observed)}
        if len(actual) != 6 or actual != expected:
            raise ValueError("Coverage must match the source lesson and actual competency events")
        for record in records:
            if (record.owner_learner_id, record.session_id) != (
                self.query.owner_learner_id,
                self.query.session_id,
            ):
                raise ValueError("Evidence must belong to the authorized learner and session")
            if not self.query.start_at <= record.occurred_at < self.query.end_at:
                raise ValueError("Evidence must fall in the explicit half-open event window")
        return self
