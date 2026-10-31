import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class LearningError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


class SessionState(StrEnum):
    AWAITING_PREDICTION = "awaiting_prediction"
    READY_FOR_ATTEMPT = "ready_for_attempt"
    VERIFICATION_PENDING = "verification_pending"
    NEEDS_REVISION = "needs_revision"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


def transition(state: str, target: SessionState, *, verified: bool = False) -> str:
    allowed = {
        SessionState.AWAITING_PREDICTION: {SessionState.READY_FOR_ATTEMPT},
        SessionState.READY_FOR_ATTEMPT: {SessionState.VERIFICATION_PENDING},
        SessionState.VERIFICATION_PENDING: {SessionState.NEEDS_REVISION, SessionState.COMPLETED},
        SessionState.NEEDS_REVISION: {SessionState.VERIFICATION_PENDING},
    }
    if target == SessionState.ABANDONED and state not in {
        SessionState.COMPLETED,
        SessionState.ABANDONED,
    }:
        return target.value
    if target not in allowed.get(SessionState(state), set()):
        raise LearningError("invalid_state", "This action is not available in the current state.")
    if target == SessionState.COMPLETED and not verified:
        raise LearningError("invalid_state", "Completion requires observed verification evidence.")
    return target.value


@dataclass(frozen=True)
class Credential:
    id: UUID
    learner_id: UUID
    expires_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True)
class LessonVersion:
    id: UUID
    lesson_id: str
    version: str
    public_content: dict[str, str]
    expected_field: str
    prediction_answer: str
    content_hash: str
    created_at: datetime


@dataclass(frozen=True)
class LearningSession:
    id: UUID
    learner_id: UUID
    lesson_version_id: UUID
    state: str
    idempotency_key: str
    created_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True)
class Prediction:
    id: UUID
    session_id: UUID
    selected_answer: str
    reasoning: str
    idempotency_key: str
    created_at: datetime


@dataclass(frozen=True)
class Attempt:
    id: UUID
    session_id: UUID
    number: int
    field_name: str
    explanation: str
    hints_before: int
    idempotency_key: str
    created_at: datetime


@dataclass(frozen=True)
class TutorInteraction:
    id: UUID
    session_id: UUID
    attempt_id: UUID | None
    sequence: int
    text: str | None
    status: str
    idempotency_key: str
    created_at: datetime
    provider: str = "fake"
    fixture: str = "fake-v1"
    prompt_version: str = "payload-mismatch-v1"
    interaction_type: str = "hint"


@dataclass(frozen=True)
class VerificationRun:
    id: UUID
    session_id: UUID
    attempt_id: UUID
    status: str
    idempotency_key: str
    created_at: datetime
    completed_at: datetime | None = None
    feedback: str = "Verification is pending."


@dataclass(frozen=True)
class VerificationCheck:
    id: UUID
    run_id: UUID
    code: str
    matched: bool
    expected: str
    observed: str
    source: str
    created_at: datetime


@dataclass(frozen=True)
class LearningEvent:
    id: UUID
    session_id: UUID
    event_type: str
    reference_id: UUID | None
    created_at: datetime


@dataclass(frozen=True)
class NoteSnapshot:
    id: UUID
    title: str
    content: str


@dataclass(frozen=True)
class Observation:
    http_status: int | None
    response_json: str
    validation_codes: tuple[str, ...]
    notes: tuple[NoteSnapshot, ...] | None
    response_note_id: str | None


@dataclass(frozen=True)
class Evaluation:
    status: str
    feedback: str


NOTE_TITLE = "Trace verification note"
NOTE_CONTENT = "Understanding request validation"


def response_matches_fixture(observation: Observation) -> bool:
    try:
        body = json.loads(observation.response_json)
    except (ValueError, TypeError):
        return False
    return (
        isinstance(body, dict)
        and observation.http_status == 201
        and not observation.validation_codes
        and observation.response_note_id is not None
        and body.get("id") == observation.response_note_id
        and body.get("title") == NOTE_TITLE
        and body.get("content") == NOTE_CONTENT
    )


def evaluate(field_name: str, expected_field: str, observation: Observation) -> Evaluation:
    """Only observed API + fresh-read facts can establish a successful correction."""
    rows = observation.notes
    correct_mapping = field_name == expected_field
    if observation.http_status is None or rows is None or observation.http_status >= 500:
        return Evaluation(
            "error", "The verification service failed. This is not a learner mistake."
        )
    if (
        not correct_mapping
        and observation.http_status == 422
        and not rows
        and {"missing:content", "extra_forbidden:body"} <= set(observation.validation_codes)
    ):
        return Evaluation("failed", "The receiving schema rejected the payload. No note was saved.")
    if correct_mapping and response_matches_fixture(observation) and len(rows) == 1:
        note = rows[0]
        if (
            note.title == NOTE_TITLE
            and note.content == NOTE_CONTENT
            and str(note.id) == observation.response_note_id
        ):
            return Evaluation(
                "passed", "The mapping matches the schema. A fresh read confirmed the saved note."
            )
    return Evaluation(
        "error",
        "The observed API and database evidence are inconsistent. No learner grade was assigned.",
    )
