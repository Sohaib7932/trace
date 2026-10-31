from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response

from app.api.dependencies import current_account, get_account_service, require_write_origin
from app.domain.accounts import AuthenticatedAccount
from app.schemas.accounts import AccountLearnerResponse, AccountResponse, ClaimResponse
from app.schemas.errors import ErrorResponse
from app.schemas.learning import Contract
from app.services.accounts import AccountService
from app.services.identity import COOKIE_NAME, COOKIE_PATH

router = APIRouter(
    prefix="/api/v1/account",
    tags=["account"],
    dependencies=[Depends(require_write_origin)],
    responses={code: {"model": ErrorResponse} for code in (401, 403, 409, 422, 429, 503)},
)
Auth = Annotated[AuthenticatedAccount, Depends(current_account)]
Accounts = Annotated[AccountService, Depends(get_account_service)]


@router.get("/me", response_model=AccountResponse, operation_id="get_account")
def me(auth: Auth, service: Accounts, request: Request) -> AccountResponse:
    service.limit(auth.account, "inspect")
    status = service.status(auth.account, request.cookies.get(COOKIE_NAME))
    return AccountResponse(
        user_id=auth.account.id,
        created_at=auth.account.created_at,
        status=auth.account.status,
        roles=list(auth.account.roles),
        learner_id=status.learner_id,
        anonymous_history_available=status.anonymous_history_available,
    )


@router.get(
    "/me/learner", response_model=AccountLearnerResponse, operation_id="get_account_learner"
)
def learner(auth: Auth, service: Accounts) -> AccountLearnerResponse:
    service.limit(auth.account, "inspect")
    return AccountLearnerResponse(learner_id=service.status(auth.account, None).learner_id)


@router.post("/claim-anonymous", response_model=ClaimResponse, operation_id="claim_anonymous")
def claim(
    auth: Auth,
    service: Accounts,
    request: Request,
    response: Response,
    body: Contract,
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> ClaimResponse:
    learner_id = service.claim(auth.account, request.cookies.get(COOKIE_NAME), str(key))
    response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH, httponly=True, samesite="lax")
    return ClaimResponse(learner_id=learner_id, claimed=True)
