from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.ai.interface import TutorProvider
from app.domain.clock import Clock, as_utc, utc_now
from app.domain.learning import (
    Attempt,
    LearningError,
    LearningEvent,
    LearningSession,
    LessonVersion,
    Prediction,
    SessionState,
    TutorInteraction,
    VerificationCheck,
    VerificationRun,
    transition,
)
from app.domain.transfer import TRANSFER_ID
from app.repositories.learning import LearningRepository, LearningStore
from app.schemas.tutoring import HintRequest, TutorContext
from app.services.catalog import LESSON_ID


def owned(store: LearningStore, owner: UUID, session_id: UUID) -> LearningSession:
    session = store.owned_session(owner, session_id)
    if session is None:
        raise LearningError("not_found", "Session not found.")
    return session


def event(store: LearningStore, session_id: UUID, kind: str, reference: UUID | None) -> None:
    store.add_event(LearningEvent(uuid4(), session_id, kind, reference, datetime.now(UTC)))


@dataclass(frozen=True)
class Progress:
    session: LearningSession
    lesson: LessonVersion
    prediction: Prediction | None
    attempts: list[Attempt]
    hints: list[TutorInteraction]
    runs: list[tuple[VerificationRun, list[VerificationCheck]]]
    events: list[LearningEvent]


class LearningService:
    def __init__(
        self, repository: LearningRepository, tutor: TutorProvider, clock: Clock = utc_now
    ) -> None:
        self.repository, self.tutor, self.clock = repository, tutor, clock

    def create_session(
        self, owner: UUID, lesson_id: str, version: str, key: str
    ) -> LearningSession:
        with self.repository.write() as store:
            lesson = store.version(lesson_id, version)
            if lesson is None:
                raise LearningError("not_found", "Lesson not found.")
            existing = store.session_by_key(owner, key)
            if existing:
                if existing.lesson_version_id != lesson.id:
                    raise LearningError(
                        "conflict", "Idempotency key was used for another lesson version."
                    )
                return existing
            if lesson_id == TRANSFER_ID and not any(
                s.state == "completed"
                and store.version_by_id(s.lesson_version_id).lesson_id == LESSON_ID
                for s in store.owned_sessions(owner)
            ):
                raise LearningError(
                    "invalid_state", "Complete the original lesson before starting transfer."
                )
            session = LearningSession(
                uuid4(),
                owner,
                lesson.id,
                SessionState.AWAITING_PREDICTION,
                key,
                as_utc(self.clock()),
                None,
            )
            store.add_session(session)
            event(store, session.id, "session_created", None)
            return session

    def progress(self, owner: UUID, session_id: UUID) -> Progress:
        with self.repository.read() as store:
            session = owned(store, owner, session_id)
            runs = store.runs(session_id)
            return Progress(
                session,
                store.version_by_id(session.lesson_version_id),
                store.prediction(session_id),
                store.attempts(session_id),
                store.hints(session_id),
                [(run, store.checks(run.id)) for run in runs],
                store.events(session_id),
            )

    def predict(
        self, owner: UUID, session_id: UUID, answer: str, reasoning: str, key: str
    ) -> Prediction:
        with self.repository.write() as store:
            session = owned(store, owner, session_id)
            existing = store.prediction(session_id)
            if existing:
                if (existing.idempotency_key, existing.selected_answer, existing.reasoning) == (
                    key,
                    answer,
                    reasoning,
                ):
                    return existing
                raise LearningError(
                    "conflict", "The original prediction is locked and cannot be replaced."
                )
            state = transition(session.state, SessionState.READY_FOR_ATTEMPT)
            prediction = Prediction(
                uuid4(), session_id, answer, reasoning, key, as_utc(self.clock())
            )
            store.add_prediction(prediction)
            store.set_state(session_id, state)
            event(store, session_id, "prediction_submitted", prediction.id)
            return prediction

    def attempt(
        self, owner: UUID, session_id: UUID, field: str, explanation: str, key: str
    ) -> Attempt:
        with self.repository.write() as store:
            session = owned(store, owner, session_id)
            attempts = store.attempts(session_id)
            existing = next((a for a in attempts if a.idempotency_key == key), None)
            if existing:
                if (existing.field_name, existing.explanation) != (field, explanation):
                    raise LearningError(
                        "conflict", "Idempotency key was used for different attempt content."
                    )
                return existing
            lesson = store.version_by_id(session.lesson_version_id)
            choices = {"flat", "nested"} if lesson.lesson_id == TRANSFER_ID else {"body", "content"}
            if field not in choices:
                raise LearningError("unsupported_change", "Unsupported payload mapping.")
            if (
                lesson.lesson_id == TRANSFER_ID
                and field == "nested"
                and not any(
                    run.status == "failed"
                    and any(a.id == run.attempt_id and a.field_name == "flat" for a in attempts)
                    for run in store.runs(session_id)
                )
            ):
                raise LearningError(
                    "invalid_state",
                    (
                        "Investigate the original flat request's validation evidence be"
                        "fore proposing a nested correction."
                    ),
                )
            state = transition(session.state, SessionState.VERIFICATION_PENDING)
            attempt = Attempt(
                uuid4(),
                session_id,
                len(attempts) + 1,
                field,
                explanation,
                len(store.hints(session_id)),
                key,
                as_utc(self.clock()),
            )
            store.add_attempt(attempt)
            store.set_state(session_id, state)
            event(store, session_id, "attempt_submitted", attempt.id)
            return attempt

    def hint(
        self, owner: UUID, session_id: UUID, attempt_id: UUID | None, key: str
    ) -> TutorInteraction:
        with self.repository.write() as store:
            session = owned(store, owner, session_id)
            hints = store.hints(session_id)
            existing = next((h for h in hints if h.idempotency_key == key), None)
            if existing:
                if existing.attempt_id != attempt_id:
                    raise LearningError(
                        "conflict", "Idempotency key was used for another hint context."
                    )
                return existing
            if session.state in {
                SessionState.AWAITING_PREDICTION,
                SessionState.COMPLETED,
                SessionState.ABANDONED,
            }:
                raise LearningError(
                    "invalid_state",
                    (
                        "Commit a prediction before requesting guidance; terminal sessions"
                        " are read-only."
                    ),
                )
            attempts = store.attempts(session_id)
            attempt = next((a for a in attempts if a.id == attempt_id), None)
            if attempt_id is not None and attempt is None:
                raise LearningError("not_found", "Attempt not found.")
            if len(hints) >= 3:
                raise LearningError(
                    "hint_limit", "This session has reached its three guidance requests."
                )
            event(store, session_id, "hint_requested", attempt_id)
            text: str | None = None
            status = "delivered"
            try:
                result = self.tutor.generate_hint(
                    HintRequest(
                        context=TutorContext(
                            scenario=store.version_by_id(session.lesson_version_id).public_content[
                                "scenario"
                            ],
                            learner_attempt=attempt.field_name
                            if attempt
                            else "Prediction submitted",
                        ),
                        level=len(hints) + 1,
                    )
                )
                if result.source != "test_fixture":
                    raise ValueError("Module 2 accepts only the configured fake fixture")
                text = result.text
            except Exception:
                status = "error"  # Persist a failed request, never a guessed provider response.
            hint = TutorInteraction(
                uuid4(),
                session_id,
                attempt_id,
                len(hints) + 1,
                text,
                status,
                key,
                as_utc(self.clock()),
            )
            store.add_hint(hint)
            event(store, session_id, f"hint_{status}", hint.id)
            return hint

    def abandon(self, owner: UUID, session_id: UUID) -> LearningSession:
        with self.repository.write() as store:
            session = owned(store, owner, session_id)
            if session.state != SessionState.ABANDONED:
                state = transition(session.state, SessionState.ABANDONED)
                store.set_state(session_id, state)
                event(store, session_id, "session_abandoned", None)
        return self.progress(owner, session_id).session
