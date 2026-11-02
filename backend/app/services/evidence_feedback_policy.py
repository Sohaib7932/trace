"""Deterministic authorization of feedback, without grading or provider authority.

Inputs come from EngineeringEvidenceService, not from a client. This pure layer
checks structural/catalog consistency; repository authorization remains with the
extractor and the service's authenticated principal boundary.
"""

import hashlib
from uuid import UUID

from app.schemas.engineering_evidence import (
    Competency,
    EngineeringEvidenceBatch,
    EngineeringObservation,
    SourceReference,
)
from app.schemas.evidence_feedback import (
    ClaimRole,
    FeedbackClaim,
    FeedbackRequest,
    FeedbackState,
    FeedbackWording,
    LessonField,
    LessonReference,
    SectionName,
)
from app.schemas.lesson_assistant import PublicLessonContent
from app.services.catalog import (
    LESSON_ID,
    PUBLIC_CONTENT,
    TRANSFER_CONTENT,
    lesson_hash,
    transfer_hash,
)

_FIELDS: tuple[LessonField, ...] = (
    "title",
    "objective",
    "scenario",
    "outgoing_code",
    "schema_code",
)


def _claim(
    identity: str,
    section: SectionName,
    role: ClaimRole,
    text: str,
    concise: str,
    *,
    competency: Competency | None = None,
    evidence: tuple[UUID, ...] = (),
    lesson: tuple[LessonField, ...] = (),
    coverage: tuple[Competency, ...] = (),
) -> FeedbackClaim:
    return FeedbackClaim(
        claim_id=identity,
        section=section,
        role=role,
        competency=competency,
        evidence_ids=evidence,
        lesson_reference_ids=lesson,
        coverage_refs=coverage,
        wordings=(
            FeedbackWording(wording_id="plain", text=text),
            FeedbackWording(wording_id="concise", text=concise),
        ),
    )


def _latest(records: tuple[EngineeringObservation, ...]) -> EngineeringObservation | None:
    return max(records, key=lambda record: (record.occurred_at, str(record.id)), default=None)


def _attempt(record: EngineeringObservation) -> SourceReference | None:
    return next((ref for ref in record.related_sources if ref.kind == "attempt"), None)


def _lesson_references(
    batch: EngineeringEvidenceBatch, public_content: PublicLessonContent
) -> tuple[LessonReference, ...]:
    public = PublicLessonContent.model_validate(public_content.model_dump(warnings=False))
    supplied = public.model_dump()
    if batch.lesson.lesson_id == LESSON_ID:
        expected = PUBLIC_CONTENT
        digest = lesson_hash(PUBLIC_CONTENT, "content", "rejected")
    else:
        expected = TRANSFER_CONTENT
        digest = transfer_hash(TRANSFER_CONTENT)
    if supplied != expected or batch.lesson.content_hash != digest:
        raise ValueError("Feedback material must match the pinned trusted legacy catalog")
    return tuple(
        LessonReference(
            reference_id=field,
            lesson=batch.lesson,
            text=supplied[field],
            sha256=hashlib.sha256(supplied[field].encode("utf-8")).hexdigest(),
        )
        for field in _FIELDS
    )


def build_feedback_request(
    request_id: UUID,
    batch: EngineeringEvidenceBatch,
    public_content: PublicLessonContent,
) -> FeedbackRequest:
    """Authorize bounded factual wording from canonical, already owned evidence.

    Timestamp/ID ordering is a deterministic selection rule, not proof that a
    tied timestamp identifies the learner's last real-world action. Wording
    therefore says "selected" rather than inferring a temporal ordering.
    """
    checked = EngineeringEvidenceBatch.model_validate(batch.model_dump(warnings=False))
    references = _lesson_references(checked, public_content)
    observations = checked.observations
    predictions = tuple(o for o in observations if o.event_type == "prediction_submitted")
    if len(predictions) > 1:
        raise ValueError("One legacy session cannot have multiple original predictions")
    prediction = predictions[0] if predictions else None
    modification = _latest(
        tuple(o for o in observations if o.event_type == "modification_submitted")
    )
    runs = tuple(o for o in observations if o.event_type == "verification_finished")
    focus = modification.source if modification else None
    if focus is None:
        latest_run = _latest(runs)
        focus = _attempt(latest_run) if latest_run is not None else None
    selected_runs = tuple(o for o in runs if focus is not None and _attempt(o) == focus)
    graded = tuple(o for o in selected_runs if o.outcome in {"success", "failure"})
    if len({o.outcome for o in graded}) > 1:
        raise ValueError("A selected attempt cannot have conflicting finalized grades")
    verification = _latest(graded or selected_runs)
    if focus is None and prediction is not None:
        focus = prediction.source
    if focus is None and checked.retrieval_events:
        recall = max(checked.retrieval_events, key=lambda r: (r.occurred_at, str(r.id)))
        focus = recall.checkpoint

    claims: list[FeedbackClaim] = []
    if prediction is not None:
        correct = prediction.outcome == "success"
        claims.append(
            _claim(
                "prediction-accuracy",
                "demonstrated" if correct else "needs_improvement",
                "fact",
                (
                    "Your original prediction matched the pinned lesson outcome. This "
                    "confirms that prediction only."
                )
                if correct
                else (
                    "Your original prediction did not match the pinned lesson outcome. This "
                    "identifies an outcome discrepancy, not a diagnosis of understanding."
                ),
                "The recorded prediction was correct; implementation competence remains separate."
                if correct
                else (
                    "The recorded prediction was incorrect; the evidence does not diagnose "
                    "why you chose it."
                ),
                competency=Competency.PREDICTION,
                evidence=(prediction.id,),
                lesson=("scenario",),
                coverage=(Competency.PREDICTION,),
            )
        )
    if modification is not None:
        claims.append(
            _claim(
                "mapping-submitted",
                "demonstrated",
                "fact",
                (
                    "You submitted the selected finite payload-mapping attempt. The "
                    "submission itself does not establish successful execution or an "
                    "independently authored code change."
                ),
                "The selected mapping submission is recorded; its execution outcome is separate.",
                competency=Competency.MODIFICATION,
                evidence=(modification.id,),
                coverage=(Competency.MODIFICATION,),
            )
        )

    if verification is not None:
        if verification.outcome == "success":
            claims.append(
                _claim(
                    "verification-passed",
                    "demonstrated",
                    "fact",
                    (
                        "The selected attempt passed all five recorded checks: HTTP status, API "
                        "response, receiving-schema validation, row count and stored values. The "
                        "database checks came from independent fresh readback."
                    ),
                    (
                        "All five checks passed for the selected attempt, including independent "
                        "database readback."
                    ),
                    competency=Competency.VERIFICATION,
                    evidence=(verification.id,),
                    coverage=(Competency.VERIFICATION,),
                )
            )
        elif verification.outcome == "failure":
            claims.append(
                _claim(
                    "verification-failed",
                    "needs_improvement",
                    "fact",
                    (
                        "The selected attempt failed trusted runtime verification. Its recorded "
                        "acceptance checks did not all match; this is an observed result for that"
                        " attempt."
                    ),
                    "The selected attempt failed its recorded verification checks.",
                    competency=Competency.VERIFICATION,
                    evidence=(verification.id,),
                    coverage=(Competency.VERIFICATION,),
                )
            )
        else:
            claims.append(
                _claim(
                    "verification-unavailable",
                    "why",
                    "fact",
                    (
                        "Verification for the selected attempt was unavailable or inconsistent. "
                        "This does not establish a learner mistake or a successful "
                        "implementation."
                    ),
                    "The selected verification is unavailable; no learner failure is inferred.",
                    competency=Competency.VERIFICATION,
                    evidence=(verification.id,),
                    coverage=(Competency.VERIFICATION,),
                )
            )
        if verification.outcome in {"success", "failure"}:
            validation = next(check for check in verification.checks if check.code == "validation")
            claims.append(
                _claim(
                    "receiving-contract",
                    "why",
                    "fact",
                    (
                        "The recorded receiving-schema validation check passed for the selected "
                        "attempt. Compare the approved request builder and receiving schema to "
                        "understand the accepted contract."
                    )
                    if validation.matched
                    else (
                        "The recorded receiving-schema validation check did not pass for the "
                        "selected attempt. The approved request builder and receiving schema are "
                        "the relevant material to compare; the evidence does not diagnose your "
                        "reasoning."
                    ),
                    (
                        "The selected schema-validation check passed; the pinned code shows the "
                        "receiving contract."
                    )
                    if validation.matched
                    else (
                        "The selected schema-validation check did not pass; compare the pinned "
                        "outgoing and receiving code."
                    ),
                    competency=Competency.VERIFICATION,
                    evidence=(verification.id,),
                    lesson=("outgoing_code", "schema_code"),
                )
            )
        recovery = _latest(
            tuple(
                o
                for o in observations
                if o.event_type == "debugging_recovery_observed"
                and o.source == verification.source
                and _attempt(o) == focus
            )
        )
        if recovery is not None and verification.outcome == "success":
            claims.append(
                _claim(
                    "observed-recovery",
                    "demonstrated",
                    "fact",
                    (
                        "The recorded sequence shows an earlier failed attempt followed by a "
                        "changed attempt whose verification passed. This establishes recovery "
                        "chronology, not a proven debugging diagnosis."
                    ),
                    (
                        "A failed-then-changed-and-passed sequence was recorded; diagnosis "
                        "remains unproven."
                    ),
                    competency=Competency.DEBUGGING,
                    evidence=(recovery.id, verification.id),
                    coverage=(Competency.DEBUGGING,),
                )
            )
        transfer = _latest(
            tuple(
                o
                for o in observations
                if o.event_type == "transfer_completed"
                and o.source == verification.source
                and _attempt(o) == focus
            )
        )
        if transfer is not None and verification.outcome == "success":
            claims.append(
                _claim(
                    "tasks-transfer-result",
                    "demonstrated",
                    "fact",
                    (
                        "The related Tasks exercise completed with the selected passing "
                        "verification. This reports that actual transfer-task result, not general"
                        " transfer mastery."
                    ),
                    (
                        "The recorded Tasks transfer exercise completed with a verified passing "
                        "result."
                    ),
                    competency=Competency.TRANSFER,
                    evidence=(transfer.id,),
                    coverage=(Competency.TRANSFER,),
                )
            )

    action = modification or verification or prediction
    if action is not None:
        if (
            modification is not None
            and verification is not None
            and modification.assistance != verification.assistance
        ):
            raise ValueError("The same selected action cannot have conflicting assistance")
        delivered = action.assistance.category == "tutor_assisted"
        claims.append(
            _claim(
                "assistance-context",
                "why",
                "fact" if delivered else "limitation",
                (
                    "Tutor guidance was recorded as delivered before the selected action. Its"
                    " source references are retained; this does not establish independent "
                    "work."
                )
                if delivered
                else (
                    "The recorded assistance context for the selected action is unknown. A "
                    "hint reservation alone does not establish delivered help, and absence of"
                    " recorded help does not prove independent work."
                ),
                (
                    "Recorded tutor guidance preceded the selected action; independent work "
                    "is not established."
                )
                if delivered
                else (
                    "Assistance for the selected action remains unknown; independence is not "
                    "inferred."
                ),
                evidence=(action.id,),
                coverage=(action.competency,),
            )
        )
    elif checked.hint_events:
        hint = max(checked.hint_events, key=lambda h: (h.occurred_at, str(h.id)))
        text = (
            (
                "A hint request was recorded. The reservation alone does not establish "
                "that guidance was delivered."
            )
            if hint.event_type == "hint_requested"
            else "The selected tutor operation finished with an error; it is not a delivered hint."
            if hint.outcome == "error"
            else (
                "A delivered tutor result was recorded. With no competency action in this"
                " cohort, it does not establish assisted competence."
            )
        )
        claims.append(_claim("hint-record-only", "why", "fact", text, text, evidence=(hint.id,)))

    if not observations and checked.retrieval_events:
        recall = max(checked.retrieval_events, key=lambda r: (r.occurred_at, str(r.id)))
        text = (
            (
                "A saved retrieval answer was recorded as correct. This recall result "
                "does not establish implementation competence."
            )
            if recall.outcome == "success"
            else (
                "A saved retrieval answer was recorded as incorrect. This recall result "
                "does not establish an implementation failure or diagnose understanding."
            )
        )
        claims.append(
            _claim("retrieval-record-only", "why", "fact", text, text, evidence=(recall.id,))
        )

    if modification is not None and verification is None:
        claims.append(
            _claim(
                "execution-unproven",
                "why",
                "limitation",
                (
                    "No finalized verification for the selected mapping attempt appears in "
                    "this evidence cohort. Implementation success therefore remains unproven "
                    "here."
                ),
                "This cohort does not establish successful execution of the selected mapping.",
                evidence=(modification.id,),
                coverage=(Competency.MODIFICATION, Competency.VERIFICATION),
            )
        )
    claims.append(
        _claim(
            "instrumentation-limits",
            "why",
            "limitation",
            (
                "These records do not capture investigation actions, submitted code "
                "patches or a trusted diagnosis of debugging reasoning. They also do not "
                "prove independent work or reveal external help."
            ),
            (
                "Investigation, code authorship, debugging diagnosis and independent work"
                " remain unproven."
            ),
            coverage=(Competency.INVESTIGATION, Competency.MODIFICATION, Competency.DEBUGGING),
        )
    )
    if checked.lesson.lesson_id != LESSON_ID:
        claims.append(
            _claim(
                "transfer-parent-unknown",
                "why",
                "limitation",
                (
                    "The exact originating Notes-session relationship was not recorded for "
                    "this Tasks session. A completed related task cannot establish that "
                    "missing link."
                ),
                "The exact parent Notes-session link remains unavailable.",
                coverage=(Competency.TRANSFER,),
            )
        )
    if not observations:
        claims.append(
            _claim(
                "no-competency-observations",
                "why",
                "limitation",
                (
                    "This evidence cohort contains no canonical competency observations. "
                    "Missing observations are not failed competencies; no competence "
                    "conclusion is supported here."
                ),
                "No competency observations support an assessment in this cohort.",
                coverage=tuple(Competency),
            )
        )
    claims.append(
        _claim(
            "compare-receiving-contract",
            "next",
            "next_step",
            (
                "Compare the pinned outgoing request builder with the receiving schema, "
                "tracing each value to its required location before your next attempt."
            ),
            "Trace the outgoing values into the pinned receiving schema before the next attempt.",
            lesson=("outgoing_code", "schema_code"),
        )
    )

    state: FeedbackState = "supported"
    if not observations:
        state = "insufficient_evidence"
    elif (
        modification is not None
        and (verification is None or verification.outcome == "unavailable")
        or verification is not None
        and verification.outcome == "unavailable"
    ):
        state = "partially_supported"
    return FeedbackRequest(
        schema_version="evidence-feedback-v1",
        policy_version="evidence-feedback-policy-v1",
        request_id=request_id,
        evidence=checked,
        focus=focus,
        state=state,
        lesson_references=references,
        claims=tuple(claims),
    )
