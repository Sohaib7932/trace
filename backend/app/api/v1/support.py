"""Authenticated public-document retrieval; never learner/account inspection by an LLM."""

import hashlib
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import (
    current_account,
    get_account_service,
    get_http_support_service,
    get_support_operations,
    require_write_origin,
)
from app.core.errors import ApplicationError
from app.domain.accounts import AuthenticatedAccount
from app.domain.clock import Clock
from app.domain.learning import LearningError
from app.schemas.errors import ErrorResponse
from app.schemas.support import SupportQuestion, SupportResponse
from app.schemas.support_http import SupportAskCreate
from app.services.accounts import AccountService
from app.services.feedback_operations import FeedbackOperations
from app.services.support import SupportService
from app.support.receipts import VersionedSupportAnswer

router = APIRouter(
    prefix="/api/v1/support",
    tags=["support"],
    dependencies=[Depends(require_write_origin)],
    responses={code: {"model": ErrorResponse} for code in (401, 403, 413, 422, 429, 500, 503, 504)},
)


@router.post("/ask", response_model=SupportResponse, operation_id="ask_support")
async def ask(
    body: SupportAskCreate,
    request: Request,
    auth: Annotated[AuthenticatedAccount, Depends(current_account)],
    accounts: Annotated[AccountService, Depends(get_account_service)],
    service: Annotated[SupportService, Depends(get_http_support_service)],
    operations: Annotated[FeedbackOperations, Depends(get_support_operations)],
) -> SupportResponse:
    """Answer from approved public passages, with exact source quotations.

    No conversation persistence, account actions, source selection, arbitrary file
    ingestion or learner bootstrap. A draft/expired corpus remains unavailable.
    """
    clock = cast(Clock, request.app.state.clock)
    auth.account.require_role("learner")
    deadline = getattr(request.state, "support_deadline", None)
    if not isinstance(deadline, float):
        raise ApplicationError("dependency_unavailable", "Support is unavailable.", 503)

    def operation() -> VersionedSupportAnswer:
        if clock() >= auth.identity.expires_at:
            raise LearningError("unauthenticated", "Account authorization expired.")
        result = service.answer_with_provenance(
            SupportQuestion(question=body.question),
            subject="support:" + hashlib.sha256(str(auth.account.id).encode()).hexdigest(),
        )
        if clock() >= auth.identity.expires_at:
            raise LearningError("unauthenticated", "Account authorization expired.")
        fresh = accounts.bootstrap(auth.identity)
        fresh.require_role("learner")
        if fresh.id != auth.account.id:
            raise LearningError("unauthenticated", "Account authorization changed.")
        return result

    result = await operations.execute_account(auth.account.id, operation, deadline=deadline)
    receipt = result.safe_receipt()
    if receipt is not None:
        request.app.state.logger.info(
            "support_answer_released",
            extra={"request_id": request.state.request_id, "support_provenance": receipt},
        )
    return result.response
