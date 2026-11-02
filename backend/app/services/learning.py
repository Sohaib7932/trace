from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
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
from app.domain.tutoring_operations import HintOperation, hint_request_count
from app.repositories.learning import LearningRepository, LearningStore
from app.schemas.tutoring import HintRequest, TutorContext, TutorMessage
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
    hint_request_count: int = 0


class LearningService:
    def __init__(
        self,
        repository: LearningRepository,
        tutor: TutorProvider,
        clock: Clock = utc_now,
        *,
        hint_timeout_seconds: float = 30,
    ) -> None:
        self.repository, self.tutor, self.clock = repository, tutor, clock
        if (
            isinstance(hint_timeout_seconds, bool)
            or not isfinite(hint_timeout_seconds)
            or not 0 < hint_timeout_seconds <= 120
        ):
            raise ValueError("Hint operation timeout must be bounded between 0 and 120 seconds")
        self.hint_timeout = timedelta(seconds=hint_timeout_seconds)

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
            hints = store.hints(session_id)
            return Progress(
                session,
                store.version_by_id(session.lesson_version_id),
                store.prediction(session_id),
                store.attempts(session_id),
                hints,
                [(run, store.checks(run.id)) for run in runs],
                store.events(session_id),
                hint_request_count(hints, store.hint_operations(session_id)),
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
                hint_request_count(store.hints(session_id), store.hint_operations(session_id)),
                key,
                as_utc(self.clock()),
            )
            store.add_attempt(attempt)
            store.set_state(session_id, state)
            event(store, session_id, "attempt_submitted", attempt.id)
            return attempt

    def hint(
        self,
        owner: UUID,
        session_id: UUID,
        attempt_id: UUID | None,
        key: str,
        *,
        authorization_expires_at: datetime | None = None,
    ) -> TutorInteraction:
        authorization_deadline = (
            as_utc(authorization_expires_at) if authorization_expires_at is not None else None
        )
        self._require_authorization(authorization_deadline)
        reservation = self._reserve_hint(owner, session_id, attempt_id, key, authorization_deadline)
        if isinstance(reservation, LearningError):
            raise reservation
        if isinstance(reservation, TutorInteraction):
            return reservation
        operation, request = reservation
        text: str | None = None
        try:
            # No learner transaction or write gate is held across the provider call.
            # A worker resumed after its committed deadline must not start external work.
            if as_utc(self.clock()) < operation.deadline_at:
                received = self.tutor.generate_hint(request)
                result = TutorMessage.model_validate(received.model_dump(warnings=False))
                if result.source != "test_fixture":
                    raise ValueError("Only configured fixture guidance is currently permitted")
                text = result.text
        except Exception:
            pass  # Failed requests persist an error, never provider diagnostics or guessed text.
        return self._finalize_hint(owner, operation, text, authorization_deadline)

    def _require_authorization(self, deadline: datetime | None) -> None:
        if deadline is not None and deadline <= as_utc(self.clock()):
            raise LearningError("unauthenticated", "The learner authorization has expired.")

    @staticmethod
    def _hint_allowed(session: LearningSession) -> bool:
        return session.state not in {
            SessionState.AWAITING_PREDICTION,
            SessionState.COMPLETED,
            SessionState.ABANDONED,
        }

    def _reserve_hint(
        self,
        owner: UUID,
        session_id: UUID,
        attempt_id: UUID | None,
        key: str,
        authorization_deadline: datetime | None,
    ) -> tuple[HintOperation, HintRequest] | TutorInteraction | LearningError:
        with self.repository.write() as store:
            self._require_authorization(authorization_deadline)
            session = owned(store, owner, session_id)
            hints = store.hints(session_id)
            existing = next((h for h in hints if h.idempotency_key == key), None)
            if existing:
                if existing.attempt_id != attempt_id:
                    raise LearningError(
                        "conflict", "Idempotency key was used for another hint context."
                    )
                return existing
            operations = store.hint_operations(session_id)
            now = as_utc(self.clock())
            existing_operation = next((o for o in operations if o.idempotency_key == key), None)
            if existing_operation is not None:
                if existing_operation.attempt_id != attempt_id:
                    raise LearningError(
                        "conflict", "Idempotency key was used for another hint context."
                    )
                if existing_operation.status != "pending":
                    raise LearningError("dependency_unavailable", "Saved guidance is unavailable.")
                if existing_operation.deadline_at <= now or not self._hint_allowed(session):
                    return self._complete_hint(store, existing_operation, None, now)
                raise LearningError(
                    "conflict", "Guidance is already running. Retry the same request."
                )
            if not self._hint_allowed(session):
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
            pending = next((o for o in operations if o.status == "pending"), None)
            if pending is not None:
                if pending.deadline_at > now:
                    raise LearningError(
                        "conflict", "Guidance is already running. Retry the same request."
                    )
                hints.append(self._complete_hint(store, pending, None, now))
            count = hint_request_count(hints, operations)
            if count >= 3:
                # Returning the rejection commits any expired-operation recovery first.
                # Raising inside the context would roll that preserved error back.
                return LearningError(
                    "hint_limit", "This session has reached its three guidance requests."
                )
            deadline = now + self.hint_timeout
            if authorization_deadline is not None:
                deadline = min(deadline, authorization_deadline)
            operation = HintOperation(
                uuid4(),
                session_id,
                attempt_id,
                count + 1,
                key,
                now,
                deadline,
            )
            request = HintRequest(
                context=TutorContext(
                    scenario=store.version_by_id(session.lesson_version_id).public_content[
                        "scenario"
                    ],
                    learner_attempt=attempt.field_name if attempt else "Prediction submitted",
                ),
                level=operation.sequence,
            )
            store.add_hint_operation(operation)
            event(store, session_id, "hint_requested", attempt_id)
            return operation, request

    @staticmethod
    def _complete_hint(
        store: LearningStore,
        operation: HintOperation,
        text: str | None,
        at: datetime,
    ) -> TutorInteraction:
        hint = TutorInteraction(
            operation.id,
            operation.session_id,
            operation.attempt_id,
            operation.sequence,
            text,
            "delivered" if text is not None else "error",
            operation.idempotency_key,
            at,
        )
        store.add_hint(hint)
        store.finish_hint_operation(operation.id, at)
        event(store, operation.session_id, f"hint_{hint.status}", hint.id)
        return hint

    def _finalize_hint(
        self,
        owner: UUID,
        operation: HintOperation,
        text: str | None,
        authorization_deadline: datetime | None,
    ) -> TutorInteraction:
        with self.repository.write() as store:
            at = as_utc(self.clock())
            authorization_expired = (
                authorization_deadline is not None and authorization_deadline <= at
            )
            session = owned(store, owner, operation.session_id)
            current = next(
                (o for o in store.hint_operations(session.id) if o.id == operation.id), None
            )
            if current is None:
                raise LearningError(
                    "dependency_unavailable", "Guidance reservation is unavailable."
                )
            if current.status == "finalized":
                saved = next((h for h in store.hints(session.id) if h.id == current.id), None)
                if saved is None:
                    raise LearningError("dependency_unavailable", "Saved guidance is unavailable.")
            else:
                if (
                    current.deadline_at <= at
                    or authorization_expired
                    or not self._hint_allowed(session)
                ):
                    text = None
                saved = self._complete_hint(store, current, text, at)
        # Commit the failed request before denying a response to expired authorization.
        if authorization_expired:
            raise LearningError("unauthenticated", "The learner authorization has expired.")
        return saved

    def abandon(self, owner: UUID, session_id: UUID) -> LearningSession:
        with self.repository.write() as store:
            session = owned(store, owner, session_id)
            if session.state != SessionState.ABANDONED:
                state = transition(session.state, SessionState.ABANDONED)
                store.set_state(session_id, state)
                event(store, session_id, "session_abandoned", None)
        return self.progress(owner, session_id).session
