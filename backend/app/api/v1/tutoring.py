"""Owned account-only guidance and optional conversational engineering advice."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import (
    current_account,
    current_learner,
    get_conversation_tutoring_service,
    get_lesson_tutoring_service,
    get_tutor_operations,
    require_write_origin,
)
from app.core.errors import ApplicationError
from app.domain.accounts import Principal
from app.schemas.conversation_tutor import ConversationTutorReply, TutorConversationCreate
from app.schemas.errors import ErrorResponse
from app.schemas.lesson_assistant import LessonAssistantReply
from app.schemas.lesson_tutoring import TutorQuestionCreate
from app.services.conversation_tutoring import ConversationTutoringService
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
    response_model=LessonAssistantReply | ConversationTutorReply,
    operation_id="ask_lesson_tutor",
)
async def ask(
    session_id: UUID,
    body: TutorQuestionCreate | TutorConversationCreate,
    request: Request,
    owner: Annotated[Principal, Depends(current_learner)],
    service: Annotated[LessonTutoringService, Depends(get_lesson_tutoring_service)],
    conversation: Annotated[
        ConversationTutoringService, Depends(get_conversation_tutoring_service)
    ],
    operations: Annotated[FeedbackOperations, Depends(get_tutor_operations)],
) -> LessonAssistantReply | ConversationTutorReply:
    """Read-only engineering advice over freshly authorized owned public context.

    Question-only requests retain the approved-guidance contract. Explicit
    mode=conversation allows free-form unexecuted advice and bounded untrusted
    page-session history. Neither mode grades, completes or consumes hint slots.
    """
    deadline = getattr(request.state, "tutor_deadline", None)
    if not isinstance(deadline, float):
        raise ApplicationError("dependency_unavailable", "Tutor is unavailable.", 503)
    if isinstance(body, TutorConversationCreate):
        return await operations.execute(
            owner, lambda: conversation.answer(owner, session_id, body), deadline=deadline
        )
    return await operations.execute(
        owner, lambda: service.answer(owner, session_id, body.question), deadline=deadline
    )
