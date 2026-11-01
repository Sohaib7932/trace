"""Explicit deterministic development fixture, never an automatic live fallback."""

from app.schemas.lesson_assistant import LessonAssistantReply, LessonAssistantRequest


class FakeLessonAssistant:
    def answer(self, request: LessonAssistantRequest) -> LessonAssistantReply:
        level = request.hint_level or 1
        hints = (
            "Trace the request data from the sender to the receiving FastAPI schema.",
            "Compare the outgoing JSON keys and their nesting with the public receiving schema.",
            "Use the visible validation error to locate a missing field or unexpected JSON level.",
        )
        return LessonAssistantReply(status="answered", text=hints[level - 1], source="test_fixture")
