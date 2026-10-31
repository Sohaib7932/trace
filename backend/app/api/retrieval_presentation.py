from datetime import datetime

from app.domain.retrieval import (
    RetrievalAttempt,
    RetrievalCheckpoint,
    checkpoint_status,
    question_for,
)
from app.schemas.learning import SessionResponse
from app.schemas.retrieval import (
    CheckpointSummary,
    JourneyResponse,
    PhaseResponse,
    QuestionOption,
    RetrievalAttemptResponse,
    RetrievalQuestionResponse,
    RetrievalResponse,
)
from app.services.retrieval import Journey


def present_checkpoint(
    checkpoint: RetrievalCheckpoint, now: datetime, count: int
) -> CheckpointSummary:
    return CheckpointSummary(
        id=checkpoint.id,
        transfer_session_id=checkpoint.transfer_session_id,
        ordinal=checkpoint.ordinal,
        due_at=checkpoint.due_at,
        completed_at=checkpoint.completed_at,
        status=checkpoint_status(checkpoint, now),
        attempt_count=count,
    )


def present_journey(journey: Journey) -> JourneyResponse:
    return JourneyResponse(
        server_time=journey.server_time,
        phases=[
            PhaseResponse(
                lesson_id=p.lesson_id,
                available=p.available,
                completed=p.completed,
                sessions=[SessionResponse.model_validate(s) for s in p.sessions],
                attempt_count=p.attempt_count,
            )
            for p in journey.phases
        ],
        checkpoints=[
            present_checkpoint(c, journey.server_time, count) for c, count in journey.checkpoints
        ],
        last_completed_at=journey.last_completed_at,
    )


def present_retrieval(
    checkpoint: RetrievalCheckpoint, attempts: list[RetrievalAttempt], now: datetime
) -> RetrievalResponse:
    summary = present_checkpoint(checkpoint, now, len(attempts))
    question = question_for(checkpoint) if summary.status != "upcoming" else None
    return RetrievalResponse(
        checkpoint=summary,
        server_time=now,
        question=RetrievalQuestionResponse(
            id=question.id,
            title=question.title,
            prompt=question.prompt,
            payload=question.payload,
            schema_code=question.schema_code,
            options=[
                QuestionOption.model_validate({"id": key, "label": label})
                for key, label in zip(("a", "b", "c"), question.options, strict=True)
            ],
        )
        if question
        else None,
        attempts=[RetrievalAttemptResponse.model_validate(a) for a in attempts],
    )
