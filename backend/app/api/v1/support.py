"""Authenticated public-document retrieval; never learner/account inspection by an LLM."""

import hashlib
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request

from app.ai.observability import record_ai_delivery
from app.ai.support_diagnostics import observe_support, support_logger_observer
from app.api.dependencies import (
    current_account,
    get_account_service,
    get_http_support_service,
    get_knowledge_service,
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
from app.services.knowledge import KnowledgeGovernanceService
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
    knowledge: Annotated[KnowledgeGovernanceService, Depends(get_knowledge_service)],
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
    observer = support_logger_observer(
        request.app.state.logger, request_id=getattr(request.state, "request_id", None)
    )

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
        durable = request.app.state.accounting_settings.mode == "durable"
        if result.response.status == "answered" and (
            durable or request.app.state.settings.environment == "production"
        ):
            try:
                knowledge.authorize_release(
                    result,
                    actor=AuthenticatedAccount(fresh, auth.identity),
                    request_id=request.state.request_id,
                    retrieval_profile=result.retrieval_profile,
                    index_sha256=result.index_sha256,
                )
            except LearningError as error:
                if error.code in {"unauthenticated", "forbidden"}:
                    observe_support(
                        observer, "release", "unauthorized", len(result.response.references)
                    )
                    raise
                observe_support(observer, "release", "unavailable", len(result.response.references))
                raise ApplicationError(
                    "dependency_unavailable", "Support sources are unavailable.", 503
                ) from None
            except Exception:
                observe_support(observer, "release", "failed", len(result.response.references))
                raise ApplicationError(
                    "dependency_unavailable", "Support is unavailable.", 503
                ) from None
            observe_support(observer, "release", "authorized", len(result.response.references))
        return result

    result = await operations.execute_account(auth.account.id, operation, deadline=deadline)
    receipt = result.safe_receipt()
    if receipt is not None:
        request.app.state.logger.info(
            "support_answer_released",
            extra={"request_id": request.state.request_id, "support_provenance": receipt},
        )
    record_ai_delivery(
        request.app.state.logger,
        family="support",
        status=result.response.status,
        source=result.response.source,
    )
    return result.response
