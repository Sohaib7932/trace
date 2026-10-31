from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.learning import router as learning_router
from app.api.v1.router import router
from app.core.errors import register_error_handlers
from app.core.logging import create_logger
from app.core.middleware import RequestContextMiddleware, RequestLimitsMiddleware
from app.core.settings import Settings
from app.db.migrations import expected_heads
from app.db.session import Database


def create_app(settings: Settings | None = None, database: Database | None = None) -> FastAPI:
    config = settings if settings is not None else Settings()
    logger = create_logger(config.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resource = database if database is not None else Database(config)
        app.state.database = resource
        try:
            yield
        finally:
            if database is None:
                resource.dispose()

    app = FastAPI(title="Trace API", version="0.1.0", lifespan=lifespan)
    app.state.settings = config
    app.state.migration_heads = expected_heads()
    app.state.logger = logger
    register_error_handlers(app)
    app.include_router(router)
    app.include_router(learning_router)
    # Request context wraps CORS, which wraps safe error/limit handling.
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
        allow_headers=["Content-Type", "X-Request-ID", "X-Trace-Client", "Idempotency-Key"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware, logger=logger)
    return app
