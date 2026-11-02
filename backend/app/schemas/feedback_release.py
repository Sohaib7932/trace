"""Internal, read-authorized feedback evaluations; never wire credentials."""

import hashlib
import json
from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, StrictBool, StrictInt, field_validator, model_validator

from app.domain.lesson_spec.fields import Digest, Items, Value
from app.schemas.engineering_evidence import EngineeringEvidenceBatch, LessonPin
from app.schemas.evidence_feedback import FeedbackReply, FeedbackRequest
from app.schemas.learner_evidence import UTCInstant
from app.schemas.lesson_assistant import PublicLessonContent

type AuthenticationMode = Literal["account", "guest"]
type ReleaseAvailability = Literal["evaluated", "not_ready", "not_supported", "unavailable"]
type ReleaseSessionState = Literal[
    "awaiting_prediction",
    "ready_for_attempt",
    "verification_pending",
    "needs_revision",
    "completed",
    "abandoned",
]


def _canonical(value: object) -> object:
    if isinstance(value, BaseModel):
        return _canonical(value.model_dump(warnings=False))
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        from app.domain.clock import as_utc

        return as_utc(value).isoformat(timespec="microseconds")
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("Feedback fingerprints require string object keys")
        return {key: _canonical(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(child) for child in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    raise ValueError("Unsupported feedback fingerprint value")


def feedback_release_digest(value: object) -> str:
    """UTF-8 JSON, sorted keys, compact separators, UTC microsecond timestamps.

    Arrays must already be in canonical source-identity order. Raw private
    source fields may be hashed transiently; only their digest is retained.
    """
    encoded = json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fresh(value: object) -> object:
    if isinstance(value, BaseModel):
        return _fresh(value.model_dump(warnings=False))
    if isinstance(value, dict):
        return {key: _fresh(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return tuple(_fresh(child) for child in value)
    return value


class FreshAuthorization(Value):
    schema_version: Literal["feedback-authorization-v1"] = "feedback-authorization-v1"
    mode: AuthenticationMode
    learner_id: UUID = Field(repr=False)
    principal_expires_at: UTCInstant
    valid_until: UTCInstant
    account_id: UUID | None = Field(repr=False)
    credential_id: UUID | None = Field(repr=False)
    identity_fingerprint: Digest = Field(repr=False)
    observed_at: UTCInstant

    @model_validator(mode="after")
    def exact_mode(self) -> Self:
        if not self.observed_at < self.valid_until <= self.principal_expires_at:
            raise ValueError("Authorization must be unexpired when observed")
        if (self.account_id is not None, self.credential_id is not None) != (
            self.mode == "account",
            self.mode == "guest",
        ):
            raise ValueError("Authorization must use exactly one authentication mode")
        return self

    def identity(self) -> dict[str, object]:
        return self.model_dump(exclude={"observed_at", "valid_until"})


class FeedbackReleaseScope(Value):
    schema_version: Literal["feedback-release-scope-v1"] = "feedback-release-scope-v1"
    allowed_modes: Items[AuthenticationMode] = Field(max_length=2)
    allow_terminal_reflection: StrictBool

    @model_validator(mode="after")
    def unique_modes(self) -> Self:
        if len(self.allowed_modes) != len(set(self.allowed_modes)):
            raise ValueError("Authentication modes cannot be repeated")
        return self

    @classmethod
    def disabled(cls) -> Self:
        return cls(allowed_modes=(), allow_terminal_reflection=False)


class ReleaseSession(Value):
    session_id: UUID
    owner_learner_id: UUID = Field(repr=False)
    lesson_version_id: UUID = Field(repr=False)
    state: ReleaseSessionState
    created_at: UTCInstant
    completed_at: UTCInstant | None


class SelectedAttempt(Value):
    attempt_id: UUID
    number: StrictInt = Field(ge=1)
    created_at: UTCInstant


class SelectedRun(Value):
    run_id: UUID
    attempt_id: UUID
    status: Literal["pending", "passed", "failed", "error"]
    created_at: UTCInstant
    completed_at: UTCInstant | None

    @model_validator(mode="after")
    def finalization(self) -> Self:
        if (self.status == "pending") != (self.completed_at is None):
            raise ValueError("Run finalization must match its current status")
        if self.completed_at is not None and self.completed_at < self.created_at:
            raise ValueError("A run cannot finish before it was created")
        return self


class FeedbackEvaluationEnvelope(Value):
    schema_version: Literal["feedback-evaluation-v1"] = "feedback-evaluation-v1"
    policy_version: Literal["evidence-feedback-policy-v1"] = "evidence-feedback-policy-v1"
    request_id: UUID
    authorization: FreshAuthorization = Field(repr=False)
    scope: FeedbackReleaseScope
    scope_fingerprint: Digest
    session: ReleaseSession
    lesson: LessonPin | None = Field(repr=False)
    public_content: PublicLessonContent | None = Field(repr=False)
    cutoff: UTCInstant
    availability: ReleaseAvailability
    evidence: EngineeringEvidenceBatch | None = Field(repr=False)
    plan: FeedbackRequest | None = Field(repr=False)
    source_fingerprint: Digest = Field(repr=False)
    cohort_fingerprint: Digest | None = Field(repr=False)
    selected_attempt: SelectedAttempt | None
    selected_run: SelectedRun | None
    envelope_fingerprint: Digest = Field(repr=False)

    @field_validator(
        "authorization",
        "scope",
        "session",
        "lesson",
        "public_content",
        "evidence",
        "plan",
        "selected_attempt",
        "selected_run",
        mode="before",
    )
    @classmethod
    def refresh_values(cls, value: object) -> object:
        return _fresh(value)

    @model_validator(mode="after")
    def bindings(self) -> Self:
        if self.scope_fingerprint != feedback_release_digest(self.scope):
            raise ValueError("Evaluation scope fingerprint does not match")
        if self.authorization.learner_id != self.session.owner_learner_id:
            raise ValueError("Evaluation owner does not match its authorization")
        if self.cutoff != self.authorization.observed_at:
            raise ValueError("Evaluation cutoff must come from initial authorization")
        if self.lesson is not None and self.lesson.version_id != self.session.lesson_version_id:
            raise ValueError("Evaluation lesson does not match its session pin")
        if (self.lesson is None) != (self.public_content is None):
            raise ValueError("A supported lesson requires its exact public content")
        if self.evidence is None:
            if self.cohort_fingerprint is not None:
                raise ValueError("Unevaluated history has no cohort digest")
        else:
            query = self.evidence.query
            if (
                query.owner_learner_id != self.authorization.learner_id
                or query.session_id != self.session.session_id
                or query.start_at != self.session.created_at
                or query.end_at != self.cutoff
                or query.as_of != self.cutoff
                or query.max_records != 64
                or self.evidence.lesson != self.lesson
                or self.cohort_fingerprint != feedback_release_digest(self.evidence)
            ):
                raise ValueError("Evaluation cohort does not match its server-owned scope")
        if self.availability == "evaluated":
            if self.plan is None or self.evidence is None or self.public_content is None:
                raise ValueError("Evaluated feedback requires its actual canonical plan")
            from app.services.evidence_feedback_policy import build_feedback_request

            expected_plan = build_feedback_request(
                self.request_id, self.evidence, self.public_content
            )
            if self.plan != expected_plan:
                raise ValueError(
                    "Evaluation claims must come from the deterministic feedback policy"
                )
            if (
                self.plan.request_id != self.request_id
                or self.plan.evidence != self.evidence
                or self.plan.policy_version != self.policy_version
                or any(
                    ref.text != getattr(self.public_content, ref.reference_id)
                    for ref in self.plan.lesson_references
                )
            ):
                raise ValueError("Evaluation plan does not match its canonical cohort")
        elif self.plan is not None:
            raise ValueError("Unevaluated feedback must not contain a provider plan")
        if self.plan is not None:
            self._selected_bindings()
        if self.availability in {"not_ready", "not_supported"} and self.evidence is not None:
            raise ValueError("Closed visibility gates must not calculate evidence correctness")
        if self.selected_attempt is not None and self.selected_attempt.created_at >= self.cutoff:
            raise ValueError("A selected attempt must precede the server cutoff")
        if self.selected_run is not None and (
            self.selected_attempt is None
            or self.selected_run.attempt_id != self.selected_attempt.attempt_id
        ):
            raise ValueError("Selected verification must belong to the selected attempt")
        if self.envelope_fingerprint != feedback_release_digest(
            self.model_dump(exclude={"envelope_fingerprint"}, warnings=False)
        ):
            raise ValueError("Evaluation envelope fingerprint does not match")
        return self

    def _selected_bindings(self) -> None:
        plan, attempt = self.plan, self.selected_attempt
        assert plan is not None
        if (
            attempt is None
            or plan.focus is None
            or plan.focus.kind != "attempt"
            or plan.focus.record_id != attempt.attempt_id
        ):
            raise ValueError("Evaluated feedback must bind its selected attempt")
        modifications = [
            item
            for item in plan.evidence.observations
            if item.event_type == "modification_submitted"
            and item.source.record_id == attempt.attempt_id
        ]
        if len(modifications) != 1 or modifications[0].occurred_at != attempt.created_at:
            raise ValueError("Selected attempt must match its canonical submission")
        cited = {
            identity
            for claim in plan.claims
            if claim.claim_id
            in {"verification-passed", "verification-failed", "verification-unavailable"}
            for identity in claim.evidence_ids
        }
        verifications = [
            item
            for item in plan.evidence.observations
            if item.id in cited and item.event_type == "verification_finished"
        ]
        run = self.selected_run
        if verifications:
            if len(verifications) != 1 or run is None:
                raise ValueError("Selected run must match its canonical verification")
            observed = verifications[0]
            if (
                observed.source.record_id != run.run_id
                or observed.occurred_at != run.completed_at
                or {"passed": "success", "failed": "failure", "error": "unavailable"}.get(
                    run.status
                )
                != observed.outcome
            ):
                raise ValueError("Selected run state must match the observed verification")
        elif run is not None and run.completed_at is not None and run.completed_at < self.cutoff:
            raise ValueError("A finished in-cohort run requires its canonical observation")


class ReleasedFeedbackResult(Value):
    """An internal service result, not a client-accepted authorization token.

    Fingerprints detect accidental/forged typed-value mutation. They do not turn
    arbitrary client objects into trusted database provenance or credentials.
    """

    schema_version: Literal["released-feedback-v1"] = "released-feedback-v1"
    envelope: FeedbackEvaluationEnvelope = Field(repr=False)
    reply: FeedbackReply | None = Field(repr=False)
    released_authorization: FreshAuthorization = Field(repr=False)
    released_at: UTCInstant
    release_fingerprint: Digest = Field(repr=False)

    @field_validator("envelope", "reply", "released_authorization", mode="before")
    @classmethod
    def refresh_values(cls, value: object) -> object:
        return _fresh(value)

    @model_validator(mode="after")
    def released_bindings(self) -> Self:
        if (
            self.released_authorization.identity() != self.envelope.authorization.identity()
            or self.released_authorization.observed_at < self.envelope.cutoff
            or self.released_at < self.released_authorization.observed_at
            or self.released_at >= self.released_authorization.valid_until
        ):
            raise ValueError("Release authorization does not match its evaluated identity")
        if self.envelope.availability in {"not_ready", "not_supported"}:
            if self.reply is not None:
                raise ValueError("Closed visibility gates cannot contain feedback")
        elif self.reply is None or (
            self.reply.request_id != self.envelope.request_id
            or self.reply.session_id != self.envelope.session.session_id
        ):
            raise ValueError("Released reply does not match its evaluation")
        elif self.envelope.availability == "unavailable":
            if self.reply.state != "unavailable":
                raise ValueError("Unavailable sources cannot produce feedback conclusions")
        else:
            self._validate_reply()
        if self.release_fingerprint != feedback_release_digest(
            self.model_dump(exclude={"release_fingerprint"}, warnings=False)
        ):
            raise ValueError("Released result fingerprint does not match")
        return self

    def _validate_reply(self) -> None:
        from app.services.evidence_feedback_validation import render_feedback

        plan, reply = self.envelope.plan, self.reply
        assert plan is not None and reply is not None
        expected = render_feedback(plan)
        if any(
            getattr(reply, field) != getattr(expected, field)
            for field in (
                "schema_version",
                "policy_version",
                "request_id",
                "session_id",
                "lesson",
                "state",
                "evidence_references",
                "lesson_references",
                "coverage_references",
            )
        ):
            raise ValueError("Released feedback changed its canonical facts or references")
        actual = {
            item.claim_id: (section.kind, item)
            for section in reply.sections
            for item in section.items
        }
        if actual.keys() != {claim.claim_id for claim in plan.claims}:
            raise ValueError("Released feedback must preserve all original authorized claims")
        for claim in plan.claims:
            section, item = actual[claim.claim_id]
            if (
                section != claim.section
                or item.role != claim.role
                or item.text not in {wording.text for wording in claim.wordings}
                or item.evidence_ids != claim.evidence_ids
                or item.lesson_reference_ids != claim.lesson_reference_ids
                or item.coverage_refs != claim.coverage_refs
            ):
                raise ValueError("Released feedback contains an unauthorized statement")
