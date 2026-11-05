from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.dependencies import current_account, get_account_service, get_leaderboard_service
from app.domain.accounts import AuthenticatedAccount
from app.schemas.errors import ErrorResponse
from app.schemas.leaderboard import LeaderboardResponse
from app.services.accounts import AccountService
from app.services.leaderboard import LeaderboardService

router = APIRouter(
    prefix="/api/v1/leaderboard",
    tags=["leaderboard"],
    responses={code: {"model": ErrorResponse} for code in (401, 403, 422, 429, 500, 503)},
)


@router.get("", response_model=LeaderboardResponse, operation_id="get_leaderboard")
def leaderboard(
    auth: Annotated[AuthenticatedAccount, Depends(current_account)],
    service: Annotated[LeaderboardService, Depends(get_leaderboard_service)],
    accounts: Annotated[AccountService, Depends(get_account_service)],
    response: Response,
    cursor: Annotated[str | None, Query(min_length=1, max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> LeaderboardResponse:
    """Global all-time distinct verified problems, for active registered learners.

    Competition ranks share ties (1, 1, 3); tied rows have a stable secondary order.
    Only completed sessions with passed server verification and all five matching
    evidence categories count. Repeated sessions and lesson versions count once per
    canonical lesson. AI practice and retrieval answers do not count.

    Only positive scores are visible. No public profile is stored, so names/avatars
    are null. Account, learner and provider identifiers and emails are never returned.
    Continuations retain a UTC cutoff for scores, registrations and history claims.
    Account disablement or role removal takes effect immediately, including on a
    continuation; restart pagination after such membership changes.
    """
    auth.account.require_role("learner")
    accounts.limit(auth.account, "leaderboard")
    result = service.page(auth.account, cursor, limit)
    response.headers["Cache-Control"] = "private, max-age=60"
    response.headers["Vary"] = "Authorization"
    return result
