"""Repository contract and records for learner-requested lessons (implementation: app.db)."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from app.schemas.custom_lessons import (
    AnswerResult,
    CustomLessonList,
    CustomLessonRequestView,
    CustomLessonView,
)


@dataclass(frozen=True)
class RequestFields:
    topic: str
    language: str
    framework: str | None
    level: str
    goal: str
    lesson_count: int
    practice_styles: tuple[str, ...]


@dataclass(frozen=True)
class CreateOutcome:
    kind: Literal["created", "replayed", "conflict", "rate_limited", "quota"]
    view: CustomLessonRequestView | None = None


@dataclass(frozen=True)
class GenerationJob:
    account_id: UUID
    fields: RequestFields


@dataclass(frozen=True)
class LessonContent:
    title: str
    objective: str
    sections: list[dict[str, str]]
    challenges: list[dict[str, object]]


@dataclass(frozen=True)
class AnswerOutcome:
    kind: Literal["ok", "not_found", "conflict", "invalid_option", "missing_text"]
    result: AnswerResult | None = None


class CustomLessonRepository(Protocol):
    def create_request(
        self,
        account_id: UUID,
        key: str,
        digest: str,
        fields: RequestFields,
        now: datetime,
        *,
        per_minute: int,
        per_day: int,
    ) -> CreateOutcome: ...

    def get_request(
        self, account_id: UUID, request_id: UUID, now: datetime, stale_after: timedelta
    ) -> CustomLessonRequestView | None: ...

    def cancel_request(
        self, account_id: UUID, request_id: UUID, now: datetime
    ) -> CustomLessonRequestView | None: ...

    def recover_interrupted(self, now: datetime) -> int: ...

    def start_generation(self, request_id: UUID, now: datetime) -> GenerationJob | None: ...

    def status(self, request_id: UUID) -> str | None: ...

    def finish(self, request_id: UUID, status: str, code: str | None, now: datetime) -> None: ...

    def save_lesson(
        self,
        request_id: UUID,
        job: GenerationJob,
        position: int,
        content: LessonContent,
        now: datetime,
    ) -> bool: ...

    def list_lessons(self, account_id: UUID) -> CustomLessonList: ...

    def get_lesson(self, account_id: UUID, lesson_id: UUID) -> CustomLessonView | None: ...

    def delete_lesson(self, account_id: UUID, lesson_id: UUID) -> bool: ...

    def answer(
        self,
        account_id: UUID,
        lesson_id: UUID,
        challenge_id: UUID,
        key: str,
        digest: str,
        selected_option: int | None,
        text: str | None,
        now: datetime,
    ) -> AnswerOutcome: ...
