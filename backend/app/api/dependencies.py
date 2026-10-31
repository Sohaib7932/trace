from collections.abc import Iterator
from typing import Annotated, cast

from fastapi import Depends, Request, Response
from sqlalchemy.orm import Session

from app.ai.interface import TutorProvider
from app.ai.providers.fake import FakeTutorProvider
from app.core.errors import ApplicationError
from app.core.settings import Settings
from app.db.health import SqlReadinessProbe
from app.db.learning import SqlLearningRepository
from app.db.session import Database
from app.domain.clock import Clock
from app.domain.learning import Credential
from app.repositories.learning import LearningRepository
from app.repositories.verification import NotesVerifier
from app.services.catalog import CatalogService
from app.services.health import HealthService
from app.services.identity import COOKIE_NAME, IdentityService
from app.services.learning import LearningService
from app.services.retrieval import RetrievalService
from app.services.verification import VerificationService
from app.verification.asgi_notes import AsgiNotesVerifier
from app.verification.asgi_tasks import AsgiTasksVerifier


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


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


def current_learner(
    request: Request, service: Annotated[IdentityService, Depends(get_identity_service)]
) -> Credential:
    return service.authenticate(request.cookies.get(COOKIE_NAME))


def get_catalog_service(
    repository: Annotated[LearningRepository, Depends(get_learning_repository)],
) -> CatalogService:
    return CatalogService(repository)


def get_learning_service(
    repository: Annotated[LearningRepository, Depends(get_learning_repository)],
    tutor: Annotated[TutorProvider, Depends(get_tutor_provider)],
    request: Request,
) -> LearningService:
    return LearningService(repository, tutor, cast(Clock, request.app.state.clock))


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
