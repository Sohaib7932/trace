from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from app.domain.clock import Clock, as_utc, utc_now
from app.domain.learning import LearningError, LearningSession
from app.domain.retrieval import (
    QUESTIONS,
    RetrievalAttempt,
    RetrievalCheckpoint,
    checkpoint_status,
    due_at,
    question_for,
)
from app.domain.transfer import TRANSFER_ID
from app.repositories.learning import LearningRepository, LearningStore
from app.services.catalog import LESSON_ID


def schedule_checkpoints(store: LearningStore, session: LearningSession, at: datetime) -> None:
    existing = {
        c.ordinal
        for c in store.checkpoints(session.learner_id)
        if c.transfer_session_id == session.id
    }
    for ordinal, question in enumerate(QUESTIONS, 1):
        if ordinal not in existing:
            store.add_checkpoint(
                RetrievalCheckpoint(
                    uuid4(),
                    session.id,
                    ordinal,
                    question.id,
                    question.content_hash,
                    due_at(at, ordinal),
                    as_utc(at),
                )
            )


@dataclass(frozen=True)
class Phase:
    lesson_id: str
    available: bool
    completed: bool
    sessions: list[LearningSession]
    attempt_count: int


@dataclass(frozen=True)
class Journey:
    server_time: datetime
    phases: list[Phase]
    checkpoints: list[tuple[RetrievalCheckpoint, int]]
    last_completed_at: datetime | None


class RetrievalService:
    def __init__(self, repository: LearningRepository, clock: Clock = utc_now) -> None:
        self.repository, self.clock = repository, clock

    def journey(self, owner: UUID) -> Journey:
        now = as_utc(self.clock())
        with self.repository.read() as store:
            sessions = store.owned_sessions(owner)
            grouped = {
                lesson_id: [
                    s
                    for s in sessions
                    if store.version_by_id(s.lesson_version_id).lesson_id == lesson_id
                ]
                for lesson_id in (LESSON_ID, TRANSFER_ID)
            }
            original_done = any(s.state == "completed" for s in grouped[LESSON_ID])
            phases = [
                Phase(
                    lesson_id,
                    lesson_id == LESSON_ID or original_done,
                    any(s.state == "completed" for s in group),
                    group,
                    sum(len(store.attempts(s.id)) for s in group),
                )
                for lesson_id, group in grouped.items()
            ]
            checkpoints = store.checkpoints(owner)
            completed = [s.completed_at for s in sessions if s.completed_at is not None]
            completed.extend(c.completed_at for c in checkpoints if c.completed_at is not None)
            return Journey(
                now,
                phases,
                [(c, len(store.retrieval_attempts(c.id))) for c in checkpoints],
                max(completed) if completed else None,
            )

    def retrieve(
        self, owner: UUID, checkpoint_id: UUID
    ) -> tuple[RetrievalCheckpoint, list[RetrievalAttempt], datetime]:
        with self.repository.read() as store:
            checkpoint = self._owned(store, owner, checkpoint_id)
            return checkpoint, store.retrieval_attempts(checkpoint.id), as_utc(self.clock())

    @staticmethod
    def _owned(store: LearningStore, owner: UUID, checkpoint_id: UUID) -> RetrievalCheckpoint:
        checkpoint = next((c for c in store.checkpoints(owner) if c.id == checkpoint_id), None)
        if checkpoint is None:
            raise LearningError("not_found", "Retrieval checkpoint not found.")
        return checkpoint

    def submit(
        self, owner: UUID, checkpoint_id: UUID, selection: str, reasoning: str, key: str
    ) -> RetrievalAttempt:
        with self.repository.write() as store:
            checkpoint = self._owned(store, owner, checkpoint_id)
            attempts = store.retrieval_attempts(checkpoint_id)
            existing = next((a for a in attempts if a.idempotency_key == key), None)
            if existing:
                if (existing.selection, existing.reasoning) != (selection, reasoning):
                    raise LearningError(
                        "conflict", "Idempotency key was used for a different retrieval response."
                    )
                return existing
            now = as_utc(self.clock())
            if checkpoint_status(checkpoint, now) != "due":
                raise LearningError(
                    "invalid_state", "This checkpoint is not due or is already completed."
                )
            if selection not in {"a", "b", "c"}:
                raise LearningError("unsupported_change", "Choose one of the question's options.")
            question = question_for(checkpoint)
            correct = selection == question.answer
            feedback = ("Correct. " if correct else "Review the contract. ") + question.explanation
            attempt = RetrievalAttempt(
                uuid4(),
                checkpoint_id,
                len(attempts) + 1,
                selection,
                reasoning,
                correct,
                feedback,
                key,
                now,
            )
            store.add_retrieval_attempt(attempt)
            if correct:
                store.complete_checkpoint(checkpoint.id, now)
            return attempt
