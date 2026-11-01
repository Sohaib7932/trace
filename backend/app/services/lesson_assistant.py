"""Read-only assistance composition over already-authorized public learner data.

This internal service has no repository or identity capability. A future route must
authorize the owned session first and obtain these fields from its pinned public
projection. It must not pass LessonVersion, LessonSpecV1 or a whole progress record.
"""

from collections.abc import Mapping

from app.ai.lesson_assistant import LessonAssistant
from app.schemas.lesson_assistant import (
    LessonAssistantContext,
    LessonAssistantReply,
    LessonAssistantRequest,
    LessonStage,
    PublicLessonContent,
    SupportedLesson,
    VisibleEvidence,
)


def build_lesson_assistant_request(
    *,
    lesson_id: SupportedLesson,
    stage: LessonStage,
    public_content: Mapping[str, str],
    question: str,
    visible_attempt: str | None = None,
    evidence: tuple[VisibleEvidence, ...] = (),
    previous_hints: tuple[str, ...] = (),
    hint_level: int | None = None,
) -> LessonAssistantRequest:
    # Exact public schema rejects extra/private fields rather than silently dropping them.
    lesson = PublicLessonContent.model_validate(dict(public_content))
    return LessonAssistantRequest(
        context=LessonAssistantContext(
            lesson_id=lesson_id,
            stage=stage,
            lesson=lesson,
            visible_attempt=visible_attempt,
            evidence=evidence,
            previous_hints=previous_hints,
        ),
        question=question,
        hint_level=hint_level,
    )


def unavailable_assistance() -> LessonAssistantReply:
    return LessonAssistantReply(
        status="unavailable",
        text="Lesson assistance is unavailable. Continue using the lesson's visible evidence.",
        source="none",
    )


class LessonAssistantService:
    def __init__(self, assistant: LessonAssistant) -> None:
        self.assistant = assistant

    def answer(self, request: LessonAssistantRequest) -> LessonAssistantReply:
        # Refresh trust boundaries even if an internal caller used model_construct/model_copy.
        try:
            checked = LessonAssistantRequest.model_validate(
                request.model_dump(mode="json", warnings=False)
            )
            result = self.assistant.answer(checked)
            return LessonAssistantReply.model_validate(
                result.model_dump(mode="json", warnings=False)
            )
        except Exception:
            return unavailable_assistance()
