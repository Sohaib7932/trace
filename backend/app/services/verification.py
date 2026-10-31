import json
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from app.domain.clock import Clock, as_utc, utc_now
from app.domain.learning import (
    NOTE_CONTENT,
    NOTE_TITLE,
    Attempt,
    Evaluation,
    LearningError,
    LessonVersion,
    Observation,
    SessionState,
    VerificationCheck,
    VerificationRun,
    evaluate,
    response_matches_fixture,
    transition,
)
from app.domain.transfer import TRANSFER_ID, TaskObservation, evaluate_transfer
from app.repositories.learning import LearningRepository, LearningStore
from app.repositories.verification import NotesVerifier, TasksVerifier
from app.services.learning import event, owned
from app.services.retrieval import schedule_checkpoints
from app.services.task_evidence import task_checks


class VerificationService:
    def __init__(
        self,
        repository: LearningRepository,
        verifier: NotesVerifier,
        timeout_seconds: float,
        tasks_verifier: TasksVerifier | None = None,
        clock: Clock = utc_now,
    ) -> None:
        self.repository, self.verifier = repository, verifier
        self.tasks_verifier, self.clock = tasks_verifier, clock
        self.recovery_after = timedelta(seconds=max(60, timeout_seconds * 3))

    def verify(self, owner: UUID, session_id: UUID, attempt_id: UUID, key: str) -> VerificationRun:
        run, attempt, lesson = self._reserve(owner, session_id, attempt_id, key)
        expected_field = lesson.expected_field
        is_transfer = lesson.lesson_id == TRANSFER_ID
        if run.status != "pending":
            return run
        observation: Observation | None = None
        task_observation: TaskObservation | None = None
        try:
            if is_transfer:
                if self.tasks_verifier is None:
                    raise RuntimeError("Task verifier is not configured")
                task_observation = self.tasks_verifier.observe(run.id, attempt.field_name)
                result = evaluate_transfer(attempt.field_name, expected_field, task_observation)
            else:
                observation = self.verifier.observe(run.id, attempt.field_name)
                result = evaluate(attempt.field_name, expected_field, observation)
        except Exception:
            result = Evaluation(
                "error", "Verification could not finish. This is not a learner mistake."
            )
        at = as_utc(self.clock())
        with self.repository.write() as store:
            session = owned(store, owner, session_id)
            if is_transfer:
                task_checks(store, run.id, task_observation, at)
            else:
                self._checks(store, run.id, attempt.field_name, expected_field, observation, at)
            store.finish_run(run.id, result.status, result.feedback, at)
            if session.state != SessionState.ABANDONED and result.status != "error":
                target = (
                    SessionState.COMPLETED
                    if result.status == "passed"
                    else SessionState.NEEDS_REVISION
                )
                state = transition(session.state, target, verified=result.status == "passed")
                store.set_state(session_id, state, at if result.status == "passed" else None)
                if is_transfer and result.status == "passed":
                    schedule_checkpoints(store, session, at)
            event(store, session_id, f"verification_{result.status}", run.id)
        return replace(run, status=result.status, feedback=result.feedback, completed_at=at)

    def _reserve(
        self, owner: UUID, session_id: UUID, attempt_id: UUID, key: str
    ) -> tuple[VerificationRun, Attempt, LessonVersion]:
        with self.repository.write() as store:
            session = owned(store, owner, session_id)
            attempts = store.attempts(session_id)
            attempt = next((a for a in attempts if a.id == attempt_id), None)
            if attempt is None:
                raise LearningError("not_found", "Attempt not found.")
            lesson = store.version_by_id(session.lesson_version_id)
            runs = [r for r in store.runs(session_id) if r.attempt_id == attempt_id]
            existing = next((r for r in runs if r.idempotency_key == key), None)
            if existing and existing.status != "pending":
                return existing, attempt, lesson
            last = runs[-1] if runs else None
            if last and last.status == "pending":
                if as_utc(self.clock()) - last.created_at < self.recovery_after:
                    raise LearningError(
                        "conflict", "Verification is already running. Refresh its saved evidence."
                    )
                at = as_utc(self.clock())
                message = (
                    "An earlier verification did not finish before its recovery "
                    "deadline. No learner grade was assigned."
                )
                store.add_check(
                    VerificationCheck(
                        uuid4(),
                        last.id,
                        "execution",
                        False,
                        "finished verification",
                        "no finished result observed before recovery",
                        "server_lifecycle",
                        at,
                    )
                )
                store.finish_run(last.id, "error", message, at)
                event(store, session_id, "verification_error", last.id)
                last = replace(last, status="error", feedback=message, completed_at=at)
                if existing and existing.id == last.id:
                    existing = last
            if existing:
                return existing, attempt, lesson
            if last and last.status in {"passed", "failed"}:
                return (
                    last,
                    attempt,
                    lesson,
                )  # Repeated completed verification never creates another runtime row.
            if session.state != SessionState.VERIFICATION_PENDING or attempts[-1].id != attempt.id:
                raise LearningError(
                    "invalid_state", "Only the current pending attempt can be verified."
                )
            run = VerificationRun(
                uuid4(), session_id, attempt_id, "pending", key, as_utc(self.clock())
            )
            store.add_run(run)
            event(store, session_id, "verification_started", run.id)
            return run, attempt, lesson

    @staticmethod
    def _checks(
        store: LearningStore,
        run_id: UUID,
        field: str,
        expected_field: str,
        observed: Observation | None,
        at: datetime,
    ) -> None:
        if observed is None:
            store.add_check(
                VerificationCheck(
                    uuid4(),
                    run_id,
                    "execution",
                    False,
                    "completed request and fresh read",
                    "dependency_or_execution_failure",
                    "verifier",
                    at,
                )
            )
            return
        rows = observed.notes
        stored = (
            json.dumps(
                [{"id": str(n.id), "title": n.title, "content": n.content} for n in rows],
                sort_keys=True,
            )
            if rows is not None
            else "unavailable"
        )
        definitions = [
            (
                "http_status",
                observed.http_status == 201,
                "201",
                str(observed.http_status) if observed.http_status is not None else "unavailable",
                "asgi_http",
            ),
            (
                "api_response",
                response_matches_fixture(observed),
                "validated note response",
                observed.response_json,
                "asgi_http",
            ),
            (
                "validation",
                field == expected_field
                and observed.http_status == 201
                and not observed.validation_codes,
                "request accepted by receiving schema",
                json.dumps(observed.validation_codes),
                "asgi_http",
            ),
            (
                "row_count",
                rows is not None and len(rows) == 1,
                "1",
                str(len(rows)) if rows is not None else "unavailable",
                "fresh_database_read",
            ),
            (
                "stored_values",
                rows is not None
                and len(rows) == 1
                and rows[0].title == NOTE_TITLE
                and rows[0].content == NOTE_CONTENT
                and str(rows[0].id) == observed.response_note_id,
                json.dumps({"title": NOTE_TITLE, "content": NOTE_CONTENT}, sort_keys=True),
                stored,
                "fresh_database_read",
            ),
        ]
        for code, matched, expected, actual, source in definitions:
            store.add_check(
                VerificationCheck(uuid4(), run_id, code, matched, expected, actual, source, at)
            )
