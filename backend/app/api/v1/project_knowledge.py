"""Authenticated repository ingestion and questions using existing GitHub admission."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.dependencies import require_write_origin
from app.api.v1.github_projects import Accounts, Actor, run
from app.schemas.errors import ErrorResponse
from app.schemas.github_projects import CommitSha, SnapshotCreate
from app.schemas.project_knowledge import RepositoryKnowledgeSnapshot
from app.schemas.project_questions import ProjectQuestionAnswer, ProjectQuestionCreate
from app.services.project_knowledge import ProjectKnowledgeService

router = APIRouter(
    prefix="/api/v1/projects/github/repositories",
    tags=["project learning"],
    dependencies=[Depends(require_write_origin)],
    responses={
        code: {"model": ErrorResponse}
        for code in (401, 403, 404, 409, 413, 422, 429, 500, 503, 504)
    },
)


def service(request: Request) -> ProjectKnowledgeService:
    return cast(ProjectKnowledgeService, request.app.state.project_knowledge)


@router.post("/{connection_id}/ingest", response_model=RepositoryKnowledgeSnapshot)
async def ingest_repository(
    connection_id: UUID,
    body: SnapshotCreate,
    request: Request,
    response: Response,
    actor: Actor,
    accounts: Accounts,
) -> RepositoryKnowledgeSnapshot:
    return await run(
        request,
        response,
        actor,
        accounts,
        lambda: service(request).ingest(actor.account.id, connection_id, body.commit_sha),
    )


@router.get("/{connection_id}/knowledge", response_model=RepositoryKnowledgeSnapshot)
async def repository_knowledge(
    connection_id: UUID,
    request: Request,
    response: Response,
    actor: Actor,
    accounts: Accounts,
    commit_sha: Annotated[CommitSha, Query()],
) -> RepositoryKnowledgeSnapshot:
    return await run(
        request,
        response,
        actor,
        accounts,
        lambda: service(request).knowledge(actor.account.id, connection_id, commit_sha),
    )


@router.post("/{connection_id}/ask", response_model=ProjectQuestionAnswer)
async def ask_repository(
    connection_id: UUID,
    body: ProjectQuestionCreate,
    request: Request,
    response: Response,
    actor: Actor,
    accounts: Accounts,
) -> ProjectQuestionAnswer:
    return await run(
        request,
        response,
        actor,
        accounts,
        lambda: service(request).ask(actor.account.id, connection_id, body),
    )
