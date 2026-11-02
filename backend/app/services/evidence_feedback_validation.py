"""Validate a whole wording selection, then render only server-authorized claims.

No provider prose is presented. A rejected selection cannot leave behind its
conclusions or repaired citations: deterministic fallback renders the original
policy bundle instead, with an explicit delivery reason.
"""

from typing import Literal
from uuid import UUID

from app.ai.json_output import strict_json_object
from app.schemas.engineering_evidence import (
    EngineeringObservation,
    HintEvidence,
    RetrievalEvidence,
    SourceReference,
)
from app.schemas.evidence_feedback import (
    POLICY_VERSION,
    SCHEMA_VERSION,
    EvidenceReference,
    FallbackReason,
    FeedbackCompletion,
    FeedbackReply,
    FeedbackRequest,
    FeedbackSection,
    FeedbackSelection,
    FeedbackStatement,
    LessonCitation,
    SectionName,
)

MAX_SELECTION_BYTES = 8192


def validate_feedback_selection(
    request: FeedbackRequest, completion: FeedbackCompletion
) -> FeedbackSelection:
    checked = FeedbackRequest.model_validate(request.model_dump(warnings=False))
    received = FeedbackCompletion.model_validate(completion.model_dump(warnings=False))
    if received.status != "success" or received.text is None or received.source != "test_fixture":
        raise ValueError("Feedback provider did not supply a usable selection")
    # JSON-mode validation parses UUIDs and the established enum taxonomy while
    # this preliminary parse rejects duplicate keys, nonfinite values and depth.
    strict_json_object(received.text, max_bytes=MAX_SELECTION_BYTES)
    selection = FeedbackSelection.model_validate_json(received.text)
    if (
        selection.request_id != checked.request_id
        or selection.policy_version != checked.policy_version
        or selection.lesson != checked.evidence.lesson
        or selection.state != checked.state
    ):
        raise ValueError("Feedback selection changed its authorized scope")
    choices = {choice.claim_id: choice for choice in selection.choices}
    claims = {claim.claim_id: claim for claim in checked.claims}
    if choices.keys() != claims.keys():
        raise ValueError("Feedback selection must preserve every authorized claim")
    for identity, claim in claims.items():
        choice = choices[identity]
        if (
            choice.wording_id not in {wording.wording_id for wording in claim.wordings}
            or set(choice.evidence_ids) != set(claim.evidence_ids)
            or set(choice.lesson_reference_ids) != set(claim.lesson_reference_ids)
            or set(choice.coverage_refs) != set(claim.coverage_refs)
        ):
            raise ValueError("Feedback selection must preserve each claim's exact references")
    return selection


def _sources(
    record: EngineeringObservation | HintEvidence | RetrievalEvidence,
) -> tuple[SourceReference, ...]:
    references = [record.source]
    if isinstance(record, EngineeringObservation):
        references.extend(record.related_sources)
        references.extend(check.source for check in record.checks)
        references.extend(record.assistance.requested_before)
        references.extend(record.assistance.delivered_before)
    elif isinstance(record, RetrievalEvidence):
        references.append(record.checkpoint)
        references.extend(record.assistance.requested_before)
        references.extend(record.assistance.delivered_before)
    # The same immutable source may have several provenance roles. Present its
    # identity once; never manufacture an evidence event for an out-of-window hint.
    unique = {(reference.kind, reference.record_id): reference for reference in references}
    return tuple(sorted(unique.values(), key=lambda ref: (ref.kind, str(ref.record_id))))


def render_feedback(
    request: FeedbackRequest,
    selection: FeedbackSelection | None = None,
    *,
    delivery: Literal["mock", "deterministic"] = "deterministic",
    fallback_reason: FallbackReason | None = None,
) -> FeedbackReply:
    checked = FeedbackRequest.model_validate(request.model_dump(warnings=False))
    if selection is not None:
        # This also protects internal callers passing model_construct/model_copy.
        selected = validate_feedback_selection(
            checked,
            FeedbackCompletion(
                status="success", text=selection.model_dump_json(), source="test_fixture"
            ),
        )
        choices = {choice.claim_id: choice.wording_id for choice in selected.choices}
    else:
        if delivery == "mock":
            raise ValueError("Mock delivery requires a fully validated provider selection")
        choices = {claim.claim_id: claim.wordings[0].wording_id for claim in checked.claims}
    sections: list[FeedbackSection] = []
    kinds: tuple[SectionName, ...] = ("demonstrated", "needs_improvement", "why", "next")
    for kind in kinds:
        items: list[FeedbackStatement] = []
        for claim in checked.claims:
            if claim.section != kind:
                continue
            wording = next(w for w in claim.wordings if w.wording_id == choices[claim.claim_id])
            items.append(
                FeedbackStatement(
                    claim_id=claim.claim_id,
                    role=claim.role,
                    text=wording.text,
                    evidence_ids=claim.evidence_ids,
                    lesson_reference_ids=claim.lesson_reference_ids,
                    coverage_refs=claim.coverage_refs,
                )
            )
        if items:
            sections.append(FeedbackSection(kind=kind, items=tuple(items)))
    evidence_ids = {identity for claim in checked.claims for identity in claim.evidence_ids}
    lesson_ids = {identity for claim in checked.claims for identity in claim.lesson_reference_ids}
    coverage = {identity for claim in checked.claims for identity in claim.coverage_refs}
    records: tuple[EngineeringObservation | HintEvidence | RetrievalEvidence, ...] = (
        *checked.evidence.observations,
        *checked.evidence.hint_events,
        *checked.evidence.retrieval_events,
    )
    return FeedbackReply(
        schema_version=SCHEMA_VERSION,
        policy_version=POLICY_VERSION,
        request_id=checked.request_id,
        session_id=checked.evidence.query.session_id,
        lesson=checked.evidence.lesson,
        state=checked.state,
        delivery=delivery,
        fallback_reason=fallback_reason,
        notice=(
            "Provider wording was unavailable or rejected; this feedback uses deterministic policy."
            if fallback_reason is not None
            else None
        ),
        sections=tuple(sections),
        evidence_references=tuple(
            EvidenceReference(evidence_id=record.id, sources=_sources(record))
            for record in records
            if record.id in evidence_ids
        ),
        lesson_references=tuple(
            LessonCitation(reference_id=ref.reference_id, lesson=ref.lesson, sha256=ref.sha256)
            for ref in checked.lesson_references
            if ref.reference_id in lesson_ids
        ),
        coverage_references=tuple(
            item for item in checked.evidence.coverage if item.competency in coverage
        ),
    )


def unavailable_feedback(
    request_id: UUID, session_id: UUID, reason: FallbackReason
) -> FeedbackReply:
    return FeedbackReply(
        schema_version=SCHEMA_VERSION,
        policy_version=POLICY_VERSION,
        request_id=request_id,
        session_id=session_id,
        lesson=None,
        state="unavailable",
        delivery="unavailable",
        fallback_reason=reason,
        notice="Feedback is unavailable because trusted source evidence could not be established.",
        sections=(),
        evidence_references=(),
        lesson_references=(),
        coverage_references=(),
    )
