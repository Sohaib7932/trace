from collections.abc import Iterator
from typing import Annotated, cast

from fastapi import Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.ai.client import BoundedAIClient
from app.ai.interface import TutorProvider
from app.ai.providers.bounded_support import BoundedSupportAssistant
from app.ai.providers.disabled_evidence_feedback import DisabledEvidenceFeedbackProvider
from app.ai.providers.fake import FakeTutorProvider
from app.ai.providers.guided_lesson_assistant import GuidedLessonAssistant
from app.ai.question_generator import QuestionGenerator
from app.ai.resources import AIResources
from app.auth.jwt import JwtVerifier
from app.core.errors import ApplicationError
from app.core.settings import Settings
from app.db.accounts import SqlAccountRepository
from app.db.candidates import SqlCandidateRepository
from app.db.feedback_release import SqlFeedbackReleaseRepository
from app.db.health import SqlReadinessProbe
from app.db.knowledge import SqlKnowledgeRepository
from app.db.learning import SqlLearningRepository
from app.db.session import Database
from app.domain.accounts import AuthenticatedAccount, Principal
from app.domain.clock import Clock
from app.domain.learning import LearningError
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.learning import LearningRepository
from app.repositories.verification import NotesVerifier
from app.schemas.feedback_release import FeedbackReleaseScope
from app.schemas.public_feedback import FeedbackVisibilityPolicy
from app.services.accounts import AccountService
from app.services.candidate_generation import CandidateGenerationService
from app.services.candidate_lifecycle import CandidateLifecycleService
from app.services.candidate_validation import CandidateValidationService
from app.services.catalog import CatalogService
from app.services.conversation_tutoring import ConversationTutoringService
from app.services.evidence_feedback import EvidenceFeedbackService
from app.services.feedback_operations import FeedbackOperations
from app.services.feedback_release import FeedbackReleaseService
from app.services.health import HealthService
from app.services.identity import COOKIE_NAME, IdentityService
from app.services.knowledge import KnowledgeGovernanceService
from app.services.knowledge_indexing import KnowledgeIndexingService
from app.services.learner_feedback import LearnerFeedbackService
from app.services.learning import LearningService
from app.services.lesson_assistant import LessonAssistantService
from app.services.lesson_tutoring import LessonTutoringService
from app.services.retrieval import RetrievalService
from app.services.support import SupportService
from app.services.verification import VerificationService
from app.verification.asgi_notes import AsgiNotesVerifier
from app.verification.asgi_tasks import AsgiTasksVerifier
from app.verification.candidate_runtime import IsolatedCandidateRuntime


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


def get_knowledge_repository(
    database: Annotated[Database, Depends(get_database)],
) -> KnowledgeRepository:
    return SqlKnowledgeRepository(database)


def get_knowledge_service(
    request: Request,
    repository: Annotated[KnowledgeRepository, Depends(get_knowledge_repository)],
) -> KnowledgeGovernanceService:
    return KnowledgeGovernanceService(repository, cast(Clock, request.app.state.clock))


def get_knowledge_operations(request: Request) -> FeedbackOperations:
    operations = getattr(request.app.state, "knowledge_operations", None)
    if not isinstance(operations, FeedbackOperations) or operations.closed:
        raise ApplicationError(
            "dependency_unavailable", "Knowledge administration is unavailable.", 503
        )
    return operations


def get_session(database: Annotated[Database, Depends(get_database)]) -> Iterator[Session]:
    with database.session() as session:
        yield session


def get_health_service(
    request: Request, database: Annotated[Database, Depends(get_database)]
) -> HealthService:
    return HealthService(SqlReadinessProbe(database.engine, request.app.state.migration_heads))


def get_tutor_provider(settings: Annotated[Settings, Depends(get_settings)]) -> TutorProvider:
    # Settings currently allows only fake. Add live selection with a tested real adapter.
    return FakeTutorProvider()


def get_learning_repository(
    database: Annotated[Database, Depends(get_database)],
) -> LearningRepository:
    return SqlLearningRepository(database)


def get_identity_service(
    repository: Annotated[LearningRepository, Depends(get_learning_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> IdentityService:
    return IdentityService(repository, settings.credential_lifetime_seconds)


def get_account_service(database: Annotated[Database, Depends(get_database)]) -> AccountService:
    return AccountService(SqlAccountRepository(database))


def optional_account(
    request: Request,
    service: Annotated[AccountService, Depends(get_account_service)],
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))],
) -> AuthenticatedAccount | None:
    value = request.headers.get("authorization")
    if value is None:
        return None
    if len(request.headers.getlist("authorization")) != 1:
        raise LearningError("unauthenticated", "Use one Bearer authorization header.")
    identity = cast(JwtVerifier, request.app.state.jwt_verifier).authorization(value)
    return AuthenticatedAccount(service.bootstrap(identity), identity)


def current_account(
    auth: Annotated[AuthenticatedAccount | None, Depends(optional_account)],
) -> AuthenticatedAccount:
    if auth is None:
        raise LearningError("unauthenticated", "Sign in to access your Trace account.")
    return auth


def current_learner(
    request: Request,
    service: Annotated[IdentityService, Depends(get_identity_service)],
    accounts: Annotated[AccountService, Depends(get_account_service)],
    auth: Annotated[AuthenticatedAccount | None, Depends(optional_account)],
) -> Principal:
    if auth:
        return Principal(accounts.learner(auth.account), auth.identity.expires_at, auth.account)
    credential = service.authenticate(request.cookies.get(COOKIE_NAME))
    return Principal(credential.learner_id, credential.expires_at, credential=credential)


def get_catalog_service(
    repository: Annotated[LearningRepository, Depends(get_learning_repository)],
) -> CatalogService:
    return CatalogService(repository)


def get_learning_service(
    repository: Annotated[LearningRepository, Depends(get_learning_repository)],
    tutor: Annotated[TutorProvider, Depends(get_tutor_provider)],
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> LearningService:
    return LearningService(
        repository,
        tutor,
        cast(Clock, request.app.state.clock),
        hint_timeout_seconds=settings.request_timeout_seconds,
    )


def get_notes_verifier(
    repository: Annotated[LearningRepository, Depends(get_learning_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> NotesVerifier:
    return AsgiNotesVerifier(repository, settings.verification_timeout_seconds)


def get_verification_service(
    repository: Annotated[LearningRepository, Depends(get_learning_repository)],
    verifier: Annotated[NotesVerifier, Depends(get_notes_verifier)],
    settings: Annotated[Settings, Depends(get_settings)],
    request: Request,
) -> VerificationService:
    return VerificationService(
        repository,
        verifier,
        settings.verification_timeout_seconds,
        AsgiTasksVerifier(repository, settings.verification_timeout_seconds),
        cast(Clock, request.app.state.clock),
    )


def get_retrieval_service(
    request: Request,
    repository: Annotated[LearningRepository, Depends(get_learning_repository)],
) -> RetrievalService:
    return RetrievalService(repository, cast(Clock, request.app.state.clock))


def require_write_origin(
    request: Request, response: Response, settings: Annotated[Settings, Depends(get_settings)]
) -> None:
    response.headers["Cache-Control"] = "no-store"
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and (
        request.headers.get("origin") not in settings.cors_origins
        or request.headers.get("x-trace-client") != "learning-web"
    ):
        raise ApplicationError(
            "unsafe_request", "An allowed Origin and Trace client header are required.", 403
        )


def get_ai_resources(request: Request) -> AIResources:
    resources = getattr(request.app.state, "ai_resources", None)
    if not isinstance(resources, AIResources) or resources.client.closed:
        raise ApplicationError("dependency_unavailable", "AI services are unavailable.", 503)
    return resources


def get_ai_client(resources: Annotated[AIResources, Depends(get_ai_resources)]) -> BoundedAIClient:
    return resources.client


def get_knowledge_indexing_service(
    request: Request,
    repository: Annotated[KnowledgeRepository, Depends(get_knowledge_repository)],
    resources: Annotated[AIResources, Depends(get_ai_resources)],
    governance: Annotated[KnowledgeGovernanceService, Depends(get_knowledge_service)],
    operations: Annotated[FeedbackOperations, Depends(get_knowledge_operations)],
) -> KnowledgeIndexingService:
    return KnowledgeIndexingService(
        repository,
        resources.embeddings,
        governance,
        clock=cast(Clock, request.app.state.clock),
        remaining_seconds=operations.remaining_seconds,
    )


def get_tutor_operations(request: Request) -> FeedbackOperations:
    operations = getattr(request.app.state, "tutor_operations", None)
    if not isinstance(operations, FeedbackOperations) or operations.closed:
        raise ApplicationError("dependency_unavailable", "Tutor is unavailable.", 503)
    return operations


def get_support_operations(request: Request) -> FeedbackOperations:
    operations = getattr(request.app.state, "support_operations", None)
    if not isinstance(operations, FeedbackOperations) or operations.closed:
        raise ApplicationError("dependency_unavailable", "Support is unavailable.", 503)
    return operations


def get_lesson_tutoring_service(
    request: Request,
    database: Annotated[Database, Depends(get_database)],
    resources: Annotated[AIResources, Depends(get_ai_resources)],
    operations: Annotated[FeedbackOperations, Depends(get_tutor_operations)],
) -> LessonTutoringService:
    return LessonTutoringService(
        SqlFeedbackReleaseRepository(database),
        lambda choices, subject: GuidedLessonAssistant(
            resources.client,
            choices,
            subject,
            timeout_seconds=operations.remaining_seconds(),
        ),
        cast(Clock, request.app.state.clock),
    )


def get_question_generator(
    resources: Annotated[AIResources, Depends(get_ai_resources)],
) -> QuestionGenerator:
    return resources.question_generator


def get_conversation_tutoring_service(
    context_source: Annotated[LessonTutoringService, Depends(get_lesson_tutoring_service)],
    resources: Annotated[AIResources, Depends(get_ai_resources)],
    operations: Annotated[FeedbackOperations, Depends(get_tutor_operations)],
) -> ConversationTutoringService:
    return ConversationTutoringService(
        context_source,
        resources.conversation_tutor,
        timeout_seconds=operations.settings.provider_timeout_seconds,
        remaining_seconds=operations.remaining_seconds,
    )


def get_candidate_generation_service(request: Request) -> CandidateGenerationService:
    # Internal orchestration only. No public route can reserve/release/assign candidates.
    get_ai_resources(request)
    service = getattr(request.app.state, "candidate_generation", None)
    if not isinstance(service, CandidateGenerationService):
        raise ApplicationError("dependency_unavailable", "Generation is unavailable.", 503)
    return service


def get_internal_tutor_provider(
    resources: Annotated[AIResources, Depends(get_ai_resources)],
) -> TutorProvider:
    return resources.tutor_provider


def get_lesson_assistant_service(
    resources: Annotated[AIResources, Depends(get_ai_resources)],
) -> LessonAssistantService:
    return resources.lesson_assistant


def get_support_service(
    resources: Annotated[AIResources, Depends(get_ai_resources)],
) -> SupportService:
    return resources.support


def get_http_support_service(
    resources: Annotated[AIResources, Depends(get_ai_resources)],
    operations: Annotated[FeedbackOperations, Depends(get_support_operations)],
) -> SupportService:
    return SupportService(
        BoundedSupportAssistant(
            resources.client,
            timeout_seconds=operations.settings.provider_timeout_seconds,
            remaining_seconds=operations.remaining_seconds,
        ),
        resources.support.knowledge,
        escalation=resources.support.escalation,
        remaining_seconds=operations.remaining_seconds,
    )


def get_evidence_feedback_service(
    request: Request,
    repository: Annotated[LearningRepository, Depends(get_learning_repository)],
    resources: Annotated[AIResources, Depends(get_ai_resources)],
) -> EvidenceFeedbackService:
    # Internal composition only; no learner route or hint-provider selection changes.
    return EvidenceFeedbackService(
        repository, resources.evidence_feedback_provider, cast(Clock, request.app.state.clock)
    )


def get_feedback_release_service(
    request: Request,
    database: Annotated[Database, Depends(get_database)],
    feedback: Annotated[EvidenceFeedbackService, Depends(get_evidence_feedback_service)],
) -> FeedbackReleaseService:
    return FeedbackReleaseService(
        SqlFeedbackReleaseRepository(database), feedback, cast(Clock, request.app.state.clock)
    )


def get_learner_feedback_service(
    request: Request,
    release: Annotated[FeedbackReleaseService, Depends(get_feedback_release_service)],
) -> LearnerFeedbackService:
    # No audience/next-action/reflection policy is production-approved. This
    # internal dependency stays disabled and is not mounted on a public route.
    return LearnerFeedbackService(
        release, FeedbackVisibilityPolicy.disabled(), cast(Clock, request.app.state.clock)
    )


def get_feedback_operations(request: Request) -> FeedbackOperations:
    """Reuse one application-owned admission controller, never one per request."""
    operations = getattr(request.app.state, "feedback_operations", None)
    if not isinstance(operations, FeedbackOperations):
        raise ApplicationError("dependency_unavailable", "Feedback is unavailable.", 503)
    return operations


def get_http_feedback_release_service(
    request: Request,
    database: Annotated[Database, Depends(get_database)],
    repository: Annotated[LearningRepository, Depends(get_learning_repository)],
    operations: Annotated[FeedbackOperations, Depends(get_feedback_operations)],
) -> FeedbackReleaseService:
    """Keep public delivery deterministic even if internal tests inject a mock."""
    clock = cast(Clock, request.app.state.clock)
    feedback = EvidenceFeedbackService(
        repository, operations.bounded_provider(DisabledEvidenceFeedbackProvider()), clock
    )
    return FeedbackReleaseService(SqlFeedbackReleaseRepository(database), feedback, clock)


def get_http_learner_feedback_service(
    request: Request,
    release: Annotated[FeedbackReleaseService, Depends(get_http_feedback_release_service)],
) -> LearnerFeedbackService:
    """The explicitly approved account reflection audience, without repair hints."""
    policy = FeedbackVisibilityPolicy(
        scope=FeedbackReleaseScope(allowed_modes=("account",), allow_terminal_reflection=True),
        include_recall=False,
        next_action_ids=(),
        allow_mock_delivery=False,
        approval_reference="phase35c-mvp-account-reflection-v1",
    )
    return LearnerFeedbackService(
        release,
        policy,
        cast(Clock, request.app.state.clock),
        allowed_states=(
            "awaiting_prediction",
            "ready_for_attempt",
            "verification_pending",
            "needs_revision",
            "completed",
        ),
    )


def get_candidate_lifecycle_service(
    request: Request,
    database: Annotated[Database, Depends(get_database)],
) -> CandidateLifecycleService:
    # Stateless lifecycle orchestration needs no provider client and exposes no route.
    return CandidateLifecycleService(
        SqlCandidateRepository(database),
        CandidateValidationService(IsolatedCandidateRuntime()),
        cast(Clock, request.app.state.clock),
    )
