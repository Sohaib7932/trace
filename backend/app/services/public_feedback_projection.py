"""Pure public disclosure of an already release-authorized feedback result.

Internal IDs and support graphs stay inside the backend. Local aliases are
meaningful only in their own response, never lookup keys or authorization.
"""

import hashlib
import json
from typing import Literal

from app.schemas.engineering_evidence import (
    EngineeringObservation,
    HintEvidence,
    RetrievalEvidence,
)
from app.schemas.evidence_feedback import FeedbackClaim, FeedbackState
from app.schemas.feedback_release import ReleasedFeedbackResult
from app.schemas.lesson_assistant import PublicLessonContent
from app.schemas.public_feedback import (
    LESSON_LABELS,
    NOTICE_DETERMINISTIC,
    NOTICE_INSUFFICIENT,
    NOTICE_MOCK,
    NOTICE_NOT_READY,
    NOTICE_NOT_SUPPORTED,
    NOTICE_UNAVAILABLE,
    FeedbackVisibilityPolicy,
    PublicEvidenceCitation,
    PublicFeedbackReply,
    PublicFeedbackSection,
    PublicFeedbackStatement,
    PublicLessonCitation,
    PublicLessonIdentity,
    PublicVerificationCheck,
)

_FIELDS = ("title", "objective", "scenario", "outgoing_code", "schema_code")
_CHECKS = frozenset({"http_status", "api_response", "validation", "row_count", "stored_values"})
_PUBLIC_CLAIMS = frozenset(
    {
        "prediction-accuracy",
        "mapping-submitted",
        "verification-passed",
        "verification-failed",
        "verification-unavailable",
        "receiving-contract",
        "observed-recovery",
        "tasks-transfer-result",
        "assistance-context",
        "execution-unproven",
        "instrumentation-limits",
        "transfer-parent-unknown",
        "no-competency-observations",
        "compare-receiving-contract",
    }
)
_DESCRIPTIONS = {
    "prediction_submitted": "Your original prediction",
    "modification_submitted": "Your submitted attempt",
    "verification_finished": "Your runtime verification",
    "debugging_recovery_observed": "Your recorded recovery sequence",
    "transfer_completed": "Your completed Tasks exercise",
    "hint_requested": "Your hint request",
    "hint_finalized": "Your tutor guidance record",
}
type _Record = EngineeringObservation | HintEvidence | RetrievalEvidence


def public_content_sha256(content: PublicLessonContent) -> str:
    """Hash only the five public fields with exact original Unicode/newline bytes.

    Encoding: UTF-8 JSON object; keys sorted; compact comma/colon separators;
    ensure_ascii=False; allow_nan=False. No slug, version, private definition
    wrapper or database identity participates in this digest.
    """
    checked = PublicLessonContent.model_validate(content.model_dump(warnings=False))
    public = {field: getattr(checked, field) for field in _FIELDS}
    encoded = json.dumps(
        public,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def public_grounding_state(state: FeedbackState, has_competency_fact: bool) -> FeedbackState:
    """Filtering cannot manufacture support or turn missing data into failure."""
    if state not in {"supported", "partially_supported", "insufficient_evidence", "unavailable"}:
        raise ValueError("Unknown feedback grounding state")
    if type(has_competency_fact) is not bool:
        raise ValueError("A factual-support decision must be a boolean")
    if state in {"unavailable", "insufficient_evidence"}:
        return state
    return state if has_competency_fact else "insufficient_evidence"


def _empty(
    released: ReleasedFeedbackResult,
    policy: FeedbackVisibilityPolicy,
    availability: Literal["not_ready", "not_supported", "unavailable"],
) -> PublicFeedbackReply:
    return PublicFeedbackReply.model_validate(
        {
            "policy_version": policy.policy_version,
            "availability": availability,
            "feedback_state": "unavailable" if availability == "unavailable" else None,
            "delivery_state": "unavailable",
            "session_id": released.envelope.session.session_id,
            "lesson": None,
            "as_of": None,
            "sections": (),
            "evidence_citations": (),
            "lesson_citations": (),
            "notice": {
                "not_ready": NOTICE_NOT_READY,
                "not_supported": NOTICE_NOT_SUPPORTED,
                "unavailable": NOTICE_UNAVAILABLE,
            }[availability],
        }
    )


def _visible(
    claim: FeedbackClaim,
    policy: FeedbackVisibilityPolicy,
    terminal: bool,
    records: dict[object, _Record],
) -> bool:
    if claim.claim_id not in _PUBLIC_CLAIMS:
        return False
    if any(isinstance(records[identity], RetrievalEvidence) for identity in claim.evidence_ids):
        return False
    if claim.claim_id in {"compare-receiving-contract", "receiving-contract"}:
        # The why wording also contains an imperative comparison. Do not use
        # it as a hidden next-action/hint bypass when generic guidance is closed.
        return not terminal and "compare-receiving-contract" in policy.next_action_ids
    return True


def _retained_claims(
    claims: tuple[FeedbackClaim, ...],
    policy: FeedbackVisibilityPolicy,
    terminal: bool,
    records: dict[object, _Record],
) -> tuple[FeedbackClaim, ...]:
    kept = {claim.claim_id: claim for claim in claims if _visible(claim, policy, terminal, records)}
    # Remove dependent conclusions as whole claims, rather than deleting a
    # citation and leaving an implication that its supporting parent was public.
    dependencies = {
        "receiving-contract": {"verification-passed", "verification-failed"},
        "observed-recovery": {"verification-passed"},
        "tasks-transfer-result": {"verification-passed"},
    }
    for identity, alternatives in dependencies.items():
        if identity in kept and not alternatives.intersection(kept):
            del kept[identity]
    return tuple(claim for claim in claims if claim.claim_id in kept)


def project_public_feedback(
    released: ReleasedFeedbackResult,
    policy: FeedbackVisibilityPolicy,
) -> PublicFeedbackReply:
    """No repository/provider calls, clock reads, hidden lookups or persistence.

    Only the secure orchestration facade obtains these internal service values.
    Revalidating a typed value is not a substitute for fresh authorization;
    public clients are never permitted to supply a release envelope or policy.
    """
    if not isinstance(released, ReleasedFeedbackResult) or not isinstance(
        policy, FeedbackVisibilityPolicy
    ):
        raise ValueError("Public projection requires typed internal release and policy values")
    checked = ReleasedFeedbackResult.model_validate(released.model_dump(warnings=False))
    visibility = FeedbackVisibilityPolicy.model_validate(policy.model_dump(warnings=False))
    envelope = checked.envelope
    if envelope.scope != visibility.scope:
        raise ValueError("The visibility scope differs from the authorized evaluation")
    terminal = envelope.session.state in {"completed", "abandoned"}
    if (
        envelope.authorization.mode not in visibility.scope.allowed_modes
        or visibility.approval_reference is None
        or (terminal and not visibility.scope.allow_terminal_reflection)
    ):
        return _empty(checked, visibility, "not_supported")
    if envelope.availability == "not_ready":
        return _empty(checked, visibility, "not_ready")
    if envelope.availability == "not_supported":
        return _empty(checked, visibility, "not_supported")
    if envelope.availability == "unavailable":
        return _empty(checked, visibility, "unavailable")
    reply, plan, evidence, pin, content = (
        checked.reply,
        envelope.plan,
        envelope.evidence,
        envelope.lesson,
        envelope.public_content,
    )
    if reply is None or plan is None or evidence is None or pin is None or content is None:
        return _empty(checked, visibility, "unavailable")
    if reply.delivery == "mock" and not visibility.allow_mock_delivery:
        # Explicitly forbidding mock delivery never silently converts that
        # selected output into a supposedly approved production response.
        return _empty(checked, visibility, "unavailable")
    canonical_records: tuple[_Record, ...] = (
        *evidence.observations,
        *evidence.hint_events,
        *evidence.retrieval_events,
    )
    records: dict[object, _Record] = {item.id: item for item in canonical_records}
    kept = _retained_claims(plan.claims, visibility, terminal, records)
    used_evidence = {identity for claim in kept for identity in claim.evidence_ids}
    used_lesson = {field for claim in kept for field in claim.lesson_reference_ids}
    ordered_evidence = sorted(
        (records[identity] for identity in used_evidence),
        key=lambda item: (item.occurred_at, str(item.id)),
    )
    evidence_aliases = {item.id: f"e{index}" for index, item in enumerate(ordered_evidence, 1)}
    ordered_lesson = [field for field in _FIELDS if field in used_lesson]
    lesson_aliases = {field: f"l{index}" for index, field in enumerate(ordered_lesson, 1)}
    statements = {item.claim_id: item for section in reply.sections for item in section.items}
    sections = []
    for kind in ("demonstrated", "needs_improvement", "why", "next"):
        items = []
        for claim in kept:
            if claim.section != kind:
                continue
            items.append(
                PublicFeedbackStatement.model_validate(
                    {
                        "role": {
                            "fact": "observation",
                            "limitation": "limitation",
                            "next_step": "next_action",
                        }[claim.role],
                        "text": statements[claim.claim_id].text,
                        "evidence_aliases": tuple(
                            evidence_aliases[identity] for identity in claim.evidence_ids
                        ),
                        "lesson_aliases": tuple(
                            lesson_aliases[field] for field in claim.lesson_reference_ids
                        ),
                    }
                )
            )
        if items:
            sections.append(
                PublicFeedbackSection.model_validate({"kind": kind, "items": tuple(items)})
            )
    lesson = PublicLessonIdentity(
        lesson_id=pin.lesson_id,
        version=pin.version,
        public_content_sha256=public_content_sha256(content),
    )
    citations = []
    for item in ordered_evidence:
        if isinstance(item, RetrievalEvidence):
            # Defensive: no recall source has an approved citation description.
            return _empty(checked, visibility, "unavailable")
        checks = (
            tuple(
                PublicVerificationCheck.model_validate(
                    {"code": check.code, "matched": check.matched}
                )
                for check in item.checks
                if check.code in _CHECKS
            )
            if isinstance(item, EngineeringObservation)
            else ()
        )
        citations.append(
            PublicEvidenceCitation.model_validate(
                {
                    "alias": evidence_aliases[item.id],
                    "description": _DESCRIPTIONS[item.event_type],
                    "occurred_at": item.occurred_at,
                    "checks": checks,
                }
            )
        )
    lesson_citations = tuple(
        PublicLessonCitation.model_validate(
            {
                "alias": lesson_aliases[field],
                "lesson": lesson,
                "field": field,
                "label": LESSON_LABELS[field],
                "sha256": hashlib.sha256(getattr(content, field).encode("utf-8")).hexdigest(),
            }
        )
        for field in ordered_lesson
    )
    has_fact = any(
        claim.role == "fact"
        and claim.competency is not None
        and any(
            isinstance(records[identity], EngineeringObservation) for identity in claim.evidence_ids
        )
        for claim in kept
    )
    state = public_grounding_state(reply.state, has_fact)
    return PublicFeedbackReply.model_validate(
        {
            "policy_version": visibility.policy_version,
            "availability": "available",
            "feedback_state": state,
            "delivery_state": reply.delivery,
            "session_id": envelope.session.session_id,
            "lesson": lesson,
            "as_of": envelope.cutoff,
            "sections": tuple(sections),
            "evidence_citations": tuple(citations),
            "lesson_citations": lesson_citations,
            "notice": NOTICE_INSUFFICIENT
            if state == "insufficient_evidence"
            else NOTICE_MOCK
            if reply.delivery == "mock"
            else NOTICE_DETERMINISTIC,
        }
    )


def validate_public_projection(
    released: ReleasedFeedbackResult,
    policy: FeedbackVisibilityPolicy,
    reply: PublicFeedbackReply,
) -> PublicFeedbackReply:
    """Exact regeneration binds aliases, text, checks and digests to this response."""
    if not isinstance(reply, PublicFeedbackReply):
        raise ValueError("A public feedback projection must be a typed public value")
    checked = PublicFeedbackReply.model_validate(reply.model_dump(warnings=False))
    if checked != project_public_feedback(released, policy):
        raise ValueError("Public feedback does not match the authorized projection")
    return checked
