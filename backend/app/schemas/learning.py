from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class IdentityResponse(Contract):
    learner_id: UUID
    expires_at: datetime


class LessonResponse(Contract):
    id: str
    version_id: UUID
    version: str
    title: str
    objective: str
    scenario: str
    outgoing_code: str
    schema_code: str


class SessionCreate(Contract):
    lesson_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9-]+$")
    version: str = Field(default="1.0.0", max_length=32, pattern=r"^\d+\.\d+\.\d+$")


class SessionResponse(Contract):
    id: UUID
    lesson_version_id: UUID
    state: Literal[
        "awaiting_prediction",
        "ready_for_attempt",
        "verification_pending",
        "needs_revision",
        "completed",
        "abandoned",
    ]
    created_at: datetime
    completed_at: datetime | None


class PredictionCreate(Contract):
    selected_answer: Literal["rejected", "saved", "server_error"]
    reasoning: str = Field(min_length=1, max_length=2000)

    @field_validator("reasoning")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Explain your prediction.")
        return value


class PredictionResponse(PredictionCreate):
    id: UUID
    created_at: datetime


class AttemptCreate(Contract):
    change_type: Literal["rename_payload_field"]
    field_name: Literal["body", "content"]
    explanation: str = Field(default="", max_length=2000)


class AttemptResponse(Contract):
    id: UUID
    number: int
    change_type: Literal["rename_payload_field"] = "rename_payload_field"
    field_name: Literal["body", "content"]
    explanation: str
    hints_before: int
    created_at: datetime


class HintCreate(Contract):
    attempt_id: UUID | None = None


class HintResponse(Contract):
    id: UUID
    attempt_id: UUID | None
    sequence: int
    text: str | None
    status: Literal["delivered", "error"]
    provider: Literal["fake"]
    fixture: str
    prompt_version: str
    interaction_type: Literal["hint"]
    created_at: datetime


class CheckResponse(Contract):
    code: str
    matched: bool
    expected: str
    observed: str
    source: str
    created_at: datetime


class RunResponse(Contract):
    id: UUID
    attempt_id: UUID
    status: Literal["pending", "passed", "failed", "error"]
    feedback: str
    created_at: datetime
    completed_at: datetime | None
    checks: list[CheckResponse] = Field(default_factory=list)


class EventResponse(Contract):
    event_type: str
    reference_id: UUID | None
    created_at: datetime


class EvidenceSummary(Contract):
    attempt_count: int
    hint_request_count: int
    hints_delivered: int
    verification_errors: int
    prediction_correct: bool | None
    correct_after_revision: bool
    hint_assisted_correction: bool


class ProgressResponse(Contract):
    session: SessionResponse
    lesson: LessonResponse
    prediction: PredictionResponse | None
    attempts: list[AttemptResponse]
    hints: list[HintResponse]
    verifications: list[RunResponse]
    events: list[EventResponse]
    summary: EvidenceSummary
