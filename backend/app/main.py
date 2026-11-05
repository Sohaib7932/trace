import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from threading import RLock, Thread

import anyio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ai.accounting import AdmissionPolicy, AIAccountingError, SharedAdmission
from app.ai.providers.github_app import GitHubAppClient
from app.ai.providers.private_guides import BoundedGuideGenerator
from app.ai.resources import AIResources, AITransportFactory, EmbeddingTransportFactory
from app.ai.support_diagnostics import record_support_runtime
from app.api.custom_lessons_runtime import build_custom_lessons
from app.api.v1.accounts import router as account_router
from app.api.v1.custom_lessons import router as custom_lessons_router
from app.api.v1.feedback import router as feedback_router
from app.api.v1.github_projects import router as github_projects_router
from app.api.v1.knowledge_admin import router as knowledge_admin_router
from app.api.v1.knowledge_indexes import router as knowledge_indexes_router
from app.api.v1.leaderboard import router as leaderboard_router
from app.api.v1.learning import router as learning_router
from app.api.v1.private_guides import router as private_guides_router
from app.api.v1.project_knowledge import router as project_knowledge_router
from app.api.v1.router import router
from app.api.v1.support import router as support_router
from app.api.v1.tutoring import router as tutor_router
from app.auth.jwt import JwtVerifier
from app.core.accounting_settings import AccountingSettings
from app.core.ai_settings import AIClientSettings
from app.core.custom_lesson_settings import CustomLessonSettings
from app.core.embedding_settings import EmbeddingSettings
from app.core.errors import register_error_handlers
from app.core.feedback_middleware import FeedbackSecurityMiddleware
from app.core.feedback_settings import FeedbackSettings
from app.core.github_settings import GitHubSettings, load_github_env_file
from app.core.https_middleware import ProductionHTTPSMiddleware
from app.core.logging import create_logger
from app.core.middleware import RequestContextMiddleware, RequestLimitsMiddleware
from app.core.retrieval_settings import RetrievalSettings
from app.core.settings import Settings
from app.core.support_settings import SupportSettings
from app.core.tutor_settings import TutorSettings
from app.db.accounting import SqlAIControls
from app.db.candidates import SqlCandidateRepository
from app.db.github_projects import SqlGitHubProjectRepository
from app.db.knowledge import SqlKnowledgeRepository
from app.db.migrations import expected_heads
from app.db.private_guides import SqlPrivateGuideRepository
from app.db.project_knowledge import SqlProjectKnowledgeRepository
from app.db.session import Database
from app.domain.clock import Clock, utc_now
from app.services.candidate_generation import CandidateGenerationService
from app.services.candidate_lifecycle import CandidateLifecycleService
from app.services.candidate_validation import CandidateValidationService
from app.services.feedback_operations import FeedbackOperations, SharedIngressJobs
from app.services.github_projects import GitHubProjectService
from app.services.private_guides import PrivateGuideService
from app.services.project_knowledge import ProjectKnowledgeService
from app.support.database import DatabaseSupportKnowledge
from app.support.semantic import SemanticRetrievalSettings, SemanticSupportKnowledge
from app.verification.candidate_runtime import IsolatedCandidateRuntime

_SHUTDOWN_GRACE_SECONDS = 30.0


def _drain_operations(operations: tuple[FeedbackOperations, ...], timeout: float | None) -> bool:
    deadline = time.monotonic() + timeout if timeout is not None else None
    for operation in operations:
        remaining = max(0, deadline - time.monotonic()) if deadline is not None else None
        if not operation.wait_for_idle(remaining):
            return False
    return True


def create_app(
    settings: Settings | None = None,
    database: Database | None = None,
    clock: Clock = utc_now,
    jwt_verifier: JwtVerifier | None = None,
    ai_settings: AIClientSettings | None = None,
    ai_transport_factory: AITransportFactory | None = None,
    feedback_settings: FeedbackSettings | None = None,
    tutor_settings: TutorSettings | None = None,
    support_settings: SupportSettings | None = None,
    accounting_settings: AccountingSettings | None = None,
    embedding_settings: EmbeddingSettings | None = None,
    embedding_transport_factory: EmbeddingTransportFactory | None = None,
    retrieval_settings: RetrievalSettings | None = None,
    github_settings: GitHubSettings | None = None,
    custom_lesson_settings: CustomLessonSettings | None = None,
) -> FastAPI:
    config = settings if settings is not None else Settings()
    logger = create_logger(config.log_level)
    ai_config = ai_settings if ai_settings is not None else AIClientSettings(_env_file=None)
    accounting_config = accounting_settings or AccountingSettings(_env_file=None)
    embedding_config = embedding_settings or EmbeddingSettings(_env_file=None)
    retrieval_config = retrieval_settings or RetrievalSettings(_env_file=None)
    if github_settings is None and config.environment == "development":
        # Owner GitHub App values live in the untracked backend/.env.github (names only here).
        load_github_env_file()
    github_config = github_settings or GitHubSettings(_env_file=None)
    custom_lesson_config = custom_lesson_settings or CustomLessonSettings()
    if config.environment == "production":
        if github_config.mode == "enabled" and not github_config.callback_url.startswith(
            "https://"
        ):
            raise ValueError("Production GitHub callbacks require HTTPS")
        if ai_config.mode == "mock" or embedding_config.mode == "mock":
            raise ValueError("Production AI accepts disabled or approved genuine modes only")
        if accounting_config.mode != "durable":
            raise ValueError("Production requires durable shared allowance accounting")
        if retrieval_config.mode != "lexical":
            raise ValueError("Production vector ranking awaits independent quality approval")
    requested_feedback = (
        feedback_settings if feedback_settings is not None else FeedbackSettings(_env_file=None)
    )
    feedback_values = requested_feedback.model_dump(warnings=False)
    request_deadline = min(
        requested_feedback.request_timeout_seconds, config.request_timeout_seconds
    )
    feedback_config = FeedbackSettings.model_validate(
        {
            **feedback_values,
            "request_timeout_seconds": request_deadline,
            "provider_timeout_seconds": min(
                requested_feedback.provider_timeout_seconds, request_deadline
            ),
            "max_request_bytes": min(
                requested_feedback.max_request_bytes, config.max_request_bytes
            ),
        }
    )
    requested_tutor = (
        tutor_settings if tutor_settings is not None else TutorSettings(_env_file=None)
    )
    tutor_deadline = min(requested_tutor.request_timeout_seconds, config.request_timeout_seconds)
    tutor_config = TutorSettings.model_validate(
        {
            **requested_tutor.model_dump(warnings=False),
            "request_timeout_seconds": tutor_deadline,
            "provider_timeout_seconds": min(
                requested_tutor.provider_timeout_seconds, tutor_deadline
            ),
            "max_request_bytes": min(requested_tutor.max_request_bytes, config.max_request_bytes),
        }
    )

    requested_support = (
        support_settings if support_settings is not None else SupportSettings(_env_file=None)
    )
    support_deadline = min(
        requested_support.request_timeout_seconds, config.request_timeout_seconds
    )
    support_config = SupportSettings.model_validate(
        {
            **requested_support.model_dump(warnings=False),
            "request_timeout_seconds": support_deadline,
            "provider_timeout_seconds": min(
                requested_support.provider_timeout_seconds, support_deadline
            ),
            "max_request_bytes": min(requested_support.max_request_bytes, config.max_request_bytes),
        }
    )
    knowledge_config = TutorSettings.model_validate(
        {
            **tutor_config.model_dump(warnings=False),
            "max_request_bytes": min(16384, config.max_request_bytes),
            "max_response_bytes": 262144,
        }
    )
    github_limits = TutorSettings.model_validate(
        {**knowledge_config.model_dump(warnings=False), "requests_per_minute": 10}
    )

    def admission_policy(
        family: str, limits: FeedbackSettings, *, ingress: bool = False
    ) -> AdmissionPolicy | None:
        if accounting_config.mode != "durable":
            return None
        return AdmissionPolicy(
            scope=f"{accounting_config.scope}:{family}:{'ingress' if ingress else 'worker'}",
            global_requests_per_minute=limits.ingress_requests_per_minute,
            subject_requests_per_minute=limits.ingress_requests_per_minute
            if ingress
            else limits.requests_per_minute,
            max_global_in_flight=limits.max_ingress_in_flight
            if ingress
            else limits.max_global_in_flight,
            max_subject_in_flight=min(16, limits.max_ingress_in_flight)
            if ingress
            else limits.max_subject_in_flight,
        )

    # Validate namespace lengths and all limits before opening any resources.
    worker_policies = tuple(
        admission_policy(name, limits)
        for name, limits in (
            ("feedback", feedback_config),
            ("tutor", tutor_config),
            ("support", support_config),
            ("knowledge", knowledge_config),
            ("guide", tutor_config),
            ("github", github_limits),
        )
    )
    ingress_policies = {
        name: admission_policy(name, limits, ingress=True)
        for name, limits in (
            ("feedback", feedback_config),
            ("tutor", tutor_config),
            ("support", support_config),
            ("knowledge", knowledge_config),
            ("guide", tutor_config),
            ("github", github_limits),
        )
    }
    # A default verifier belongs to this application, never to a state override.
    # Nested/repeated lifespans share it until their final real worker drains.
    # Preserve the existing UTC authentication clock. The separately injectable
    # learning/retrieval clock is not a token issuer clock; explicit verifier
    # injection remains available for deterministic authentication tests.
    owned_verifier = JwtVerifier(config) if jwt_verifier is None else None
    verifier_owners = 0
    verifier_lock = RLock()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal owned_verifier, verifier_owners
        resource: Database | None = None
        ai: AIResources | None = None
        operations: list[FeedbackOperations] = []
        ingress_jobs: SharedIngressJobs | None = None
        verifier_acquired = False
        github_client: GitHubAppClient | None = None
        try:
            with verifier_lock:
                if owned_verifier is not None:
                    if owned_verifier.closed and app.state.jwt_verifier is owned_verifier:
                        owned_verifier = JwtVerifier(config)
                        app.state.jwt_verifier = owned_verifier
                    verifier_owners += 1
                    verifier_acquired = True
            resource = database if database is not None else Database(config)
            app.state.database = resource
            controls = SqlAIControls(resource) if accounting_config.mode == "durable" else None
            app.state.ai_controls = controls
            ingress_jobs = SharedIngressJobs() if controls is not None else None
            app.state.shared_ingress_jobs = ingress_jobs
            for name, limits, policy in zip(
                ("feedback", "tutor", "support", "knowledge", "guide", "github"),
                (
                    feedback_config,
                    tutor_config,
                    support_config,
                    knowledge_config,
                    tutor_config,
                    github_limits,
                ),
                worker_policies,
                strict=True,
            ):
                operation = FeedbackOperations(
                    limits, shared_admission=controls, admission_policy=policy
                )
                operations.append(operation)
                setattr(app.state, name + "_operations", operation)
            knowledge = (
                DatabaseSupportKnowledge(SqlKnowledgeRepository(resource), clock)
                if config.environment == "production" or accounting_config.mode == "durable"
                else None
            )
            ai = AIResources.create(
                ai_config,
                ai_transport_factory,
                clock=clock,
                ledger=controls,
                allowance_policy=accounting_config.policy() if controls is not None else None,
                embedding_settings=embedding_config,
                embedding_transport_factory=embedding_transport_factory,
                knowledge=knowledge,
            )
            if retrieval_config.mode != "lexical":
                if knowledge is None:
                    raise ValueError("Vector experiments require a published durable corpus")
                with SqlKnowledgeRepository(resource).read() as store:
                    index = store.index(retrieval_config.index_sha256 or "")
                ai.support.knowledge = SemanticSupportKnowledge(
                    knowledge,
                    ai.embeddings,
                    index,
                    SemanticRetrievalSettings(
                        mode=retrieval_config.mode,
                        allow_unreviewed_experiment=retrieval_config.allow_unreviewed_experiment,
                        lexical_weight=retrieval_config.lexical_weight,
                        semantic_weight=retrieval_config.semantic_weight,
                        minimum_cosine=retrieval_config.minimum_cosine,
                    ),
                )
            app.state.ai_resources = ai
            github_client = GitHubAppClient(github_config)
            app.state.github_projects = GitHubProjectService(
                SqlGitHubProjectRepository(resource),
                github_config,
                github_client,
                ai.client,
                clock=clock,
            )
            app.state.project_knowledge = ProjectKnowledgeService(
                app.state.github_projects, SqlProjectKnowledgeRepository(resource), ai.client, clock
            )
            app.state.guide_service = PrivateGuideService(
                SqlPrivateGuideRepository(resource),
                BoundedGuideGenerator(ai.client),
                clock,
                remaining_seconds=app.state.guide_operations.remaining_seconds,
            )
            available: bool | None = None
            source_count: int | None = None
            try:
                active_knowledge = ai.support.knowledge
                snapshot_loader = getattr(
                    active_knowledge.knowledge
                    if isinstance(active_knowledge, SemanticSupportKnowledge)
                    else active_knowledge,
                    "snapshot",
                    None,
                )
                if callable(snapshot_loader):
                    snapshot = snapshot_loader()
                    available = snapshot.available
                    source_count = len(snapshot.sources)
                else:
                    available, source_count = active_knowledge.available, 0
            except Exception:
                pass  # Knowledge availability does not change readiness or bypass review.
            record_support_runtime(
                app.state.logger,
                ai_mode=ai_config.mode,
                accounting_mode=accounting_config.mode,
                retrieval_mode=retrieval_config.mode,
                knowledge_backend="semantic_archive"
                if retrieval_config.mode != "lexical"
                else "sql_archive"
                if knowledge is not None
                else "reviewed_file"
                if ai_config.mode == "gemini_free"
                else "empty_allowlist",
                available=available,
                source_count=source_count,
            )
            app.state.candidate_generation = CandidateGenerationService(
                ai.question_generator,
                CandidateLifecycleService(
                    SqlCandidateRepository(resource),
                    CandidateValidationService(IsolatedCandidateRuntime()),
                    clock,
                ),
            )
            # Learner-requested lessons: own client over the same transport and ledger.
            app.state.custom_lessons = build_custom_lessons(
                resource, ai, custom_lesson_config, clock, app.state.logger
            )
            yield
        finally:
            custom_lessons = getattr(app.state, "custom_lessons", None)
            if custom_lessons is not None:
                with anyio.CancelScope(shield=True):
                    await anyio.to_thread.run_sync(custom_lessons.close)
                app.state.custom_lessons = None
            for operation in operations:
                operation.close()
            if ingress_jobs is not None:
                ingress_jobs.close()
            if ai is not None:
                ai.stop_admission()

            def dispose() -> None:
                nonlocal verifier_owners
                try:
                    if ai is not None:
                        ai.close()
                finally:
                    try:
                        if github_client is not None:
                            github_client.close()
                    finally:
                        dispose_verifier()

            def dispose_verifier() -> None:
                nonlocal verifier_owners
                try:
                    with verifier_lock:
                        if owned_verifier is not None:
                            if verifier_acquired:
                                verifier_owners -= 1
                            if verifier_owners == 0:
                                owned_verifier.close()
                finally:
                    if database is None and resource is not None:
                        resource.dispose()

            # ASGI cancellation does not mean its abandoned sync worker stopped.
            # Keep the DB/AI alive through fresh final authorization and readback.
            with anyio.CancelScope(shield=True):
                grace_end = time.monotonic() + _SHUTDOWN_GRACE_SECONDS
                drained = await anyio.to_thread.run_sync(
                    _drain_operations, tuple(operations), _SHUTDOWN_GRACE_SECONDS
                )
                if drained and ingress_jobs is not None:
                    drained = await anyio.to_thread.run_sync(
                        ingress_jobs.wait_for_idle, max(0, grace_end - time.monotonic())
                    )
                if drained and ai is not None:
                    drained = await anyio.to_thread.run_sync(
                        ai.wait_for_idle, max(0, grace_end - time.monotonic())
                    )
                if drained and owned_verifier is not None:
                    drained = await anyio.to_thread.run_sync(
                        owned_verifier.wait_for_idle, max(0, grace_end - time.monotonic())
                    )
                if drained:
                    await anyio.to_thread.run_sync(dispose)
                else:
                    # A cancellation-resistant injected implementation may exceed
                    # the grace period. Do not destroy resources under its worker.
                    # This retains ownership; it does not kill arbitrary threads.
                    logger.warning("ai_shutdown_drain_deferred")

                    def deferred_dispose() -> None:
                        _drain_operations(tuple(operations), None)
                        if ingress_jobs is not None:
                            ingress_jobs.wait_for_idle(None)
                        if ai is not None:
                            ai.wait_for_idle(None)
                        if owned_verifier is not None:
                            owned_verifier.wait_for_idle(None)
                        try:
                            dispose()
                        except Exception:
                            logger.error("ai_shutdown_cleanup_failed")

                    Thread(
                        target=deferred_dispose, daemon=True, name="trace-shutdown-drain"
                    ).start()

    app = FastAPI(title="Trace API", version="0.1.0", lifespan=lifespan)
    app.state.settings = config
    app.state.ai_settings = ai_config
    app.state.feedback_settings = feedback_config
    app.state.tutor_settings = tutor_config
    app.state.support_settings = support_config
    app.state.accounting_settings = accounting_config
    app.state.embedding_settings = embedding_config
    app.state.retrieval_settings = retrieval_config
    app.state.custom_lesson_settings = custom_lesson_config
    app.state.migration_heads = expected_heads()
    app.state.logger = logger
    app.state.clock = clock
    app.state.jwt_verifier = jwt_verifier if jwt_verifier is not None else owned_verifier

    def ingress_factory(
        family: str, limits: FeedbackSettings
    ) -> Callable[[], tuple[SharedAdmission, AdmissionPolicy]] | None:
        policy = ingress_policies[family]
        if policy is None:
            return None

        def get_shared() -> tuple[SharedAdmission, AdmissionPolicy]:
            controls = getattr(app.state, "ai_controls", None)
            if not isinstance(controls, SqlAIControls):
                raise AIAccountingError("unavailable")
            return controls, policy

        return get_shared

    def ingress_tracker() -> SharedIngressJobs:
        jobs = getattr(app.state, "shared_ingress_jobs", None)
        if not isinstance(jobs, SharedIngressJobs):
            raise AIAccountingError("unavailable")
        return jobs

    tracker_factory = ingress_tracker if accounting_config.mode == "durable" else None

    register_error_handlers(app)
    app.include_router(router)
    app.include_router(learning_router)
    app.include_router(account_router)
    app.include_router(leaderboard_router)
    app.include_router(feedback_router)
    app.include_router(tutor_router)
    app.include_router(support_router)
    app.include_router(private_guides_router)
    app.include_router(github_projects_router)
    app.include_router(project_knowledge_router)
    app.include_router(knowledge_admin_router)
    app.include_router(knowledge_indexes_router)
    app.include_router(custom_lessons_router)
    # Request context wraps feedback ingress, CORS and generic limit handling.
    app.add_middleware(
        RequestLimitsMiddleware,
        max_bytes=config.max_request_bytes,
        timeout_seconds=config.request_timeout_seconds,
        logger=logger,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=[
            "Content-Type",
            "X-Request-ID",
            "X-Trace-Client",
            "Idempotency-Key",
            "Authorization",
        ],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(
        FeedbackSecurityMiddleware,
        settings=feedback_config,
        allowed_origins=config.cors_origins,
        shared_admission_factory=ingress_factory("feedback", feedback_config),
        shared_admission_tracker_factory=tracker_factory,
    )
    app.add_middleware(
        FeedbackSecurityMiddleware,
        settings=tutor_config,
        allowed_origins=config.cors_origins,
        path_pattern=r"/api/v1/sessions/[^/]+/tutor/ask/?\Z",
        deadline_key="tutor_deadline",
        error_subject="Lesson tutor",
        error_code_prefix="tutor",
        shared_admission_factory=ingress_factory("tutor", tutor_config),
        shared_admission_tracker_factory=tracker_factory,
    )
    app.add_middleware(
        FeedbackSecurityMiddleware,
        settings=support_config,
        allowed_origins=config.cors_origins,
        path_pattern=r"/api/v1/support/ask/?\Z",
        deadline_key="support_deadline",
        error_subject="Customer support",
        error_code_prefix="support",
        shared_admission_factory=ingress_factory("support", support_config),
        shared_admission_tracker_factory=tracker_factory,
    )
    app.add_middleware(
        FeedbackSecurityMiddleware,
        settings=knowledge_config,
        allowed_origins=config.cors_origins,
        path_pattern=r"/api/v1/admin/knowledge(?:/.*)?\Z",
        deadline_key="knowledge_deadline",
        error_subject="Knowledge administration",
        error_code_prefix="knowledge",
        shared_admission_factory=ingress_factory("knowledge", knowledge_config),
        shared_admission_tracker_factory=tracker_factory,
    )
    app.add_middleware(
        FeedbackSecurityMiddleware,
        settings=tutor_config,
        allowed_origins=config.cors_origins,
        path_pattern=r"/api/v1/learning-guides(?:/[^/]+)?/?\Z",
        deadline_key="guide_deadline",
        error_subject="Private learning guides",
        error_code_prefix="guide",
        shared_admission_factory=ingress_factory("guide", tutor_config),
        shared_admission_tracker_factory=tracker_factory,
    )
    app.add_middleware(
        FeedbackSecurityMiddleware,
        settings=github_limits,
        allowed_origins=config.cors_origins,
        path_pattern=r"/api/v1/projects/github(?:/.*)?\Z",
        deadline_key="github_deadline",
        error_subject="GitHub Project Learning",
        error_code_prefix="github",
        shared_admission_factory=ingress_factory("github", github_limits),
        shared_admission_tracker_factory=tracker_factory,
    )
    if config.environment == "production":
        app.add_middleware(ProductionHTTPSMiddleware)
    app.add_middleware(RequestContextMiddleware, logger=logger)
    return app
