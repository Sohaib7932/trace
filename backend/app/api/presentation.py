from app.domain.learning import LessonVersion, VerificationCheck, VerificationRun
from app.schemas.learning import (
    AttemptResponse,
    CheckResponse,
    EventResponse,
    EvidenceSummary,
    HintResponse,
    LessonResponse,
    PredictionResponse,
    ProgressResponse,
    RunResponse,
    SessionResponse,
)
from app.services.learning import Progress


def present_lesson(version: LessonVersion) -> LessonResponse:
    # Explicit public projection. Never serialize the internal version object wholesale.
    return LessonResponse(
        id=version.lesson_id,
        version_id=version.id,
        version=version.version,
        **version.public_content,
    )


def present_run(run: VerificationRun, checks: list[VerificationCheck]) -> RunResponse:
    response = RunResponse.model_validate(run)
    response.checks = [CheckResponse.model_validate(check) for check in checks]
    return response


def present_progress(progress: Progress) -> ProgressResponse:
    passed = next((run for run, _ in progress.runs if run.status == "passed"), None)
    success = next(
        (attempt for attempt in progress.attempts if passed and attempt.id == passed.attempt_id),
        None,
    )
    delivered = [hint for hint in progress.hints if hint.status == "delivered"]
    prediction_correct = (
        progress.prediction.selected_answer == progress.lesson.prediction_answer
        if progress.prediction and progress.attempts
        else None
    )
    return ProgressResponse(
        session=SessionResponse.model_validate(progress.session),
        lesson=present_lesson(progress.lesson),
        prediction=PredictionResponse.model_validate(progress.prediction)
        if progress.prediction
        else None,
        attempts=[AttemptResponse.model_validate(a) for a in progress.attempts],
        hints=[HintResponse.model_validate(h) for h in progress.hints],
        verifications=[present_run(run, checks) for run, checks in progress.runs],
        events=[EventResponse.model_validate(e) for e in progress.events],
        summary=EvidenceSummary(
            attempt_count=len(progress.attempts),
            hint_request_count=max(len(progress.hints), progress.hint_request_count),
            hints_delivered=len(delivered),
            verification_errors=sum(r.status == "error" for r, _ in progress.runs),
            prediction_correct=prediction_correct,
            correct_after_revision=bool(success and success.number > 1),
            hint_assisted_correction=bool(
                success and any(h.created_at < success.created_at for h in delivered)
            ),
        ),
    )
