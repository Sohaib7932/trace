from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ai.resources import AIResources, AITransportFactory
from app.api.v1.accounts import router as account_router
from app.api.v1.feedback import router as feedback_router
from app.api.v1.learning import router as learning_router
from app.api.v1.router import router
from app.auth.jwt import JwtVerifier
from app.core.ai_settings import AIClientSettings
from app.core.errors import register_error_handlers
from app.core.feedback_middleware import FeedbackSecurityMiddleware
from app.core.feedback_settings import FeedbackSettings
from app.core.logging import create_logger
from app.core.middleware import RequestContextMiddleware, RequestLimitsMiddleware
from app.core.settings import Settings
from app.db.migrations import expected_heads
from app.db.session import Database
from app.domain.clock import Clock, utc_now
from app.services.feedback_operations import FeedbackOperations


def create_app(
    settings: Settings | None = None,
    database: Database | None = None,
    clock: Clock = utc_now,
    jwt_verifier: JwtVerifier | None = None,
    ai_settings: AIClientSettings | None = None,
    ai_transport_factory: AITransportFactory | None = None,
    feedback_settings: FeedbackSettings | None = None,
) -> FastAPI:
    config = settings if settings is not None else Settings()
    logger = create_logger(config.log_level)
    ai_config = ai_settings if ai_settings is not None else AIClientSettings(_env_file=None)
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

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resource = database if database is not None else Database(config)
        app.state.database = resource
        ai: AIResources | None = None
        feedback_operations = FeedbackOperations(feedback_config)
        app.state.feedback_operations = feedback_operations
        try:
            ai = AIResources.create(ai_config, ai_transport_factory)
            app.state.ai_resources = ai
            yield
        finally:
            try:
                feedback_operations.close()
                if ai is not None:
                    ai.close()
            finally:
                if database is None:
                    resource.dispose()

    app = FastAPI(title="Trace API", version="0.1.0", lifespan=lifespan)
    app.state.settings = config
    app.state.ai_settings = ai_config
    app.state.feedback_settings = feedback_config
    app.state.migration_heads = expected_heads()
    app.state.logger = logger
    app.state.clock = clock
    app.state.jwt_verifier = jwt_verifier or JwtVerifier(config)
    register_error_handlers(app)
    app.include_router(router)
    app.include_router(learning_router)
    app.include_router(account_router)
    app.include_router(feedback_router)
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
        allow_methods=["GET", "POST"],
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
    )
    app.add_middleware(RequestContextMiddleware, logger=logger)
    return app
