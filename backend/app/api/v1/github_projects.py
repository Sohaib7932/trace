"""Authenticated GitHub App Project Learning; installation is not social login."""

from collections.abc import Callable
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi import Path as ApiPath

from app.api.dependencies import current_account, get_account_service, require_write_origin
from app.core.errors import ApplicationError
from app.domain.accounts import AuthenticatedAccount
from app.schemas.errors import ErrorResponse
from app.schemas.github_projects import (
    CommitSha,
    ConnectionView,
    InstallationComplete,
    InstallationStart,
    InstallationView,
    ProjectLearningPath,
    ProjectSnapshot,
    RepositoryChoice,
    RepositoryView,
    SnapshotCreate,
)
from app.services.accounts import AccountService
from app.services.feedback_operations import FeedbackOperations
from app.services.github_projects import GitHubProjectService

router = APIRouter(
    prefix="/api/v1/projects/github",
    tags=["project learning"],
    dependencies=[Depends(require_write_origin)],
    responses={
        code: {"model": ErrorResponse}
        for code in (401, 403, 404, 409, 413, 422, 429, 500, 503, 504)
    },
)
Actor = Annotated[AuthenticatedAccount, Depends(current_account)]
Accounts = Annotated[AccountService, Depends(get_account_service)]


def service(request: Request) -> GitHubProjectService:
    return cast(GitHubProjectService, request.app.state.github_projects)


async def run[T](
    request: Request,
    response: Response,
    actor: AuthenticatedAccount,
    accounts: AccountService,
    operation: Callable[[], T],
) -> T:
    actor.account.require_role("learner")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    operations = cast(FeedbackOperations, request.app.state.github_operations)

    def guarded() -> T:
        if request.app.state.clock() >= actor.identity.expires_at:
            raise ApplicationError("unauthenticated", "Sign in again.", 401)
        with service(request).client.deadline(operations.remaining_seconds(provider=False)):
            result = operation()
        if request.app.state.clock() >= actor.identity.expires_at:
            raise ApplicationError("unauthenticated", "Sign in again.", 401)
        fresh = accounts.bootstrap(actor.identity)
        fresh.require_role("learner")
        if fresh.id != actor.account.id:
            raise ApplicationError("unauthenticated", "Sign in again.", 401)
        return result

    # The root app installs this family's deadline middleware. Its bounded
    # operation retains admission until real network/provider work has stopped.
    deadline = getattr(request.state, "github_deadline", None)
    if not isinstance(deadline, float):
        raise ApplicationError("dependency_unavailable", "Project Learning is unavailable.", 503)
    return await operations.execute_account(actor.account.id, guarded, deadline=deadline)


@router.post("/installations/start", response_model=InstallationStart)
async def start_installation(
    request: Request,
    response: Response,
    actor: Actor,
    accounts: Accounts,
) -> InstallationStart:
    return await run(
        request, response, actor, accounts, lambda: service(request).start(actor.account.id)
    )


@router.post("/installations/complete", response_model=InstallationView)
async def complete_installation(
    body: InstallationComplete,
    request: Request,
    response: Response,
    actor: Actor,
    accounts: Accounts,
) -> InstallationView:
    return await run(
        request,
        response,
        actor,
        accounts,
        lambda: service(request).complete(actor.account.id, body),
    )


@router.get("/installations", response_model=list[InstallationView])
async def installations(
    request: Request,
    response: Response,
    actor: Actor,
    accounts: Accounts,
) -> tuple[InstallationView, ...]:
    return await run(
        request, response, actor, accounts, lambda: service(request).installations(actor.account.id)
    )


@router.get("/installations/{installation_id}/repositories", response_model=list[RepositoryView])
async def repositories(
    installation_id: Annotated[int, ApiPath(gt=0, le=2**63 - 1)],
    request: Request,
    response: Response,
    actor: Actor,
    accounts: Accounts,
) -> tuple[RepositoryView, ...]:
    return await run(
        request,
        response,
        actor,
        accounts,
        lambda: service(request).repositories(actor.account.id, installation_id),
    )


@router.post("/repositories", response_model=ConnectionView)
async def connect(
    body: RepositoryChoice,
    request: Request,
    response: Response,
    actor: Actor,
    accounts: Accounts,
) -> ConnectionView:
    return await run(
        request,
        response,
        actor,
        accounts,
        lambda: service(request).connect(
            actor.account.id, body.installation_id, body.repository_id
        ),
    )


@router.get("/repositories", response_model=list[ConnectionView])
async def connections(
    request: Request,
    response: Response,
    actor: Actor,
    accounts: Accounts,
) -> tuple[ConnectionView, ...]:
    return await run(
        request, response, actor, accounts, lambda: service(request).connections(actor.account.id)
    )


@router.post("/repositories/{connection_id}/sync", response_model=ProjectSnapshot)
async def sync(
    connection_id: UUID,
    body: SnapshotCreate,
    request: Request,
    response: Response,
    actor: Actor,
    accounts: Accounts,
) -> ProjectSnapshot:
    return await run(
        request,
        response,
        actor,
        accounts,
        lambda: service(request).sync(actor.account.id, connection_id, body.commit_sha),
    )


@router.get("/repositories/{connection_id}/snapshot", response_model=ProjectSnapshot)
async def snapshot(
    connection_id: UUID,
    request: Request,
    response: Response,
    actor: Actor,
    accounts: Accounts,
    commit_sha: Annotated[CommitSha, Query()],
) -> ProjectSnapshot:
    return await run(
        request,
        response,
        actor,
        accounts,
        lambda: service(request).snapshot(actor.account.id, connection_id, commit_sha),
    )


@router.post("/repositories/{connection_id}/learning-path", response_model=ProjectLearningPath)
async def learning_path(
    connection_id: UUID,
    body: SnapshotCreate,
    request: Request,
    response: Response,
    actor: Actor,
    accounts: Accounts,
) -> ProjectLearningPath:
    return await run(
        request,
        response,
        actor,
        accounts,
        lambda: service(request).learning_path(actor.account.id, connection_id, body.commit_sha),
    )
