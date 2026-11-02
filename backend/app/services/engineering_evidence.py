"""Read-only, owner-scoped observations of legacy learner records.

This service accepts identifiers and bounds, never submitted evidence. It neither
grades arbitrary code nor writes a second history beside the immutable sources.
"""

import json
from datetime import datetime
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError

from app.domain.clock import as_utc
from app.domain.learning import (
    NOTE_CONTENT,
    NOTE_TITLE,
    Attempt,
    LearningError,
    LearningSession,
    LessonVersion,
    Observation,
    TutorInteraction,
    VerificationCheck,
    VerificationRun,
    evaluate,
    response_matches_fixture,
)
from app.domain.retrieval import QUESTIONS, RetrievalCheckpoint, due_at, question_for
from app.domain.transfer import (
    TASK_PRIORITY,
    TASK_TITLE,
    TRANSFER_ID,
    TaskObservation,
    evaluate_transfer,
    response_matches_task,
    task_values_match,
)
from app.repositories.learning import LearningRepository, LearningStore
from app.schemas.engineering_evidence import (
    AssistanceContext,
    Competency,
    EngineeringEvidenceBatch,
    EngineeringObservation,
    EvidenceQuery,
    HintEvidence,
    LessonPin,
    ObservedCheck,
    RetrievalEvidence,
    RetrievalQuestionPin,
    SourceReference,
    coverage_profile,
)
from app.services.catalog import (
    LESSON_ID,
    PUBLIC_CONTENT,
    TRANSFER_CONTENT,
    lesson_hash,
    transfer_hash,
)

SCHEMA_VERSION = "engineering-evidence-v1"
_FIVE = {"http_status", "api_response", "validation", "row_count", "stored_values"}


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("Invalid authoritative evidence source")


def _ref(kind: str, identity: UUID) -> SourceReference:
    return SourceReference.model_validate({"kind": kind, "record_id": identity})


def _identity(event: str, source: SourceReference) -> UUID:
    return uuid5(NAMESPACE_URL, f"trace:{SCHEMA_VERSION}:{event}:{source.kind}:{source.record_id}")


def _pin(session: LearningSession, lesson: LessonVersion) -> LessonPin:
    _require(lesson.id == session.lesson_version_id and lesson.version == "1.0.0")
    if lesson.lesson_id == LESSON_ID:
        digest = lesson_hash(lesson.public_content, lesson.expected_field, lesson.prediction_answer)
        expected = lesson_hash(PUBLIC_CONTENT, "content", "rejected")
    else:
        _require(lesson.lesson_id == TRANSFER_ID)
        _require((lesson.expected_field, lesson.prediction_answer) == ("nested", "rejected"))
        digest, expected = transfer_hash(lesson.public_content), transfer_hash(TRANSFER_CONTENT)
    _require(digest == lesson.content_hash == expected)
    return LessonPin(
        version_id=lesson.id,
        lesson_id=lesson.lesson_id,  # type: ignore[arg-type]
        version="1.0.0",
        content_hash=digest,
    )


class _Projection:
    """One consistent repository read, with no retained mutable source objects."""

    def __init__(self, store: LearningStore, query: EvidenceQuery) -> None:
        self.store, self.query = store, query
        session = store.owned_session(query.owner_learner_id, query.session_id)
        if session is None:
            raise LearningError("not_found", "Session not found.")
        _require((session.id, session.learner_id) == (query.session_id, query.owner_learner_id))
        self.session = session
        self.lesson = store.version_by_id(session.lesson_version_id)
        self.pin = _pin(session, self.lesson)
        self.started = as_utc(session.created_at)
        self.seen: set[tuple[str, UUID]] = set()
        self.observations: list[EngineeringObservation] = []
        self.hint_events: list[HintEvidence] = []
        self.retrieval_events: list[RetrievalEvidence] = []
        self.attempts = store.attempts(session.id)
        self.runs = store.runs(session.id)
        self.hints = store.hints(session.id)
        self.operations = store.hint_operations(session.id)
        self.by_attempt = {a.id: a for a in self.attempts}
        self.checks: dict[UUID, tuple[ObservedCheck, ...]] = {}

    def record(self, kind: str, identity: UUID, at: datetime) -> None:
        _require(isinstance(identity, UUID) and as_utc(at) >= self.started)
        key = kind, identity
        _require(key not in self.seen)
        self.seen.add(key)
        if len(self.seen) > 10000:
            raise LearningError("evidence_limit", "The source history exceeds the evidence limit.")

    def visible(self, at: datetime) -> bool:
        return self.query.start_at <= as_utc(at) < self.query.end_at

    def assistance(self, at: datetime) -> AssistanceContext:
        requested = sorted(
            (o for o in self.operations if as_utc(o.created_at) < at),
            key=lambda o: (o.created_at, str(o.id)),
        )
        delivered = sorted(
            (h for h in self.hints if h.status == "delivered" and as_utc(h.created_at) < at),
            key=lambda h: (h.created_at, str(h.id)),
        )
        return AssistanceContext(
            category="tutor_assisted" if delivered else "unknown",
            requested_before=tuple(_ref("hint_operation", o.id) for o in requested),
            delivered_before=tuple(_ref("tutor_interaction", h.id) for h in delivered),
        )

    def emit(
        self,
        event: str,
        competency: Competency,
        outcome: str,
        source: SourceReference,
        at: datetime,
        *,
        related: tuple[SourceReference, ...] = (),
        checks: tuple[ObservedCheck, ...] = (),
        action_at: datetime | None = None,
    ) -> None:
        if not self.visible(at):
            return
        observation = EngineeringObservation.model_validate(
            {
                "id": _identity(event, source),
                "schema_version": SCHEMA_VERSION,
                "owner_learner_id": self.session.learner_id,
                "session_id": self.session.id,
                "lesson": self.pin,
                "competency": competency,
                "event_type": event,
                "outcome": outcome,
                "basis": "indirect" if event == "debugging_recovery_observed" else "direct",
                "occurred_at": as_utc(at),
                "source": source,
                "related_sources": related,
                "assistance": self.assistance(as_utc(action_at or at)),
                "checks": checks,
            }
        )
        self.observations.append(observation)

    def hint_event(
        self,
        kind: Literal["hint_operation", "tutor_interaction"],
        identity: UUID,
        at: datetime,
        outcome: str,
    ) -> None:
        if self.visible(at):
            source = _ref(kind, identity)
            event = "hint_requested" if kind == "hint_operation" else "hint_finalized"
            self.hint_events.append(
                HintEvidence.model_validate(
                    {
                        "id": _identity(event, source),
                        "schema_version": SCHEMA_VERSION,
                        "owner_learner_id": self.session.learner_id,
                        "session_id": self.session.id,
                        "lesson": self.pin,
                        "event_type": event,
                        "outcome": outcome,
                        "occurred_at": as_utc(at),
                        "source": source,
                    }
                )
            )

    def validate_attempts(self) -> None:
        numbers: set[int] = set()
        choices = (
            {"flat", "nested"} if self.lesson.lesson_id == TRANSFER_ID else {"body", "content"}
        )
        for attempt in self.attempts:
            self.record("attempt", attempt.id, attempt.created_at)
            _require(
                attempt.session_id == self.session.id
                and type(attempt.number) is int
                and attempt.number >= 1
            )
            _require(attempt.number not in numbers and attempt.field_name in choices)
            _require(type(attempt.hints_before) is int and 0 <= attempt.hints_before <= 3)
            numbers.add(attempt.number)

    def validate_hints(self) -> None:
        hints: dict[UUID, TutorInteraction] = {}
        sequences: set[int] = set()
        for hint in self.hints:
            self.record("tutor_interaction", hint.id, hint.created_at)
            _require(
                hint.session_id == self.session.id
                and type(hint.sequence) is int
                and hint.sequence in {1, 2, 3}
            )
            _require(hint.sequence not in sequences and hint.interaction_type == "hint")
            _require(hint.status in {"delivered", "error"})
            if hint.status == "delivered":
                _require(
                    isinstance(hint.text, str)
                    and bool(hint.text.strip())
                    and len(hint.text) <= 2400
                )
            else:
                _require(hint.text is None)
            if hint.attempt_id is not None:
                _require(hint.attempt_id in self.by_attempt)
                _require(hint.created_at >= self.by_attempt[hint.attempt_id].created_at)
            hints[hint.id] = hint
            sequences.add(hint.sequence)
        operation_sequences: set[int] = set()
        for operation in self.operations:
            self.record("hint_operation", operation.id, operation.created_at)
            _require(
                operation.session_id == self.session.id
                and type(operation.sequence) is int
                and operation.sequence in {1, 2, 3}
            )
            _require(operation.sequence not in operation_sequences)
            operation_sequences.add(operation.sequence)
            _require(as_utc(operation.deadline_at) > as_utc(operation.created_at))
            if operation.attempt_id is not None:
                _require(operation.attempt_id in self.by_attempt)
                _require(operation.created_at >= self.by_attempt[operation.attempt_id].created_at)
            finalized_hint = hints.get(operation.id)
            _require(operation.status in {"pending", "finalized"})
            if operation.status == "pending":
                _require(operation.completed_at is None and finalized_hint is None)
            else:
                _require(finalized_hint is not None and operation.completed_at is not None)
                assert finalized_hint is not None and operation.completed_at is not None
                _require(as_utc(operation.completed_at) >= as_utc(operation.created_at))
                _require(
                    (
                        finalized_hint.session_id,
                        finalized_hint.attempt_id,
                        finalized_hint.sequence,
                        finalized_hint.idempotency_key,
                    )
                    == (
                        operation.session_id,
                        operation.attempt_id,
                        operation.sequence,
                        operation.idempotency_key,
                    )
                )
                _require(as_utc(finalized_hint.created_at) == as_utc(operation.completed_at))
            # A legacy interaction may lack a reservation, but a new reservation
            # cannot reuse a different historical interaction's sequence.
            _require(
                not any(
                    h.sequence == operation.sequence and h.id != operation.id for h in self.hints
                )
            )
        for operation in self.operations:
            self.hint_event("hint_operation", operation.id, operation.created_at, "requested")
        for hint in self.hints:
            self.hint_event("tutor_interaction", hint.id, hint.created_at, hint.status)

    def validate_run(self, run: VerificationRun) -> None:
        self.record("verification_run", run.id, run.created_at)
        _require(run.session_id == self.session.id and run.attempt_id in self.by_attempt)
        attempt = self.by_attempt[run.attempt_id]
        _require(as_utc(run.created_at) >= as_utc(attempt.created_at))
        _require(run.status in {"pending", "passed", "failed", "error"})
        raw = self.store.checks(run.id)
        checked: list[ObservedCheck] = []
        for check in raw:
            self.record("verification_check", check.id, check.created_at)
            _require(check.run_id == run.id and as_utc(check.created_at) >= as_utc(run.created_at))
            checked.append(
                ObservedCheck.model_validate(
                    {
                        "source": _ref("verification_check", check.id),
                        "code": check.code,
                        "matched": check.matched,
                        "origin": check.source,
                    }
                )
            )
        _require(len({c.code for c in raw}) == len(raw))
        if run.status == "pending":
            _require(run.completed_at is None and not raw)
            return
        _require(run.completed_at is not None)
        assert run.completed_at is not None
        _require(as_utc(run.completed_at) >= as_utc(run.created_at))
        _require(bool(raw) and all(as_utc(c.created_at) == as_utc(run.completed_at) for c in raw))
        codes = {c.code for c in raw}
        if codes == {"execution"}:
            _require(run.status == "error")
        else:
            _require(codes == _FIVE)
            self.validate_runtime(run, attempt, {c.code: c for c in raw})
        self.checks[run.id] = tuple(sorted(checked, key=lambda c: c.code))

    def validate_runtime(
        self, run: VerificationRun, attempt: Attempt, checks: dict[str, VerificationCheck]
    ) -> None:
        """Recheck the saved observation against independently stored runtime rows.

        No execution is started; no private expectations/raw response leave here.
        Infrastructure-unavailable row reads remain unavailable, never zero rows.
        """
        status = checks["http_status"].observed
        http_status = None if status in {"None", "unavailable"} else int(status)
        response = checks["api_response"].observed
        response_parseable = True
        try:
            body = json.loads(response)
        except ValueError:
            body = None  # Malformed runtime responses are real unavailable evidence.
            response_parseable = False
        supplied_id = body.get("id") if isinstance(body, dict) else None
        response_id = supplied_id if isinstance(supplied_id, str) else None
        validation = json.loads(checks["validation"].observed)
        _require(isinstance(validation, list) and all(isinstance(c, str) for c in validation))
        unavailable = checks["row_count"].observed == "unavailable"
        if self.lesson.lesson_id == TRANSFER_ID:
            tasks = self.store.tasks(run.id)
            rows = None if unavailable else tasks
            observed_task = TaskObservation(
                http_status, response, tuple(validation), rows, response_id
            )
            result = evaluate_transfer(
                attempt.field_name, self.lesson.expected_field, observed_task
            )
            response_matches = response_matches_task(observed_task)
            values_match = task_values_match(observed_task)
            validation_matches = http_status == 201 and not validation
            stored = [{"id": str(t.id), "title": t.title, "priority": t.priority} for t in tasks]
        else:
            notes = self.store.notes(run.id)
            observed = Observation(
                http_status,
                response,
                tuple(validation),
                None if unavailable else notes,
                response_id,
            )
            result = evaluate(attempt.field_name, self.lesson.expected_field, observed)
            response_matches = response_matches_fixture(observed)
            values_match = bool(
                observed.notes is not None
                and len(observed.notes) == 1
                and observed.notes[0].title == NOTE_TITLE
                and observed.notes[0].content == NOTE_CONTENT
                and str(observed.notes[0].id) == response_id
            )
            validation_matches = (
                attempt.field_name == self.lesson.expected_field
                and http_status == 201
                and not validation
            )
            stored = [{"id": str(n.id), "title": n.title, "content": n.content} for n in notes]
        _require(result.status == run.status)
        if not response_parseable and run.status == "error":
            # Observation.response_*_id is not separately persisted. A faulty
            # verifier may retain that ID while returning malformed JSON. Only
            # the recorded check retains its correlation decision. Preserve it
            # for this unavailable run, bounded by the independently read values;
            # it cannot establish a successful verification or learner grade.
            values_match = checks["stored_values"].matched
            if values_match:
                _require(not unavailable and len(stored) == 1)
                if self.lesson.lesson_id == TRANSFER_ID:
                    _require(
                        stored[0]["title"] == TASK_TITLE and stored[0]["priority"] == TASK_PRIORITY
                    )
                else:
                    _require(
                        stored[0]["title"] == NOTE_TITLE and stored[0]["content"] == NOTE_CONTENT
                    )
        matched = {
            "http_status": http_status == 201,
            "api_response": response_matches,
            "validation": validation_matches,
            "row_count": not unavailable and len(stored) == 1,
            "stored_values": values_match,
        }
        _require(all(checks[code].matched == value for code, value in matched.items()))
        if not unavailable:
            _require(int(checks["row_count"].observed) == len(stored))
            _require(json.loads(checks["stored_values"].observed) == stored)
        else:
            # A request can commit before its original independent read fails.
            # Today's readable row cannot establish what that failed read saw.
            _require(checks["stored_values"].observed == "unavailable")
        if run.status in {"passed", "failed"}:
            _require((run.status == "passed") == all(c.matched for c in checks.values()))

    def predictions_and_attempts(self) -> None:
        prediction = self.store.prediction(self.session.id)
        if prediction is not None:
            self.record("prediction", prediction.id, prediction.created_at)
            _require(prediction.session_id == self.session.id)
            _require(prediction.selected_answer in {"saved", "rejected", "server_error"})
            self.emit(
                "prediction_submitted",
                Competency.PREDICTION,
                "success"
                if prediction.selected_answer == self.lesson.prediction_answer
                else "failure",
                _ref("prediction", prediction.id),
                prediction.created_at,
            )
        for attempt in self.attempts:
            _require(prediction is not None and prediction.created_at <= attempt.created_at)
            self.emit(
                "modification_submitted",
                Competency.MODIFICATION,
                "unknown",
                _ref("attempt", attempt.id),
                attempt.created_at,
            )

    def runtime_observations(self) -> None:
        for run in self.runs:
            self.validate_run(run)
        for run in self.runs:
            if run.completed_at is None:
                continue
            outcome = {"passed": "success", "failed": "failure", "error": "unavailable"}[run.status]
            attempt = self.by_attempt[run.attempt_id]
            self.emit(
                "verification_finished",
                Competency.VERIFICATION,
                outcome,
                _ref("verification_run", run.id),
                run.completed_at,
                related=(_ref("attempt", attempt.id),),
                checks=self.checks[run.id],
                action_at=attempt.created_at,
            )
            if run.status != "passed":
                continue
            failures = [
                r
                for r in self.runs
                if r.status == "failed"
                and r.completed_at is not None
                and r.completed_at < attempt.created_at
                and self.by_attempt[r.attempt_id].number < attempt.number
                and self.by_attempt[r.attempt_id].field_name != attempt.field_name
            ]
            if failures:
                previous = max(failures, key=lambda r: (r.completed_at, str(r.id)))
                self.emit(
                    "debugging_recovery_observed",
                    Competency.DEBUGGING,
                    "success",
                    _ref("verification_run", run.id),
                    run.completed_at,
                    related=(
                        _ref("attempt", attempt.id),
                        _ref("verification_run", previous.id),
                        _ref("attempt", previous.attempt_id),
                    ),
                    checks=self.checks[run.id],
                    action_at=attempt.created_at,
                )
            # A passed runtime after abandonment is not a completed transfer.
            if self.lesson.lesson_id == TRANSFER_ID and self.session.state == "completed":
                _require(self.session.completed_at == run.completed_at)
                self.emit(
                    "transfer_completed",
                    Competency.TRANSFER,
                    "success",
                    _ref("verification_run", run.id),
                    run.completed_at,
                    related=(_ref("attempt", attempt.id),),
                    checks=self.checks[run.id],
                    action_at=attempt.created_at,
                )

    def retrieval_observations(self) -> None:
        ordinals: set[int] = set()
        for checkpoint in self.store.checkpoints(self.session.learner_id):
            if checkpoint.transfer_session_id != self.session.id:
                continue
            self.record("retrieval_checkpoint", checkpoint.id, checkpoint.created_at)
            self.validate_checkpoint(checkpoint)
            _require(checkpoint.ordinal not in ordinals)
            ordinals.add(checkpoint.ordinal)
            question = question_for(checkpoint)
            numbers: set[int] = set()
            answers = self.store.retrieval_attempts(checkpoint.id)
            correct_answers = []
            for answer in answers:
                self.record("retrieval_attempt", answer.id, answer.created_at)
                _require(
                    answer.checkpoint_id == checkpoint.id
                    and type(answer.number) is int
                    and answer.number >= 1
                )
                _require(answer.number not in numbers and answer.selection in {"a", "b", "c"})
                _require(as_utc(answer.created_at) >= as_utc(checkpoint.due_at))
                _require(
                    type(answer.correct) is bool
                    and answer.correct == (answer.selection == question.answer)
                )
                numbers.add(answer.number)
                if answer.correct:
                    correct_answers.append(answer)
                if self.visible(answer.created_at):
                    source = _ref("retrieval_attempt", answer.id)
                    # These questions disclose a result or ask for a mapping.
                    # A recorded recall answer is not a before-result prediction
                    # or proof of investigation, modification or transfer skill.
                    self.retrieval_events.append(
                        RetrievalEvidence.model_validate(
                            {
                                "id": _identity("retrieval_answered", source),
                                "schema_version": SCHEMA_VERSION,
                                "owner_learner_id": self.session.learner_id,
                                "session_id": self.session.id,
                                "lesson": self.pin,
                                "event_type": "retrieval_answered",
                                "outcome": "success" if answer.correct else "failure",
                                "occurred_at": as_utc(answer.created_at),
                                "source": source,
                                "checkpoint": _ref("retrieval_checkpoint", checkpoint.id),
                                "question": RetrievalQuestionPin.model_validate(
                                    {
                                        "question_id": question.id,
                                        "content_hash": question.content_hash,
                                    }
                                ),
                                "assistance": AssistanceContext(
                                    category="unknown", requested_before=(), delivered_before=()
                                ),
                            }
                        )
                    )
            _require(len(correct_answers) <= 1)
            _require((checkpoint.completed_at is not None) == bool(correct_answers))
            if correct_answers:
                correct = correct_answers[0]
                _require(checkpoint.completed_at == correct.created_at)
                _require(
                    all(
                        a.number <= correct.number and a.created_at <= correct.created_at
                        for a in answers
                    )
                )

    def validate_checkpoint(self, checkpoint: RetrievalCheckpoint) -> None:
        _require(self.lesson.lesson_id == TRANSFER_ID and self.session.completed_at is not None)
        _require(type(checkpoint.ordinal) is int and checkpoint.ordinal in {1, 2})
        _require(QUESTIONS[checkpoint.ordinal - 1].id == checkpoint.question_id)
        assert self.session.completed_at is not None
        _require(as_utc(checkpoint.created_at) == as_utc(self.session.completed_at))
        _require(as_utc(checkpoint.due_at) == due_at(self.session.completed_at, checkpoint.ordinal))
        question_for(checkpoint)

    def project(self) -> EngineeringEvidenceBatch:
        self.validate_attempts()
        self.validate_hints()
        self.predictions_and_attempts()
        self.runtime_observations()
        self.retrieval_observations()
        if (
            len(self.observations) + len(self.hint_events) + len(self.retrieval_events)
            > self.query.max_records
        ):
            raise LearningError(
                "evidence_limit", "The observation cohort exceeds the evidence limit."
            )
        return EngineeringEvidenceBatch(
            query=self.query,
            lesson=self.pin,
            coverage=coverage_profile(
                self.pin, frozenset(observation.competency for observation in self.observations)
            ),
            observations=tuple(sorted(self.observations, key=lambda o: (o.occurred_at, str(o.id)))),
            hint_events=tuple(sorted(self.hint_events, key=lambda h: (h.occurred_at, str(h.id)))),
            retrieval_events=tuple(
                sorted(self.retrieval_events, key=lambda r: (r.occurred_at, str(r.id)))
            ),
        )


class EngineeringEvidenceService:
    def __init__(self, repository: LearningRepository) -> None:
        self.repository = repository

    def extract(self, query: EvidenceQuery) -> EngineeringEvidenceBatch:
        """Internal caller supplies its authenticated learner ID, not a claimed owner.

        No public route or creation method exists. Each request freshly validates
        bounds; the store supplies every original source and the exact session pin.
        """
        checked = EvidenceQuery.model_validate(query.model_dump(warnings=False))
        try:
            with self.repository.read() as store:
                return _Projection(store, checked).project()
        except (ValueError, KeyError, TypeError, StopIteration, ValidationError):
            raise LearningError(
                "evidence_integrity", "The recorded evidence could not be validated."
            ) from None
