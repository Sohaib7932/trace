from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.learning import Contract, SessionResponse


class CheckpointSummary(Contract):
    id: UUID
    transfer_session_id: UUID
    ordinal: int
    due_at: datetime
    completed_at: datetime | None
    status: Literal["upcoming", "due", "completed"]
    attempt_count: int


class PhaseResponse(Contract):
    lesson_id: str
    available: bool
    completed: bool
    sessions: list[SessionResponse]
    attempt_count: int


class JourneyResponse(Contract):
    server_time: datetime
    phases: list[PhaseResponse]
    checkpoints: list[CheckpointSummary]
    last_completed_at: datetime | None


class QuestionOption(Contract):
    id: Literal["a", "b", "c"]
    label: str


class RetrievalQuestionResponse(Contract):
    id: str
    title: str
    prompt: str
    payload: str
    schema_code: str
    options: list[QuestionOption]


class RetrievalAttemptCreate(Contract):
    selection: Literal["a", "b", "c"]
    reasoning: str = Field(default="", max_length=2000)


class RetrievalAttemptResponse(RetrievalAttemptCreate):
    id: UUID
    number: int
    correct: bool
    feedback: str
    created_at: datetime


class RetrievalResponse(Contract):
    checkpoint: CheckpointSummary
    server_time: datetime
    question: RetrievalQuestionResponse | None
    attempts: list[RetrievalAttemptResponse]
