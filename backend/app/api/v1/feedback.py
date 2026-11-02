"""Account-authenticated evidence feedback, separate from legacy learner hints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import (
    current_account,
    current_learner,
    get_feedback_operations,
    get_http_learner_feedback_service,
    require_write_origin,
)
from app.core.errors import ApplicationError
from app.domain.accounts import Principal
from app.schemas.errors import ErrorResponse
from app.schemas.learning import Contract
from app.schemas.public_feedback import PublicFeedbackReply
from app.services.feedback_operations import FeedbackOperations
from app.services.learner_feedback import LearnerFeedbackService

router = APIRouter(
    prefix="/api/v1",
    tags=["feedback"],
    dependencies=[Depends(require_write_origin), Depends(current_account)],
    responses={
        code: {"model": ErrorResponse}
        for code in (401, 403, 404, 409, 413, 422, 429, 500, 503, 504)
    },
)


@router.post(
    "/sessions/{session_id}/feedback",
    response_model=PublicFeedbackReply,
    operation_id="get_session_feedback",
)
async def feedback(
    session_id: UUID,
    body: Contract,
    request: Request,
    owner: Annotated[Principal, Depends(current_learner)],
    service: Annotated[LearnerFeedbackService, Depends(get_http_learner_feedback_service)],
    operations: Annotated[FeedbackOperations, Depends(get_feedback_operations)],
) -> PublicFeedbackReply:
    """Build feedback from owned backend evidence; clients provide no facts.

    This read-only POST recomputes the current authorized projection. It does
    not create an assignment, alter an attempt or accept an evaluator result.
    The worker owns its permit until synchronous work actually finishes even
    if its HTTP waiter reaches the request deadline or disconnects.
    """
    deadline = getattr(request.state, "feedback_deadline", None)
    if not isinstance(deadline, float):
        raise ApplicationError("dependency_unavailable", "Feedback is unavailable.", 503)
    return await operations.execute(
        owner, lambda: service.feedback(owner, session_id), deadline=deadline
    )
