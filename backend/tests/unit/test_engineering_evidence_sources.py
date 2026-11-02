"""Corrupt detached source snapshots, never the learner database or a real runtime."""

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

import pytest
from pydantic import ValidationError

from app.domain.learning import (
    Attempt,
    LearningError,
    LearningSession,
    LessonVersion,
    Observation,
    Prediction,
    TutorInteraction,
    VerificationRun,
)
from app.domain.retrieval import QUESTIONS, RetrievalAttempt, RetrievalCheckpoint, due_at
from app.domain.transfer import (
    TASK_PRIORITY,
    TASK_TITLE,
    TRANSFER_ID,
    TaskObservation,
    TaskSnapshot,
)
from app.domain.tutoring_operations import HintOperation
from app.schemas.engineering_evidence import Competency, EvidenceQuery
from app.services.catalog import (
    LESSON_ID,
    PUBLIC_CONTENT,
    TRANSFER_CONTENT,
    lesson_hash,
    transfer_hash,
)
from app.services.engineering_evidence import EngineeringEvidenceService
from app.services.task_evidence import task_checks
from app.services.verification import VerificationService

START = datetime(2026, 10, 1, tzinfo=UTC)


def identity(name):
    return uuid5(NAMESPACE_URL, f"trace:engineering-source-test:{name}")


def at(seconds):
    return START + timedelta(seconds=seconds)


class SourceStore:
    def __init__(self):
        self.lesson = LessonVersion(
            identity("lesson"),
            LESSON_ID,
            "1.0.0",
            dict(PUBLIC_CONTENT),
            "content",
            "rejected",
            lesson_hash(PUBLIC_CONTENT, "content", "rejected"),
            START,
        )
        self.session = LearningSession(
            identity("session"),
            identity("owner"),
            self.lesson.id,
            "needs_revision",
            "session-key",
            START,
            None,
        )
        self.saved_prediction = Prediction(
            identity("prediction"), self.session.id, "rejected", "", "prediction-key", at(1)
        )
        self.saved_attempts = [
            Attempt(identity("attempt"), self.session.id, 1, "body", "", 0, "attempt-key", at(3))
        ]
        self.saved_runs = [
            VerificationRun(
                identity("run"),
                self.session.id,
                self.saved_attempts[0].id,
                "failed",
                "run-key",
                at(4),
                at(5),
                "A trusted deterministic failure.",
            )
        ]
        self.saved_checks = []
        self.saved_hints = []
        self.saved_operations = []
        self.saved_checkpoints = []
        self.saved_answers = {}
        self.saved_tasks = {}

    def owned_session(self, owner, session_id):
        return (
            self.session
            if (owner, session_id) == (self.session.learner_id, self.session.id)
            else None
        )

    def version_by_id(self, version_id):
        assert version_id == self.session.lesson_version_id
        return self.lesson

    def prediction(self, session_id):
        assert session_id == self.session.id
        return self.saved_prediction

    def attempts(self, session_id):
        assert session_id == self.session.id
        return list(self.saved_attempts)

    def runs(self, session_id):
        assert session_id == self.session.id
        return list(self.saved_runs)

    def hints(self, session_id):
        assert session_id == self.session.id
        return list(self.saved_hints)

    def hint_operations(self, session_id):
        assert session_id == self.session.id
        return list(self.saved_operations)

    def add_check(self, check):
        self.saved_checks.append(check)

    def checks(self, run_id):
        assert run_id in {run.id for run in self.saved_runs}
        return [check for check in self.saved_checks if check.run_id == run_id]

    def notes(self, run_id):
        assert run_id == identity("run")
        return ()

    def checkpoints(self, owner):
        assert owner == self.session.learner_id
        return list(self.saved_checkpoints)

    def retrieval_attempts(self, checkpoint_id):
        return list(self.saved_answers.get(checkpoint_id, []))

    def tasks(self, run_id):
        return self.saved_tasks.get(run_id, ())


class ReadOnlyRepository:
    def __init__(self, store):
        self.store, self.reads = store, 0

    @contextmanager
    def read(self):
        self.reads += 1
        yield self.store

    def write(self):
        raise AssertionError("Engineering evidence must never open a write transaction")


@pytest.fixture
def source(monkeypatch):
    store = SourceStore()
    serial = iter(range(10))
    monkeypatch.setattr(
        "app.services.verification.uuid4", lambda: identity(f"check-{next(serial)}")
    )
    # Reuse the actual trusted check builder, rather than a second test interpretation.
    VerificationService._checks(
        store,
        identity("run"),
        "body",
        "content",
        Observation(
            422,
            '{"detail":"receiving schema rejected the payload"}',
            ("missing:content", "extra_forbidden:body"),
            (),
            None,
        ),
        at(5),
    )
    return store


def query(**changes):
    return EvidenceQuery.model_validate(
        {
            "owner_learner_id": identity("owner"),
            "session_id": identity("session"),
            "start_at": START,
            "end_at": at(100),
            "as_of": at(100),
            "max_records": 100,
            **changes,
        }
    )


def extract(store, request=None):
    return EngineeringEvidenceService(ReadOnlyRepository(store)).extract(request or query())


def coverage(batch, competency):
    return next(item for item in batch.coverage if item.competency == competency)


def reject(store):
    with pytest.raises(LearningError) as caught:
        extract(store)
    assert caught.value.code == "evidence_integrity"


def add_help(store, status="delivered"):
    operation = HintOperation(
        identity("hint"),
        store.session.id,
        None,
        1,
        "hint-key",
        at(2),
        at(32),
        "pending" if status == "pending" else "finalized",
        None if status == "pending" else at(2.5),
    )
    store.saved_operations = [operation]
    if status != "pending":
        store.saved_hints = [
            TutorInteraction(
                operation.id,
                operation.session_id,
                None,
                1,
                "Follow the request data." if status == "delivered" else None,
                status,
                operation.idempotency_key,
                operation.completed_at,
            )
        ]


def test_trusted_source_projection_is_readonly_repeatable_and_omits_private_data(source):
    repository = ReadOnlyRepository(source)
    service = EngineeringEvidenceService(repository)
    first = service.extract(query())
    assert service.extract(query()) == first and repository.reads == 2
    assert [record.event_type for record in first.observations] == [
        "prediction_submitted",
        "modification_submitted",
        "verification_finished",
    ]
    assert [record.outcome for record in first.observations] == ["success", "unknown", "failure"]
    assert len(first.observations[-1].checks) == 5
    assert "receiving schema rejected" not in first.model_dump_json()
    assert source.saved_attempts[0].field_name == "body"
    assert first.lesson.version_id == source.lesson.id
    assert first.lesson.content_hash == source.lesson.content_hash
    assert first.retrieval_events == ()


def test_notes_coverage_reports_source_limits_separately_from_observed_actions(source):
    result = extract(source)
    assert tuple(item.competency for item in result.coverage) == tuple(Competency)
    assert {item.competency for item in result.coverage if item.observed_in_window} == {
        Competency.PREDICTION,
        Competency.MODIFICATION,
        Competency.VERIFICATION,
    }
    assert coverage(result, "prediction").availability == "direct"
    assert coverage(result, "prediction").limitations == ("selected_outcome_only",)
    assert coverage(result, "investigation").availability == "unavailable"
    assert coverage(result, "investigation").limitations == ("investigation_not_recorded",)
    assert coverage(result, "modification").availability == "partial"
    assert coverage(result, "modification").limitations == (
        "finite_mapping_only",
        "code_patch_not_recorded",
        "runtime_outcome_separate",
    )
    assert coverage(result, "debugging").availability == "partial"
    assert coverage(result, "debugging").limitations == (
        "recovery_chronology_only",
        "diagnosis_not_recorded",
    )
    assert coverage(result, "verification").availability == "direct"
    assert coverage(result, "verification").limitations == ()
    assert coverage(result, "transfer").availability == "unavailable"
    assert coverage(result, "transfer").limitations == ("outgoing_transfer_not_recorded",)


def test_empty_source_cohort_retains_pin_and_coverage_without_manufacturing_events(source):
    source.saved_prediction = None
    source.saved_attempts = []
    source.saved_runs = []
    source.saved_checks = []
    source.session = replace(source.session, state="awaiting_prediction")
    result = extract(source, query(max_records=1))
    assert result.lesson.version_id == source.session.lesson_version_id
    assert result.lesson.lesson_id == LESSON_ID
    assert result.lesson.content_hash == source.lesson.content_hash
    assert result.observations == result.hint_events == result.retrieval_events == ()
    assert len(result.coverage) == 6
    assert all(not item.observed_in_window for item in result.coverage)
    assert coverage(result, "prediction").availability == "direct"
    assert coverage(result, "investigation").availability == "unavailable"


def test_hint_only_window_does_not_turn_help_events_into_competency_observations(source):
    add_help(source)
    result = extract(source, query(start_at=at(2), end_at=at(3), as_of=at(3)))
    assert [item.outcome for item in result.hint_events] == ["requested", "delivered"]
    assert result.observations == result.retrieval_events == ()
    assert all(not item.observed_in_window for item in result.coverage)


def test_window_without_actions_reports_absence_not_a_false_ability_score(source):
    result = extract(source, query(end_at=at(0.5), as_of=at(0.5), max_records=1))
    assert result.observations == result.hint_events == result.retrieval_events == ()
    assert result.lesson.content_hash == source.lesson.content_hash
    assert all(not item.observed_in_window for item in result.coverage)
    assert len(result.coverage) == 6


@pytest.mark.parametrize("status", ["pending", "error", "delivered"])
def test_exact_request_and_actual_delivery_are_independent_source_facts(source, status):
    add_help(source, status)
    result = extract(source)
    modification = next(
        record for record in result.observations if record.event_type == "modification_submitted"
    )
    assert len(modification.assistance.requested_before) == 1
    assert bool(modification.assistance.delivered_before) == (status == "delivered")
    assert modification.assistance.category == (
        "tutor_assisted" if status == "delivered" else "unknown"
    )
    assert [record.outcome for record in result.hint_events] == (
        ["requested"] if status == "pending" else ["requested", status]
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "session",
        "attempt",
        "sequence",
        "key",
        "completion_time",
        "missing_result",
        "pending_result",
        "pending_completion",
        "deadline",
        "unknown_status",
        "duplicate",
        "result_session",
        "result_status",
        "result_text",
        "result_type",
        "result_duplicate",
        "unmatched_sequence",
        "request_before_context",
        "result_before_context",
    ],
)
def test_hint_join_corruption_and_invalid_lifecycle_fail_closed(source, mutation):
    add_help(source)
    op, hint = source.saved_operations[0], source.saved_hints[0]
    if mutation == "session":
        source.saved_operations = [replace(op, session_id=identity("foreign-session"))]
    elif mutation == "attempt":
        source.saved_operations = [replace(op, attempt_id=identity("missing-attempt"))]
    elif mutation == "sequence":
        source.saved_operations = [replace(op, sequence=2)]
    elif mutation == "key":
        source.saved_operations = [replace(op, idempotency_key="another-key")]
    elif mutation == "completion_time":
        source.saved_operations = [replace(op, completed_at=at(2.6))]
    elif mutation == "missing_result":
        source.saved_hints = []
    elif mutation == "pending_result":
        source.saved_operations = [replace(op, status="pending", completed_at=None)]
    elif mutation == "pending_completion":
        source.saved_operations = [replace(op, status="pending")]
    elif mutation == "deadline":
        source.saved_operations = [replace(op, deadline_at=op.created_at)]
    elif mutation == "unknown_status":
        source.saved_operations = [replace(op, status="delivered")]
    elif mutation == "duplicate":
        source.saved_operations = [op, op]
    elif mutation == "result_session":
        source.saved_hints = [replace(hint, session_id=identity("foreign-session"))]
    elif mutation == "result_status":
        source.saved_hints = [replace(hint, status="pending")]
    elif mutation == "result_text":
        source.saved_hints = [replace(hint, text=None)]
    elif mutation == "result_type":
        source.saved_hints = [replace(hint, interaction_type="explanation")]
    elif mutation == "result_duplicate":
        source.saved_hints = [hint, hint]
    elif mutation == "unmatched_sequence":
        source.saved_hints = [replace(hint, id=identity("another-hint"))]
    elif mutation == "request_before_context":
        source.saved_operations = [replace(op, attempt_id=source.saved_attempts[0].id)]
    else:
        source.saved_hints = [replace(hint, attempt_id=source.saved_attempts[0].id)]
    reject(source)


@pytest.mark.parametrize(
    "changes",
    [
        {"max_records": 0},
        {"max_records": True},
        {"max_records": 10001},
        {"start_at": at(100)},
        {"end_at": START},
        {"as_of": at(99)},
        {"start_at": START.replace(tzinfo=None)},
        {"max_records": "100"},
    ],
)
def test_forged_query_construct_is_freshly_validated_before_repository_read(source, changes):
    forged = EvidenceQuery.model_construct(**{**query().model_dump(), **changes})
    repository = ReadOnlyRepository(source)
    with pytest.raises(ValidationError):
        EngineeringEvidenceService(repository).extract(forged)
    assert repository.reads == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"version": "1.1.0"},
        {"version": "v1"},
        {"id": identity("another-version")},
        {"content_hash": "a" * 64},
        {"expected_field": "body"},
        {"prediction_answer": "saved"},
        {"lesson_id": "not-an-approved-lesson"},
        {"public_content": {**PUBLIC_CONTENT, "scenario": "Changed without versioning"}},
    ],
)
def test_exact_legacy_pin_is_verified_against_actual_catalog(source, changes):
    source.lesson = replace(source.lesson, **changes)
    reject(source)


@pytest.mark.parametrize(
    "mutation",
    [
        "negative_number",
        "duplicate_number",
        "wrong_mapping",
        "invalid_help_count",
        "boolean_help_count",
        "missing_prediction",
        "prediction_after_attempt",
        "prediction_choice",
    ],
)
def test_attempt_and_original_prediction_source_invariants(source, mutation):
    attempt = source.saved_attempts[0]
    if mutation == "negative_number":
        source.saved_attempts = [replace(attempt, number=0)]
    elif mutation == "duplicate_number":
        source.saved_attempts.append(replace(attempt, id=identity("attempt-2")))
    elif mutation == "wrong_mapping":
        source.saved_attempts = [replace(attempt, field_name="nested")]
    elif mutation == "invalid_help_count":
        source.saved_attempts = [replace(attempt, hints_before=4)]
    elif mutation == "boolean_help_count":
        source.saved_attempts = [replace(attempt, hints_before=True)]
    elif mutation == "missing_prediction":
        source.saved_prediction = None
    elif mutation == "prediction_after_attempt":
        source.saved_prediction = replace(source.saved_prediction, created_at=at(4))
    else:
        source.saved_prediction = replace(source.saved_prediction, selected_answer="invented")
    reject(source)


@pytest.mark.parametrize(
    "mutation",
    [
        "pending_completion",
        "pending_checks",
        "finished_no_completion",
        "finished_before_start",
        "unknown_status",
        "run_before_attempt",
        "check_before_run",
        "check_after_completion",
        "check_before_completion",
        "wrong_run_id",
        "wrong_origin",
        "missing_category",
        "invalid_category",
        "duplicate_category",
        "boolean_match_coercion",
    ],
)
def test_run_and_check_source_integrity(source, mutation):
    run, check = source.saved_runs[0], source.saved_checks[0]
    if mutation == "pending_completion":
        source.saved_runs = [replace(run, status="pending")]
    elif mutation == "pending_checks":
        source.saved_runs = [replace(run, status="pending", completed_at=None)]
    elif mutation == "finished_no_completion":
        source.saved_runs = [replace(run, completed_at=None)]
    elif mutation == "finished_before_start":
        source.saved_runs = [replace(run, completed_at=at(3.5))]
    elif mutation == "unknown_status":
        source.saved_runs = [replace(run, status="completed")]
    elif mutation == "run_before_attempt":
        source.saved_runs = [replace(run, created_at=at(2))]
    elif mutation == "check_before_run":
        source.saved_checks[0] = replace(check, created_at=at(3))
    elif mutation == "check_after_completion":
        source.saved_checks[0] = replace(check, created_at=at(6))
    elif mutation == "check_before_completion":
        source.saved_checks[0] = replace(check, created_at=at(4.5))
    elif mutation == "wrong_run_id":
        source.saved_checks[0] = replace(check, run_id=identity("foreign-run"))
    elif mutation == "wrong_origin":
        source.saved_checks[0] = replace(check, source="fresh_database_read")
    elif mutation == "missing_category":
        source.saved_checks.pop()
    elif mutation == "invalid_category":
        source.saved_checks[0] = replace(check, code="client_claim")
    elif mutation == "duplicate_category":
        source.saved_checks.append(replace(check, id=identity("extra-check")))
    else:
        source.saved_checks[0] = replace(check, matched=0)
    reject(source)


@pytest.mark.parametrize(
    "code", ["http_status", "api_response", "validation", "row_count", "stored_values"]
)
def test_individual_match_flags_are_recomputed_from_saved_runtime_and_readback(source, code):
    index = next(i for i, item in enumerate(source.saved_checks) if item.code == code)
    original = source.saved_checks[index]
    source.saved_checks[index] = replace(original, matched=not original.matched)
    reject(source)


@pytest.mark.parametrize(
    "code,observed",
    [
        ("http_status", "not-a-number"),
        ("validation", "{}"),
        ("validation", "[1]"),
        ("row_count", "2"),
        ("stored_values", "{}"),
        ("stored_values", "[{}]"),
    ],
)
def test_corrupt_runtime_source_payloads_cannot_become_trusted_checks(source, code, observed):
    index = next(i for i, item in enumerate(source.saved_checks) if item.code == code)
    source.saved_checks[index] = replace(source.saved_checks[index], observed=observed)
    reject(source)


@pytest.mark.parametrize(
    "source_kind", ["session", "prediction", "attempt", "run", "check", "hint", "operation"]
)
def test_naive_source_times_fail_closed_instead_of_using_machine_timezone(source, source_kind):
    add_help(source)
    if source_kind == "session":
        source.session = replace(source.session, created_at=START.replace(tzinfo=None))
    elif source_kind == "prediction":
        source.saved_prediction = replace(
            source.saved_prediction, created_at=at(1).replace(tzinfo=None)
        )
    else:
        field = {
            "attempt": "saved_attempts",
            "run": "saved_runs",
            "check": "saved_checks",
            "hint": "saved_hints",
            "operation": "saved_operations",
        }[source_kind]
        row = getattr(source, field)[0]
        getattr(source, field)[0] = replace(row, created_at=row.created_at.replace(tzinfo=None))
    reject(source)


def test_pending_runtime_has_no_fabricated_result(source):
    source.saved_runs = [replace(source.saved_runs[0], status="pending", completed_at=None)]
    source.saved_checks = []
    result = extract(source)
    assert not any(item.event_type == "verification_finished" for item in result.observations)


def test_request_snapshot_is_stable_after_future_finalization_and_retry(source):
    add_help(source, "pending")
    before_completion = query(end_at=at(2.25), as_of=at(2.25))
    original = extract(source, before_completion)
    add_help(source, "delivered")
    assert extract(source, before_completion) == original
    assert [item.outcome for item in original.hint_events] == ["requested"]
    final = extract(source)
    assert extract(source) == final
    assert [item.outcome for item in final.hint_events] == ["requested", "delivered"]


def test_late_delivery_preserves_original_attempt_assistance_snapshot(source):
    add_help(source, "pending")
    original = extract(source)
    op = source.saved_operations[0]
    source.saved_operations = [replace(op, status="finalized", completed_at=at(6))]
    source.saved_hints = [
        TutorInteraction(
            op.id, op.session_id, None, 1, "Late guidance.", "delivered", op.idempotency_key, at(6)
        )
    ]
    later = extract(source)
    assert later.observations == original.observations
    assert len(later.hint_events) == len(original.hint_events) + 1


@pytest.fixture
def tasks_source(source, monkeypatch):
    source.lesson = replace(
        source.lesson,
        lesson_id=TRANSFER_ID,
        public_content=dict(TRANSFER_CONTENT),
        expected_field="nested",
        content_hash=transfer_hash(TRANSFER_CONTENT),
    )
    source.saved_attempts[0] = replace(source.saved_attempts[0], field_name="flat")
    corrected = replace(
        source.saved_attempts[0],
        id=identity("nested-attempt"),
        number=2,
        field_name="nested",
        idempotency_key="nested-key",
        created_at=at(6),
    )
    passed = VerificationRun(
        identity("passed-run"),
        source.session.id,
        corrected.id,
        "passed",
        "passed-key",
        at(7),
        at(8),
        "Real trusted task check shape.",
    )
    source.saved_attempts.append(corrected)
    source.saved_runs.append(passed)
    row = TaskSnapshot(identity("task-row"), TASK_TITLE, TASK_PRIORITY)
    source.saved_tasks[passed.id] = (row,)
    source.saved_checks = []
    serial = iter(range(10))
    monkeypatch.setattr(
        "app.services.task_evidence.uuid4", lambda: identity(f"task-check-{next(serial)}")
    )
    task_checks(
        source,
        identity("run"),
        TaskObservation(
            422,
            '{"detail":"nested schema rejected flat priority"}',
            ("missing:metadata", "extra_forbidden:priority"),
            (),
            None,
        ),
        at(5),
    )
    task_checks(
        source,
        passed.id,
        TaskObservation(
            201,
            '{"id":"'
            + str(row.id)
            + '","title":"'
            + TASK_TITLE
            + '","metadata":{"priority":"'
            + TASK_PRIORITY
            + '"}}',
            (),
            (row,),
            str(row.id),
        ),
        at(8),
    )
    source.session = replace(source.session, state="completed", completed_at=at(8))
    question = QUESTIONS[0]
    checkpoint = RetrievalCheckpoint(
        identity("checkpoint"),
        source.session.id,
        1,
        question.id,
        question.content_hash,
        due_at(at(8), 1),
        at(8),
        due_at(at(8), 1) + timedelta(seconds=2),
    )
    source.saved_checkpoints = [checkpoint]
    source.saved_answers[checkpoint.id] = [
        RetrievalAttempt(
            identity("wrong-answer"),
            checkpoint.id,
            1,
            "a",
            "",
            False,
            "Deterministic answer mismatch.",
            "wrong-answer-key",
            checkpoint.due_at + timedelta(seconds=1),
        ),
        RetrievalAttempt(
            identity("correct-answer"),
            checkpoint.id,
            2,
            question.answer,
            "",
            True,
            "Deterministic answer match.",
            "correct-answer-key",
            checkpoint.completed_at,
        ),
    ]
    return source


def test_out_of_order_immutable_sources_have_identical_projection(source):
    source.saved_attempts.append(
        replace(
            source.saved_attempts[0],
            id=identity("attempt-2"),
            number=2,
            created_at=at(6),
            idempotency_key="attempt-2-key",
        )
    )
    original = extract(source)
    source.saved_attempts.reverse()
    source.saved_checks.reverse()
    assert extract(source) == original


def test_explicit_result_cap_rejects_whole_cohort_without_silent_truncation(source):
    with pytest.raises(LearningError) as caught:
        extract(source, query(max_records=2))
    assert caught.value.code == "evidence_limit"
    assert len(extract(source, query(max_records=3)).observations) == 3


def test_hard_source_cap_applies_even_to_records_outside_selected_event_window(source):
    sample = source.saved_attempts[0]
    source.saved_attempts = [
        replace(
            sample, id=identity(f"bounded-attempt-{i}"), number=i + 1, idempotency_key=f"key-{i}"
        )
        for i in range(10001)
    ]
    with pytest.raises(LearningError) as caught:
        extract(source, query(start_at=at(50)))
    assert caught.value.code == "evidence_limit"


@pytest.mark.parametrize("number", [True, False, 1.0, "1"])
def test_attempt_number_requires_an_actual_positive_integer(source, number):
    source.saved_attempts[0] = replace(source.saved_attempts[0], number=number)
    reject(source)


@pytest.mark.parametrize("kind", ["operation", "interaction"])
@pytest.mark.parametrize("sequence", [True, False, 1.0, "1"])
def test_hint_sequence_requires_an_actual_integer(source, kind, sequence):
    add_help(source)
    target = source.saved_operations if kind == "operation" else source.saved_hints
    target[0] = replace(target[0], sequence=sequence)
    reject(source)


@pytest.mark.parametrize("text", ["", "   ", "\n\t", "a" * 2401, 1, ["guidance"]])
def test_delivered_guidance_requires_valid_nonblank_bounded_text(source, text):
    add_help(source)
    source.saved_hints[0] = replace(source.saved_hints[0], text=text)
    reject(source)


@pytest.mark.parametrize("text", ["", "  ", "Hidden partial response"])
def test_error_guidance_does_not_retain_partial_text(source, text):
    add_help(source, "error")
    source.saved_hints[0] = replace(source.saved_hints[0], text=text)
    reject(source)


def test_tasks_sources_preserve_real_check_builder_and_pinned_retrieval_facts(tasks_source):
    end = START + timedelta(days=8)
    result = extract(tasks_source, query(end_at=end, as_of=end))
    runtime = [
        record for record in result.observations if record.event_type == "verification_finished"
    ]
    assert [record.outcome for record in runtime] == ["failure", "success"]
    assert all(len(record.checks) == 5 for record in runtime)
    assert any(record.event_type == "debugging_recovery_observed" for record in result.observations)
    assert any(record.event_type == "transfer_completed" for record in result.observations)
    answers = result.retrieval_events
    assert [record.outcome for record in answers] == ["failure", "success"]
    assert all(record.question.content_hash == QUESTIONS[0].content_hash for record in answers)
    assert all(record.assistance.category == "unknown" for record in answers)
    assert all(
        record.checkpoint.record_id == tasks_source.saved_checkpoints[0].id for record in answers
    )
    assert not any(record.event_type == "retrieval_answered" for record in result.observations)
    assert all(not hasattr(record, "competency") for record in answers)
    assert coverage(result, "transfer").availability == "partial"
    assert coverage(result, "transfer").observed_in_window is True
    assert coverage(result, "transfer").limitations == ("exact_notes_parent_not_pinned",)


def test_retrieval_only_window_preserves_recall_facts_without_claiming_prediction(tasks_source):
    checkpoint = tasks_source.saved_checkpoints[0]
    end = checkpoint.due_at + timedelta(seconds=3)
    result = extract(tasks_source, query(start_at=checkpoint.due_at, end_at=end, as_of=end))
    assert [item.outcome for item in result.retrieval_events] == ["failure", "success"]
    assert result.observations == result.hint_events == ()
    assert all(not item.observed_in_window for item in result.coverage)
    assert coverage(result, "transfer").availability == "partial"
    assert result.lesson.lesson_id == TRANSFER_ID
    assert all(item.lesson == result.lesson for item in result.retrieval_events)
    assert extract(tasks_source, query(start_at=checkpoint.due_at, end_at=end, as_of=end)) == result


@pytest.mark.parametrize(
    "mutation",
    [
        "boolean_ordinal",
        "float_ordinal",
        "invalid_ordinal",
        "duplicate_ordinal",
        "question_id",
        "question_digest",
        "created_time",
        "due_time",
        "missing_completion",
        "unearned_completion",
        "wrong_completion_time",
        "multiple_correct",
        "answer_after_correct",
        "later_number_earlier_time",
        "earlier_number_later_time",
        "answer_checkpoint",
        "answer_boolean_number",
        "answer_float_number",
        "answer_zero_number",
        "answer_duplicate_number",
        "answer_duplicate_identity",
        "answer_selection",
        "answer_correct_type",
        "answer_false_result",
        "answer_before_due",
        "answer_naive_timestamp",
    ],
)
def test_retrieval_source_lifecycle_and_exact_pins_fail_closed(tasks_source, mutation):
    store = tasks_source
    checkpoint = store.saved_checkpoints[0]
    answers = store.saved_answers[checkpoint.id]
    wrong, correct = answers
    if mutation == "boolean_ordinal":
        store.saved_checkpoints[0] = replace(checkpoint, ordinal=True)
    elif mutation == "float_ordinal":
        store.saved_checkpoints[0] = replace(checkpoint, ordinal=1.0)
    elif mutation == "invalid_ordinal":
        store.saved_checkpoints[0] = replace(checkpoint, ordinal=3)
    elif mutation == "duplicate_ordinal":
        store.saved_checkpoints.append(replace(checkpoint, id=identity("duplicate-checkpoint")))
    elif mutation == "question_id":
        store.saved_checkpoints[0] = replace(checkpoint, question_id=QUESTIONS[1].id)
    elif mutation == "question_digest":
        store.saved_checkpoints[0] = replace(checkpoint, question_hash="a" * 64)
    elif mutation == "created_time":
        store.saved_checkpoints[0] = replace(checkpoint, created_at=at(9))
    elif mutation == "due_time":
        store.saved_checkpoints[0] = replace(
            checkpoint, due_at=checkpoint.due_at + timedelta(days=2)
        )
    elif mutation == "missing_completion":
        store.saved_checkpoints[0] = replace(checkpoint, completed_at=None)
    elif mutation == "unearned_completion":
        store.saved_answers[checkpoint.id] = [wrong]
    elif mutation == "wrong_completion_time":
        store.saved_checkpoints[0] = replace(
            checkpoint, completed_at=correct.created_at + timedelta(seconds=1)
        )
    elif mutation == "multiple_correct":
        answers.append(
            replace(
                correct, id=identity("second-correct"), number=3, idempotency_key="second-correct"
            )
        )
    elif mutation == "answer_after_correct":
        answers.append(
            replace(
                wrong,
                id=identity("after-correct"),
                number=3,
                created_at=correct.created_at + timedelta(seconds=1),
            )
        )
    elif mutation == "later_number_earlier_time":
        answers[0] = replace(wrong, number=3)
    elif mutation == "earlier_number_later_time":
        answers[0] = replace(wrong, created_at=correct.created_at + timedelta(seconds=1))
    elif mutation == "answer_checkpoint":
        answers[0] = replace(wrong, checkpoint_id=identity("foreign-checkpoint"))
    elif mutation == "answer_boolean_number":
        answers[0] = replace(wrong, number=True)
    elif mutation == "answer_float_number":
        answers[0] = replace(wrong, number=1.0)
    elif mutation == "answer_zero_number":
        answers[0] = replace(wrong, number=0)
    elif mutation == "answer_duplicate_number":
        answers[0] = replace(wrong, number=correct.number)
    elif mutation == "answer_duplicate_identity":
        answers[0] = replace(wrong, id=correct.id)
    elif mutation == "answer_selection":
        answers[0] = replace(wrong, selection="saved")
    elif mutation == "answer_correct_type":
        answers[0] = replace(wrong, correct=0)
    elif mutation == "answer_false_result":
        answers[0] = replace(wrong, correct=True)
    elif mutation == "answer_before_due":
        answers[0] = replace(wrong, created_at=checkpoint.due_at - timedelta(seconds=1))
    else:
        answers[0] = replace(wrong, created_at=wrong.created_at.replace(tzinfo=None))
    end = START + timedelta(days=8)
    with pytest.raises(LearningError) as caught:
        extract(store, query(end_at=end, as_of=end))
    assert caught.value.code == "evidence_integrity"


def test_retrieval_answer_order_does_not_change_immutable_projection(tasks_source):
    end = START + timedelta(days=8)
    request = query(end_at=end, as_of=end)
    original = extract(tasks_source, request)
    checkpoint = tasks_source.saved_checkpoints[0]
    tasks_source.saved_answers[checkpoint.id].reverse()
    tasks_source.saved_checks.reverse()
    tasks_source.saved_runs.reverse()
    tasks_source.saved_attempts.reverse()
    assert extract(tasks_source, request) == original
