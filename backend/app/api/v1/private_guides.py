"""Authenticated private instructional guides; no executable lesson assignment."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request

from app.ai.observability import record_ai_delivery
from app.api.dependencies import current_account, require_write_origin
from app.core.errors import ApplicationError
from app.domain.accounts import AuthenticatedAccount
from app.schemas.errors import ErrorResponse
from app.schemas.private_guides import GuideCreate, GuideDetail, GuideSummary
from app.services.feedback_operations import FeedbackOperations
from app.services.private_guides import PrivateGuideService

router = APIRouter(
    prefix="/api/v1/learning-guides",
    tags=["private-learning-guides"],
    responses={
        code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 413, 422, 429, 503, 504)
    },
)


def get_guide_service(request: Request) -> PrivateGuideService:
    service = getattr(request.app.state, "guide_service", None)
    if not isinstance(service, PrivateGuideService):
        raise ApplicationError("dependency_unavailable", "Private guides are unavailable.", 503)
    return service


@router.post(
    "",
    response_model=GuideDetail,
    status_code=201,
    operation_id="create_private_learning_guide",
    dependencies=[Depends(require_write_origin)],
)
async def create(
    body: GuideCreate,
    request: Request,
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
    auth: Annotated[AuthenticatedAccount, Depends(current_account)],
    service: Annotated[PrivateGuideService, Depends(get_guide_service)],
) -> GuideDetail:
    operations = getattr(request.app.state, "guide_operations", None)
    deadline = getattr(request.state, "guide_deadline", None)
    if not isinstance(operations, FeedbackOperations) or not isinstance(deadline, float):
        raise ApplicationError("dependency_unavailable", "Private guides are unavailable.", 503)
    result = await operations.execute_account(
        auth.account.id,
        lambda: service.create(auth, key, body),
        deadline=deadline,
    )
    if result.status != "generating":
        record_ai_delivery(
            request.app.state.logger,
            family="generation",
            status="success" if result.status == "ready" else "unavailable",
            source=result.source or "unavailable",
        )
    return result


@router.get(
    "", response_model=tuple[GuideSummary, ...], operation_id="list_private_learning_guides"
)
def list_guides(
    auth: Annotated[AuthenticatedAccount, Depends(current_account)],
    service: Annotated[PrivateGuideService, Depends(get_guide_service)],
) -> tuple[GuideSummary, ...]:
    return service.list(auth)


@router.get("/{guide_id}", response_model=GuideDetail, operation_id="get_private_learning_guide")
def get(
    guide_id: UUID,
    auth: Annotated[AuthenticatedAccount, Depends(current_account)],
    service: Annotated[PrivateGuideService, Depends(get_guide_service)],
) -> GuideDetail:
    return service.get(auth, guide_id)
