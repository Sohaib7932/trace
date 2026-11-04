"""Public contracts for learner-requested (custom) lessons.

Answer keys never appear in any response model here: they stay in the database and are
only used by the server-side answer check.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints

type Level = Literal["beginner", "intermediate", "advanced"]
type Goal = Literal["understand", "debug", "build"]
type ChallengeKind = Literal["predict_output", "find_bug", "multiple_choice", "explain"]
type GeneratedVerification = Literal["answer_key", "practice_only"]
ALL_KINDS: tuple[ChallengeKind, ...] = ("predict_output", "find_bug", "multiple_choice", "explain")
type RequestStatus = Literal["queued", "generating", "ready", "failed", "cancelled", "rejected"]

Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CustomLessonRequestCreate(Strict):
    topic: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=1000)]
    language: Short
    framework: Short | None = None
    level: Level = "beginner"
    goal: Goal = "understand"
    lesson_count: Annotated[StrictInt, Field(ge=1, le=3)] = 1
    practice_styles: Annotated[list[ChallengeKind], Field(min_length=1, max_length=4)] = Field(
        default_factory=lambda: list(ALL_KINDS)
    )


class CustomLessonRequestView(Strict):
    id: UUID
    status: RequestStatus
    error_code: str | None
    message: str | None = Field(description="Safe, learner-facing explanation for failed/rejected.")
    topic: str
    language: str
    framework: str | None
    level: Level
    lesson_count: int
    lessons_ready: int
    lesson_ids: list[UUID]
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class Section(Strict):
    heading: str
    body: str


class ChallengeView(Strict):
    id: UUID
    position: int
    kind: ChallengeKind
    prompt: str
    code: str | None
    options: list[str]
    hints: list[str]
    verification_mode: GeneratedVerification
    # Learner progress (from stored answers). Explanation only once answered.
    attempts: int
    answered_correctly: bool | None
    explanation: str | None


class CustomLessonSummary(Strict):
    id: UUID
    request_id: UUID
    position: int
    title: str
    objective: str
    language: str
    level: Level
    created_at: datetime
    challenge_count: int
    completed_challenges: int


class CustomLessonView(CustomLessonSummary):
    sections: list[Section]
    challenges: list[ChallengeView]
    next_lesson_id: UUID | None


class CustomLessonList(Strict):
    items: list[CustomLessonSummary]


class AnswerCreate(Strict):
    selected_option: Annotated[StrictInt, Field(ge=0, le=7)] | None = None
    text: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None


class AnswerResult(Strict):
    challenge_id: UUID
    verification_mode: GeneratedVerification
    # answer_key: true/false. practice_only: null (no automatic check).
    correct: bool | None
    explanation: str
    model_answer: str | None = Field(
        description="practice_only: an example answer to compare with; null for answer_key."
    )
    attempts: int


class LanguageView(Strict):
    id: str
    label: str
    frameworks: list[str]
    verification: GeneratedVerification
    note: str


class LanguageList(Strict):
    items: list[LanguageView]
    generation_available: bool
