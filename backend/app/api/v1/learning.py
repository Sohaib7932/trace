from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from app.api.dependencies import (
    current_learner,
    get_catalog_service,
    get_identity_service,
    get_learning_service,
    get_settings,
    get_verification_service,
    require_write_origin,
)
from app.api.presentation import present_lesson, present_progress, present_run
from app.core.settings import Settings
from app.domain.learning import Credential
from app.schemas.errors import ErrorResponse
from app.schemas.learning import (
    AttemptCreate,
    AttemptResponse,
    Contract,
    HintCreate,
    HintResponse,
    IdentityResponse,
    LessonResponse,
    PredictionCreate,
    PredictionResponse,
    ProgressResponse,
    RunResponse,
    SessionCreate,
    SessionResponse,
)
from app.services.catalog import CatalogService
from app.services.identity import COOKIE_NAME, COOKIE_PATH, IdentityService
from app.services.learning import LearningService
from app.services.verification import VerificationService

router = APIRouter(
    prefix="/api/v1",
    tags=["learning"],
    dependencies=[Depends(require_write_origin)],
    responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)},
)
Owner = Annotated[Credential, Depends(current_learner)]
Learning = Annotated[LearningService, Depends(get_learning_service)]
Identity = Annotated[IdentityService, Depends(get_identity_service)]
Key = Annotated[UUID, Header(alias="Idempotency-Key")]


@router.post(
    "/learners/anonymous", response_model=IdentityResponse, operation_id="create_anonymous"
)
def anonymous(
    request: Request,
    response: Response,
    service: Identity,
    settings: Annotated[Settings, Depends(get_settings)],
    body: Contract,
) -> IdentityResponse:
    credential, raw = service.bootstrap(request.cookies.get(COOKIE_NAME))
    if raw is not None:
        response.set_cookie(
            COOKIE_NAME,
            raw,
            max_age=settings.credential_lifetime_seconds,
            expires=credential.expires_at,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            path=COOKIE_PATH,
        )
    response.headers["Cache-Control"] = "no-store"
    return IdentityResponse(learner_id=credential.learner_id, expires_at=credential.expires_at)


@router.get("/learners/me", response_model=IdentityResponse, operation_id="get_learner")
def me(owner: Owner, response: Response) -> IdentityResponse:
    response.headers["Cache-Control"] = "no-store"
    return IdentityResponse(learner_id=owner.learner_id, expires_at=owner.expires_at)


@router.post("/learners/me/revoke", status_code=204, operation_id="revoke_learner")
def revoke(owner: Owner, service: Identity, response: Response, body: Contract) -> None:
    service.revoke(owner)
    response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH, httponly=True, samesite="lax")


@router.get("/lessons/{lesson_id}", response_model=LessonResponse, operation_id="get_lesson")
def lesson(
    lesson_id: str,
    service: Annotated[CatalogService, Depends(get_catalog_service)],
    version: Annotated[str | None, Query(pattern=r"^\d+\.\d+\.\d+$", max_length=32)] = None,
) -> LessonResponse:
    return present_lesson(service.retrieve(lesson_id, version))


@router.post(
    "/sessions", response_model=SessionResponse, status_code=201, operation_id="create_session"
)
def create_session(
    body: SessionCreate, owner: Owner, service: Learning, key: Key
) -> SessionResponse:
    return SessionResponse.model_validate(
        service.create_session(owner.learner_id, body.lesson_id, body.version, str(key))
    )


@router.get("/sessions/{session_id}", response_model=SessionResponse, operation_id="get_session")
def session(session_id: UUID, owner: Owner, service: Learning) -> SessionResponse:
    return SessionResponse.model_validate(service.progress(owner.learner_id, session_id).session)


@router.post(
    "/sessions/{session_id}/abandon", response_model=SessionResponse, operation_id="abandon_session"
)
def abandon(session_id: UUID, owner: Owner, service: Learning, body: Contract) -> SessionResponse:
    return SessionResponse.model_validate(service.abandon(owner.learner_id, session_id))


@router.post(
    "/sessions/{session_id}/prediction",
    response_model=PredictionResponse,
    status_code=201,
    operation_id="submit_prediction",
)
def predict(
    session_id: UUID, body: PredictionCreate, owner: Owner, service: Learning, key: Key
) -> PredictionResponse:
    return PredictionResponse.model_validate(
        service.predict(
            owner.learner_id, session_id, body.selected_answer, body.reasoning, str(key)
        )
    )


@router.get(
    "/sessions/{session_id}/prediction",
    response_model=PredictionResponse | None,
    operation_id="get_prediction",
)
def prediction(session_id: UUID, owner: Owner, service: Learning) -> PredictionResponse | None:
    original = service.progress(owner.learner_id, session_id).prediction
    return PredictionResponse.model_validate(original) if original else None


@router.post(
    "/sessions/{session_id}/attempts",
    response_model=AttemptResponse,
    status_code=201,
    operation_id="submit_attempt",
)
def attempt(
    session_id: UUID, body: AttemptCreate, owner: Owner, service: Learning, key: Key
) -> AttemptResponse:
    return AttemptResponse.model_validate(
        service.attempt(owner.learner_id, session_id, body.field_name, body.explanation, str(key))
    )


@router.get(
    "/sessions/{session_id}/attempts",
    response_model=list[AttemptResponse],
    operation_id="get_attempts",
)
def attempts(session_id: UUID, owner: Owner, service: Learning) -> list[AttemptResponse]:
    return [
        AttemptResponse.model_validate(a)
        for a in service.progress(owner.learner_id, session_id).attempts
    ]


@router.post(
    "/sessions/{session_id}/hints",
    response_model=HintResponse,
    status_code=201,
    operation_id="request_hint",
)
def hint(
    session_id: UUID, body: HintCreate, owner: Owner, service: Learning, key: Key
) -> HintResponse:
    return HintResponse.model_validate(
        service.hint(owner.learner_id, session_id, body.attempt_id, str(key))
    )


@router.post(
    "/sessions/{session_id}/attempts/{attempt_id}/verify",
    response_model=RunResponse,
    operation_id="verify_attempt",
)
def verify(
    session_id: UUID,
    attempt_id: UUID,
    owner: Owner,
    key: Key,
    service: Learning,
    verifier: Annotated[VerificationService, Depends(get_verification_service)],
    body: Contract,
) -> RunResponse:
    run = verifier.verify(owner.learner_id, session_id, attempt_id, str(key))
    progress = service.progress(owner.learner_id, session_id)
    checks = next(checks for saved, checks in progress.runs if saved.id == run.id)
    return present_run(run, checks)


@router.get(
    "/sessions/{session_id}/verifications",
    response_model=list[RunResponse],
    operation_id="get_verifications",
)
def verifications(session_id: UUID, owner: Owner, service: Learning) -> list[RunResponse]:
    return [
        present_run(run, checks)
        for run, checks in service.progress(owner.learner_id, session_id).runs
    ]


@router.get(
    "/sessions/{session_id}/progress", response_model=ProgressResponse, operation_id="get_progress"
)
def progress(
    session_id: UUID, owner: Owner, service: Learning, response: Response
) -> ProgressResponse:
    response.headers["Cache-Control"] = "no-store"
    return present_progress(service.progress(owner.learner_id, session_id))
