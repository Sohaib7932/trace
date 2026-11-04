"""Learner-requested lessons. Signed-in account with the learner role; private to the owner."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response

from app.api.custom_lessons_runtime import CustomLessonRuntime
from app.api.dependencies import current_account, require_write_origin
from app.core.errors import ApplicationError
from app.domain.accounts import AuthenticatedAccount
from app.schemas.custom_lessons import (
    AnswerCreate,
    AnswerResult,
    CustomLessonList,
    CustomLessonRequestCreate,
    CustomLessonRequestView,
    CustomLessonView,
    LanguageList,
)
from app.schemas.errors import ErrorResponse
from app.services.custom_lessons import Owner

router = APIRouter(
    prefix="/api/v1/custom-lessons",
    tags=["custom-lessons"],
    dependencies=[Depends(require_write_origin)],
    responses={
        code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 413, 422, 429, 500, 503)
    },
)

Key = Annotated[UUID, Header(alias="Idempotency-Key")]


def get_runtime(request: Request) -> CustomLessonRuntime:
    runtime = getattr(request.app.state, "custom_lessons", None)
    if not isinstance(runtime, CustomLessonRuntime):
        raise ApplicationError("custom_lessons_unavailable", "Custom lessons are unavailable.", 503)
    return runtime


def owner(auth: Annotated[AuthenticatedAccount, Depends(current_account)]) -> Owner:
    auth.account.require_role("learner")
    return Owner(auth.account.id)


Runtime = Annotated[CustomLessonRuntime, Depends(get_runtime)]
Learner = Annotated[Owner, Depends(owner)]


@router.get("/languages", response_model=LanguageList, operation_id="list_custom_lesson_languages")
def languages(runtime: Runtime, _: Learner) -> LanguageList:
    """Languages Trace can draft lessons in, and how their answers are checked."""
    return runtime.service.languages()


@router.post(
    "/requests",
    response_model=CustomLessonRequestView,
    status_code=202,
    operation_id="create_custom_lesson_request",
)
def create_request(
    body: CustomLessonRequestCreate, key: Key, runtime: Runtime, learner: Learner
) -> CustomLessonRequestView:
    """Queue generation and return immediately. Same Idempotency-Key + body replays."""
    view, created = runtime.service.create_request(learner, body, key)
    if created:
        runtime.runner.submit(view.id)
    return view


@router.get(
    "/requests/{request_id}",
    response_model=CustomLessonRequestView,
    operation_id="get_custom_lesson_request",
)
def get_request(request_id: UUID, runtime: Runtime, learner: Learner) -> CustomLessonRequestView:
    return runtime.service.get_request(learner, request_id)


@router.post(
    "/requests/{request_id}/cancel",
    response_model=CustomLessonRequestView,
    operation_id="cancel_custom_lesson_request",
)
def cancel_request(request_id: UUID, runtime: Runtime, learner: Learner) -> CustomLessonRequestView:
    return runtime.service.cancel_request(learner, request_id)


@router.get("", response_model=CustomLessonList, operation_id="list_custom_lessons")
def list_lessons(runtime: Runtime, learner: Learner) -> CustomLessonList:
    return runtime.service.list_lessons(learner)


@router.get("/{lesson_id}", response_model=CustomLessonView, operation_id="get_custom_lesson")
def get_lesson(lesson_id: UUID, runtime: Runtime, learner: Learner) -> CustomLessonView:
    """The lesson without answer keys. Explanations appear only for answered challenges."""
    return runtime.service.get_lesson(learner, lesson_id)


@router.delete("/{lesson_id}", status_code=204, operation_id="delete_custom_lesson")
def delete_lesson(lesson_id: UUID, runtime: Runtime, learner: Learner) -> Response:
    runtime.service.delete_lesson(learner, lesson_id)
    return Response(status_code=204)


@router.post(
    "/{lesson_id}/challenges/{challenge_id}/answers",
    response_model=AnswerResult,
    operation_id="answer_custom_lesson_challenge",
)
def answer(
    lesson_id: UUID,
    challenge_id: UUID,
    body: AnswerCreate,
    key: Key,
    runtime: Runtime,
    learner: Learner,
) -> AnswerResult:
    """Checked on the server against the stored key; the key itself is never returned."""
    return runtime.service.answer(learner, lesson_id, challenge_id, body, key)
