"""Free-question port separate from the backwards-compatible TutorProvider."""

from typing import Protocol

from app.schemas.lesson_assistant import LessonAssistantReply, LessonAssistantRequest


class LessonAssistant(Protocol):
    def answer(self, request: LessonAssistantRequest) -> LessonAssistantReply: ...
