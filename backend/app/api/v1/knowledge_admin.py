"""Protected bounded customer-document operations; no URL/path ingestion or learner access."""

from collections.abc import Callable
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import AwareDatetime, Field, StrictInt, model_validator

from app.api.dependencies import (
    current_account,
    get_account_service,
    get_knowledge_operations,
    get_knowledge_service,
    require_write_origin,
)
from app.core.errors import ApplicationError
from app.domain.accounts import AuthenticatedAccount
from app.domain.clock import Clock
from app.domain.knowledge import (
    KnowledgeHistory,
    KnowledgePublication,
    KnowledgeReason,
    KnowledgeReleaseReceipt,
)
from app.domain.learning import LearningError
from app.domain.lesson_spec.fields import Digest, Items, Value, Version, VersionId
from app.schemas.errors import ErrorResponse
from app.services.accounts import AccountService
from app.services.knowledge import KnowledgeGovernanceService
from app.support.knowledge import CorpusDocument

router = APIRouter(
    prefix="/api/v1/admin/knowledge",
    tags=["knowledge administration"],
    dependencies=[Depends(require_write_origin)],
    responses={
        code: {"model": ErrorResponse}
        for code in (401, 403, 404, 409, 413, 422, 429, 500, 503, 504)
    },
)


async def run_knowledge_operation[T](
    request: Request, actor: AuthenticatedAccount, operation: Callable[[], T]
) -> T:
    deadline = getattr(request.state, "knowledge_deadline", None)
    if not isinstance(deadline, float):
        raise ApplicationError(
            "dependency_unavailable", "Knowledge administration is unavailable.", 503
        )
    return await get_knowledge_operations(request).execute_account(
        actor.account.id, operation, deadline=deadline
    )


def current_admin(
    request: Request,
    auth: Annotated[AuthenticatedAccount, Depends(current_account)],
    accounts: Annotated[AccountService, Depends(get_account_service)],
) -> AuthenticatedAccount:
    if cast(Clock, request.app.state.clock)() >= auth.identity.expires_at:
        raise LearningError("unauthenticated", "Account authorization expired.")
    fresh = accounts.bootstrap(auth.identity)
    fresh.require_role("admin")
    if fresh.id != auth.account.id:
        raise LearningError("unauthenticated", "Account authorization changed.")
    return AuthenticatedAccount(fresh, auth.identity)


class IngestKnowledge(Value):
    document: CorpusDocument
    revision: Version
    operation_key: VersionId

    @model_validator(mode="after")
    def safe_copy(self) -> "IngestKnowledge":
        self.document.document()
        return self


class KnowledgeTransition(Value):
    action: Literal[
        "parse",
        "normalize",
        "chunk",
        "index",
        "validate",
        "review",
        "approve",
        "adopt_existing_review",
        "reject",
        "revoke",
        "expire",
    ]
    expected_sequence: Annotated[StrictInt, Field(ge=0)]
    operation_key: VersionId
    reason: KnowledgeReason
    reviewed_document_sha256: Digest | None = None
    valid_until: AwareDatetime | None = None


class ImportReviewedCorpus(Value):
    operation_key: VersionId
    adopt_existing_review: bool = False


class PublishKnowledge(Value):
    revision_ids: Items[VersionId] = Field(min_length=1, max_length=32)
    expected_sequence: Annotated[StrictInt, Field(ge=-1)]
    operation_key: VersionId
    reason: KnowledgeReason


@router.post("/revisions", response_model=KnowledgeHistory, operation_id="admin_ingest_knowledge")
async def ingest(
    body: IngestKnowledge,
    request: Request,
    actor: Annotated[AuthenticatedAccount, Depends(current_admin)],
    service: Annotated[KnowledgeGovernanceService, Depends(get_knowledge_service)],
) -> KnowledgeHistory:
    return await run_knowledge_operation(
        request,
        actor,
        lambda: service.ingest(
            body.document, revision=body.revision, key=body.operation_key, actor=actor
        ),
    )


@router.get(
    "/revisions/{revision_id}",
    response_model=KnowledgeHistory,
    operation_id="admin_get_knowledge_revision",
)
async def get_revision(
    revision_id: UUID,
    request: Request,
    actor: Annotated[AuthenticatedAccount, Depends(current_admin)],
    service: Annotated[KnowledgeGovernanceService, Depends(get_knowledge_service)],
) -> KnowledgeHistory:
    return await run_knowledge_operation(
        request, actor, lambda: service.get(str(revision_id), actor=actor)
    )


@router.post(
    "/revisions/{revision_id}/transitions",
    response_model=KnowledgeHistory,
    operation_id="admin_transition_knowledge",
)
async def transition(
    revision_id: UUID,
    body: KnowledgeTransition,
    request: Request,
    actor: Annotated[AuthenticatedAccount, Depends(current_admin)],
    service: Annotated[KnowledgeGovernanceService, Depends(get_knowledge_service)],
) -> KnowledgeHistory:
    return await run_knowledge_operation(
        request,
        actor,
        lambda: service.advance(
            str(revision_id),
            action=body.action,
            expected_sequence=body.expected_sequence,
            key=body.operation_key,
            actor=actor,
            reason=body.reason,
            reviewed_document_sha256=body.reviewed_document_sha256,
            valid_until=body.valid_until,
        ),
    )


@router.post(
    "/import-reviewed-corpus",
    response_model=tuple[KnowledgeHistory, ...],
    operation_id="admin_import_reviewed_knowledge",
)
async def import_corpus(
    body: ImportReviewedCorpus,
    request: Request,
    actor: Annotated[AuthenticatedAccount, Depends(current_admin)],
    service: Annotated[KnowledgeGovernanceService, Depends(get_knowledge_service)],
) -> tuple[KnowledgeHistory, ...]:
    return await run_knowledge_operation(
        request,
        actor,
        lambda: service.import_reviewed_corpus(
            key=body.operation_key, actor=actor, adopt_existing_review=body.adopt_existing_review
        ),
    )


@router.post(
    "/publications", response_model=KnowledgePublication, operation_id="admin_publish_knowledge"
)
async def publish(
    body: PublishKnowledge,
    request: Request,
    actor: Annotated[AuthenticatedAccount, Depends(current_admin)],
    service: Annotated[KnowledgeGovernanceService, Depends(get_knowledge_service)],
) -> KnowledgePublication:
    return await run_knowledge_operation(
        request,
        actor,
        lambda: service.publish(
            body.revision_ids,
            key=body.operation_key,
            expected_sequence=body.expected_sequence,
            actor=actor,
            reason=body.reason,
        ),
    )


@router.get(
    "/receipts/{receipt_id}",
    response_model=KnowledgeReleaseReceipt,
    operation_id="admin_get_knowledge_receipt",
)
async def get_receipt(
    receipt_id: UUID,
    request: Request,
    actor: Annotated[AuthenticatedAccount, Depends(current_admin)],
    service: Annotated[KnowledgeGovernanceService, Depends(get_knowledge_service)],
) -> KnowledgeReleaseReceipt:
    return await run_knowledge_operation(
        request, actor, lambda: service.get_receipt(str(receipt_id), actor=actor)
    )
