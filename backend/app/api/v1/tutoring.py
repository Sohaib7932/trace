"""Account-only guidance; Gemini selects text and cannot grade or release solutions."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import (
    current_account,
    current_learner,
    get_lesson_tutoring_service,
    get_tutor_operations,
    require_write_origin,
)
from app.core.errors import ApplicationError
from app.domain.accounts import Principal
from app.schemas.errors import ErrorResponse
from app.schemas.lesson_assistant import LessonAssistantReply
from app.schemas.lesson_tutoring import TutorQuestionCreate
from app.services.feedback_operations import FeedbackOperations
from app.services.lesson_tutoring import LessonTutoringService

router = APIRouter(
    prefix="/api/v1",
    tags=["tutoring"],
    dependencies=[Depends(require_write_origin), Depends(current_account)],
    responses={
        code: {"model": ErrorResponse}
        for code in (401, 403, 404, 409, 413, 422, 429, 500, 503, 504)
    },
)


@router.post(
    "/sessions/{session_id}/tutor/ask",
    response_model=LessonAssistantReply,
    operation_id="ask_lesson_tutor",
)
async def ask(
    session_id: UUID,
    body: TutorQuestionCreate,
    request: Request,
    owner: Annotated[Principal, Depends(current_learner)],
    service: Annotated[LessonTutoringService, Depends(get_lesson_tutoring_service)],
    operations: Annotated[FeedbackOperations, Depends(get_tutor_operations)],
) -> LessonAssistantReply:
    """Read-only question over server-owned public context and approved guidance.

    No exchange persistence, live grading, full worked solution or hint-slot change.
    Gemini only selects an allowed topic; trusted code supplies the returned text.
    """
    deadline = getattr(request.state, "tutor_deadline", None)
    if not isinstance(deadline, float):
        raise ApplicationError("dependency_unavailable", "Tutor is unavailable.", 503)
    return await operations.execute(
        owner, lambda: service.answer(owner, session_id, body.question), deadline=deadline
    )
