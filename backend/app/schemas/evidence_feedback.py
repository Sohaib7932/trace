"""Internal feedback values; only deterministic policy authorizes substantive claims.

Provider output selects already authorized wording and references. It contains
no free prose, learner grade, evaluator configuration or new evidence facts.
These structural checks do not replace repository authorization or policy.
"""

import hashlib
from typing import Annotated, Final, Literal, Self
from uuid import UUID

from pydantic import AfterValidator, Field, StrictInt, field_validator, model_validator

from app.domain.lesson_spec.fields import Digest, Items, LocalId, Value, plain_text
from app.schemas.ai_client import ClientErrorCode
from app.schemas.engineering_evidence import (
    Competency,
    EngineeringEvidenceBatch,
    EngineeringObservation,
    EvidenceCoverage,
    HintEvidence,
    LessonPin,
    RetrievalEvidence,
    SourceReference,
)
from app.schemas.generation import CompletionStatus, captured_text
from app.schemas.learner_evidence import UTCInstant

SCHEMA_VERSION: Final = "evidence-feedback-v1"
POLICY_VERSION: Final = "evidence-feedback-policy-v1"
SELECTION_VERSION: Final = "evidence-feedback-selection-v1"
MAX_FEEDBACK_BYTES = 65536

type FeedbackState = Literal[
    "supported", "partially_supported", "insufficient_evidence", "unavailable"
]
type SectionName = Literal["demonstrated", "needs_improvement", "why", "next"]
type LessonField = Literal["title", "objective", "scenario", "outgoing_code", "schema_code"]
type FeedbackRole = Literal["fact", "limitation", "next_step"]
type ClaimRole = FeedbackRole
type WordingId = Literal["plain", "concise"]
type FallbackReason = Literal[
    "disabled",
    "provider_unavailable",
    "provider_timeout",
    "provider_exception",
    "invalid_output",
    "source_unavailable",
    "source_invalid",
    "context_limit",
]


def _utf8(value: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError("Feedback content must be valid UTF-8") from exc
    return value


def _copy(value: str) -> str:
    plain_text(value)
    return _utf8(value)


def _unique(values: tuple[object, ...]) -> None:
    if len(values) != len(set(values)):
        raise ValueError("Feedback references cannot be repeated")


def _references(
    evidence_ids: tuple[UUID, ...],
    lesson_ids: tuple[LessonField, ...],
    coverage_refs: tuple[Competency, ...],
) -> None:
    for values in (evidence_ids, lesson_ids, coverage_refs):
        _unique(values)


def _fresh_values(value: object) -> object:
    """Revalidate typed Python values without accepting coercible wire history."""
    if isinstance(value, Value):
        return _fresh_values(value.model_dump(warnings=False))
    if isinstance(value, dict):
        return {key: _fresh_values(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return tuple(_fresh_values(item) for item in value)
    return value


type FeedbackText = Annotated[str, Field(min_length=1, max_length=600), AfterValidator(_copy)]
type LessonText = Annotated[str, Field(min_length=1, max_length=2400), AfterValidator(_utf8)]
type EvidenceIds = Annotated[Items[UUID], Field(max_length=8)]
type LessonIds = Annotated[Items[LessonField], Field(max_length=5)]
type CoverageRefs = Annotated[Items[Competency], Field(max_length=6)]


class FeedbackQuery(Value):
    """Unprivileged selectors only; the service obtains the owner from its principal."""

    request_id: UUID
    session_id: UUID
    start_at: UTCInstant
    end_at: UTCInstant
    as_of: UTCInstant
    max_records: Annotated[StrictInt, Field(ge=1, le=64)]

    @model_validator(mode="after")
    def ordered_window(self) -> Self:
        if not self.start_at < self.end_at <= self.as_of:
            raise ValueError("Require an increasing window ending no later than as_of")
        return self


class LessonReference(Value):
    reference_id: LessonField
    lesson: LessonPin
    text: LessonText = Field(repr=False)
    sha256: Digest

    @model_validator(mode="after")
    def exact_bytes(self) -> Self:
        if hashlib.sha256(self.text.encode("utf-8")).hexdigest() != self.sha256:
            raise ValueError("A lesson reference must bind the exact trusted UTF-8 bytes")
        return self


class FeedbackWording(Value):
    wording_id: WordingId
    text: FeedbackText = Field(repr=False)


class FeedbackClaim(Value):
    claim_id: LocalId
    section: SectionName
    role: ClaimRole
    competency: Competency | None
    evidence_ids: EvidenceIds
    lesson_reference_ids: LessonIds
    coverage_refs: CoverageRefs
    wordings: Items[FeedbackWording] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def structured_claim(self) -> Self:
        _references(self.evidence_ids, self.lesson_reference_ids, self.coverage_refs)
        _unique(tuple(item.wording_id for item in self.wordings))
        if self.role == "fact" and not self.evidence_ids:
            raise ValueError("A substantive fact requires canonical evidence")
        if self.section == "next":
            if self.role != "next_step" or not self.lesson_reference_ids:
                raise ValueError("The next step must cite approved lesson material")
        elif self.role == "next_step":
            raise ValueError("An actionable next step belongs only in the next section")
        if self.section in {"demonstrated", "needs_improvement"} and self.role != "fact":
            raise ValueError("Demonstrated actions and discrepancies require factual observations")
        return self


def _source_keys(batch: EngineeringEvidenceBatch) -> set[tuple[str, UUID]]:
    keys: set[tuple[str, UUID]] = set()
    records: tuple[EngineeringObservation | HintEvidence | RetrievalEvidence, ...] = (
        *batch.observations,
        *batch.hint_events,
        *batch.retrieval_events,
    )
    for record in records:
        refs = [record.source]
        if isinstance(record, EngineeringObservation):
            refs.extend(record.related_sources)
            refs.extend(check.source for check in record.checks)
            refs.extend(record.assistance.requested_before)
            refs.extend(record.assistance.delivered_before)
        elif not isinstance(record, HintEvidence):
            refs.append(record.checkpoint)
            refs.extend(record.assistance.requested_before)
            refs.extend(record.assistance.delivered_before)
        keys.update((ref.kind, ref.record_id) for ref in refs)
    return keys


class FeedbackRequest(Value):
    """Server-built policy bundle, not a client input or a provider's authority."""

    schema_version: Literal["evidence-feedback-v1"]
    policy_version: Literal["evidence-feedback-policy-v1"]
    request_id: UUID
    evidence: EngineeringEvidenceBatch = Field(repr=False)
    focus: SourceReference | None
    state: FeedbackState
    lesson_references: Items[LessonReference] = Field(min_length=5, max_length=5, repr=False)
    claims: Items[FeedbackClaim] = Field(min_length=1, max_length=16, repr=False)

    @field_validator("evidence", "focus", "lesson_references", "claims", mode="before")
    @classmethod
    def fresh_nested_python_values(cls, value: object) -> object:
        # The request is an internal typed envelope, not a client JSON endpoint.
        # Preserve datetime/UUID/enum values and reject forged nested instances
        # before their after-validators could inspect unvalidated attributes.
        return _fresh_values(value)

    @model_validator(mode="after")
    def bound_authorized_bundle(self) -> Self:
        # Rebuild nested values: a Python model_construct/model_copy instance is
        # not a substitute for canonical validation at this service boundary.
        checked = EngineeringEvidenceBatch.model_validate(self.evidence.model_dump(warnings=False))
        refs = tuple(
            LessonReference.model_validate(ref.model_dump(warnings=False))
            for ref in self.lesson_references
        )
        claims = tuple(
            FeedbackClaim.model_validate(claim.model_dump(warnings=False)) for claim in self.claims
        )
        focus = (
            SourceReference.model_validate(self.focus.model_dump(warnings=False))
            if self.focus is not None
            else None
        )
        object.__setattr__(self, "evidence", checked)
        object.__setattr__(self, "lesson_references", refs)
        object.__setattr__(self, "claims", claims)
        object.__setattr__(self, "focus", focus)
        if self.state == "unavailable":
            raise ValueError("Unavailable source evidence cannot create a feedback request")
        records: tuple[EngineeringObservation | HintEvidence | RetrievalEvidence, ...] = (
            *checked.observations,
            *checked.hint_events,
            *checked.retrieval_events,
        )
        if len(records) > 64:
            raise ValueError("Feedback contexts contain at most 64 canonical evidence records")
        lesson_ids = tuple(ref.reference_id for ref in refs)
        _unique(lesson_ids)
        if set(lesson_ids) != {"title", "objective", "scenario", "outgoing_code", "schema_code"}:
            raise ValueError("Feedback must bind all five trusted lesson fields")
        if any(ref.lesson != checked.lesson for ref in refs):
            raise ValueError("Lesson references must match the exact evidence lesson pin")
        _unique(tuple(claim.claim_id for claim in claims))
        if sum(claim.section == "next" for claim in claims) != 1:
            raise ValueError("Feedback must authorize exactly one actionable next step")
        evidence_ids = {record.id for record in records}
        coverage = {item.competency for item in checked.coverage}
        for claim in claims:
            if (
                not set(claim.evidence_ids) <= evidence_ids
                or not set(claim.lesson_reference_ids) <= set(lesson_ids)
                or not set(claim.coverage_refs) <= coverage
            ):
                raise ValueError("Every feedback claim must cite its authorized request bundle")
        if focus is not None and (focus.kind, focus.record_id) not in _source_keys(checked):
            raise ValueError("Feedback focus must identify an existing canonical source")
        if len(self.model_dump_json().encode("utf-8")) > MAX_FEEDBACK_BYTES:
            raise ValueError("Feedback context exceeds 65536 UTF-8 bytes")
        return self


class FeedbackChoice(Value):
    claim_id: LocalId
    wording_id: WordingId
    evidence_ids: EvidenceIds
    lesson_reference_ids: LessonIds
    coverage_refs: CoverageRefs

    @model_validator(mode="after")
    def unique_references(self) -> Self:
        _references(self.evidence_ids, self.lesson_reference_ids, self.coverage_refs)
        return self


class FeedbackSelection(Value):
    """The only model output: bounded choices, without prose or new factual fields."""

    schema_version: Literal["evidence-feedback-selection-v1"]
    policy_version: Literal["evidence-feedback-policy-v1"]
    request_id: UUID
    lesson: LessonPin
    state: FeedbackState
    choices: Items[FeedbackChoice] = Field(max_length=16)

    @model_validator(mode="after")
    def unique_claims(self) -> Self:
        _unique(tuple(choice.claim_id for choice in self.choices))
        return self


class FeedbackCompletion(Value):
    status: CompletionStatus
    text: Annotated[str, Field(max_length=65536), AfterValidator(captured_text)] | None = Field(
        repr=False
    )
    source: Literal["test_fixture", "none"]
    error_code: ClientErrorCode | None = None

    @model_validator(mode="after")
    def consistent_result(self) -> Self:
        if self.status == "success" and (
            self.text is None
            or not self.text.strip()
            or self.source != "test_fixture"
            or self.error_code is not None
        ):
            raise ValueError(
                "Successful feedback transport requires fixture output without an error"
            )
        return self


class FeedbackStatement(Value):
    claim_id: LocalId
    role: ClaimRole
    text: FeedbackText = Field(repr=False)
    evidence_ids: EvidenceIds
    lesson_reference_ids: LessonIds
    coverage_refs: CoverageRefs

    @model_validator(mode="after")
    def referenced_statement(self) -> Self:
        _references(self.evidence_ids, self.lesson_reference_ids, self.coverage_refs)
        if self.role == "fact" and not self.evidence_ids:
            raise ValueError("A rendered factual statement must retain canonical evidence")
        if self.role == "next_step" and not self.lesson_reference_ids:
            raise ValueError("A rendered next step must retain approved lesson material")
        return self


class FeedbackSection(Value):
    kind: SectionName
    items: Items[FeedbackStatement] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def section_roles(self) -> Self:
        _unique(tuple(item.claim_id for item in self.items))
        if self.kind == "next":
            if len(self.items) != 1 or self.items[0].role != "next_step":
                raise ValueError("The next section contains exactly one actionable step")
        elif any(item.role == "next_step" for item in self.items):
            raise ValueError("An actionable step belongs only in the next section")
        if self.kind in {"demonstrated", "needs_improvement"} and any(
            item.role != "fact" for item in self.items
        ):
            raise ValueError("Action and discrepancy sections contain supported factual statements")
        return self


class EvidenceReference(Value):
    evidence_id: UUID
    sources: Items[SourceReference] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique_sources(self) -> Self:
        _unique(tuple((ref.kind, ref.record_id) for ref in self.sources))
        return self


class LessonCitation(Value):
    reference_id: LessonField
    lesson: LessonPin
    sha256: Digest


class FeedbackReply(Value):
    schema_version: Literal["evidence-feedback-v1"]
    policy_version: Literal["evidence-feedback-policy-v1"]
    request_id: UUID
    session_id: UUID
    lesson: LessonPin | None
    state: FeedbackState
    delivery: Literal["mock", "deterministic", "unavailable"]
    fallback_reason: FallbackReason | None
    notice: FeedbackText | None
    sections: Items[FeedbackSection] = Field(max_length=4)
    evidence_references: Items[EvidenceReference] = Field(max_length=64)
    lesson_references: Items[LessonCitation] = Field(max_length=5)
    coverage_references: Items[EvidenceCoverage] = Field(max_length=6)

    @model_validator(mode="after")
    def safe_presentation(self) -> Self:
        _unique(tuple(section.kind for section in self.sections))
        evidence_ids = tuple(ref.evidence_id for ref in self.evidence_references)
        lesson_ids = tuple(ref.reference_id for ref in self.lesson_references)
        coverage = tuple(ref.competency for ref in self.coverage_references)
        _references(evidence_ids, lesson_ids, coverage)
        statements = tuple(item for section in self.sections for item in section.items)
        _unique(tuple(item.claim_id for item in statements))
        if self.state == "unavailable":
            if (
                self.delivery != "unavailable"
                or self.notice is None
                or self.fallback_reason
                not in {"source_unavailable", "source_invalid", "context_limit"}
                or self.sections
                or self.evidence_references
                or self.lesson_references
                or self.coverage_references
            ):
                raise ValueError("Unavailable source evidence returns only a safe diagnostic")
            return self
        if self.lesson is None or self.delivery == "unavailable":
            raise ValueError("Usable feedback retains its trusted lesson identity")
        if self.delivery == "mock" and self.fallback_reason is not None:
            raise ValueError("Accepted mock output cannot carry a fallback reason")
        if self.delivery == "deterministic" and self.fallback_reason in {
            "source_unavailable",
            "source_invalid",
            "context_limit",
        }:
            raise ValueError("Invalid source evidence cannot be rendered as usable feedback")
        if any(ref.lesson != self.lesson for ref in self.lesson_references):
            raise ValueError("All displayed lesson citations must preserve the exact lesson pin")
        for statement in statements:
            if (
                not set(statement.evidence_ids) <= set(evidence_ids)
                or not set(statement.lesson_reference_ids) <= set(lesson_ids)
                or not set(statement.coverage_refs) <= set(coverage)
            ):
                raise ValueError("Rendered statements must retain every supporting citation")
        return self
