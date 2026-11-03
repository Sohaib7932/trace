"""Server-selected, bounded derived indexing. Building an index never activates it."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field

from app.api.dependencies import get_knowledge_indexing_service, require_write_origin
from app.api.v1.knowledge_admin import current_admin, run_knowledge_operation
from app.domain.accounts import AuthenticatedAccount
from app.domain.lesson_spec.fields import Digest, Value, VersionId
from app.schemas.errors import ErrorResponse
from app.services.knowledge_indexing import KnowledgeIndexingService
from app.support.embedding_index import EmbeddingIndex

router = APIRouter(
    prefix="/api/v1/admin/knowledge",
    tags=["knowledge administration"],
    dependencies=[Depends(require_write_origin)],
    responses={
        code: {"model": ErrorResponse} for code in (401, 403, 409, 413, 422, 429, 500, 503, 504)
    },
)


class BuildKnowledgeIndex(Value):
    operation_key: VersionId


class KnowledgeIndexResult(Value):
    index_sha256: Digest
    manifest_sha256: Digest
    space_sha256: Digest
    passage_count: int = Field(ge=1, le=256)
    source: Literal["ai"] = "ai"
    retrieval_activated: Literal[False] = False


def _result(index: EmbeddingIndex) -> KnowledgeIndexResult:
    return KnowledgeIndexResult(
        index_sha256=index.index_sha256,
        manifest_sha256=index.manifest_sha256,
        space_sha256=index.metadata.profile.space_sha256,
        passage_count=len(index.passages),
    )


@router.post(
    "/indexes/build",
    response_model=KnowledgeIndexResult,
    operation_id="admin_build_knowledge_index",
)
async def build_index(
    body: BuildKnowledgeIndex,
    request: Request,
    actor: Annotated[AuthenticatedAccount, Depends(current_admin)],
    service: Annotated[KnowledgeIndexingService, Depends(get_knowledge_indexing_service)],
) -> KnowledgeIndexResult:
    index = await run_knowledge_operation(
        request, actor, lambda: service.build(key=body.operation_key, actor=actor)
    )
    return _result(index)
