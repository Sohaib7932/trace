"""Engineering observations come from owned, pinned, immutable learner records."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError

from app.ai.providers.fake import FakeTutorProvider
from app.api.dependencies import get_notes_verifier
from app.db import models as m
from app.db.learning import SqlLearningRepository
from app.domain.learning import LearningError, TutorInteraction
from app.schemas.engineering_evidence import Competency, EvidenceQuery
from app.services.catalog import seed_transfer_lesson
from app.services.engineering_evidence import EngineeringEvidenceService
from app.services.learning import LearningService
from app.verification.asgi_notes import AsgiNotesVerifier
from tests.integration.test_learning import attempt, post, predict, start, verify
from tests.integration.test_transfer_retrieval import journey, mapping, start_transfer
from tests.integration.test_tutor_transactions import BlockingTutor

CHECK_CODES = {"http_status", "api_response", "validation", "row_count", "stored_values"}


class EvidenceClock:
    def __init__(self):
        self.now = datetime.now(UTC) + timedelta(seconds=1)

    def __call__(self):
        return self.now

    def advance(self, seconds=1):
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def evidence_clock(learning_app):
    clock = EvidenceClock()
    learning_app.state.clock = clock
    return clock


def evidence_query(learner, session, at, **changes):
    return EvidenceQuery(
        **{
            "owner_learner_id": UUID(learner.get("/api/v1/learners/me").json()["learner_id"]),
            "session_id": UUID(str(session)),
            "start_at": datetime(2000, 1, 1, tzinfo=UTC),
            "end_at": at + timedelta(seconds=1),
            "as_of": at + timedelta(seconds=1),
            "max_records": 1000,
            **changes,
        }
    )


def extraction(learner, database, session, clock, **changes):
    query = evidence_query(learner, session, clock(), **changes)
    return EngineeringEvidenceService(SqlLearningRepository(database)).extract(query)


def find(batch, event_type):
    return [item for item in batch.observations if item.event_type == event_type]


def coverage(batch, competency):
    return next(item for item in batch.coverage if item.competency == competency)


def notes_failure(learner, clock):
    session = start(learner)
    clock.advance()
    assert predict(learner, session).status_code == 201
    clock.advance()
    wrong = attempt(learner, session)
    clock.advance()
    failed = verify(learner, session, wrong["id"]).json()
    assert failed["status"] == "failed"
    return session, wrong, failed


def test_notes_actual_failure_repair_and_readonly_provenance(learner, database, evidence_clock):
    session, wrong, failed = notes_failure(learner, evidence_clock)
    earlier = extraction(learner, database, session, evidence_clock)
    submitted = find(earlier, "modification_submitted")[0]
    assert submitted.source.record_id == UUID(wrong["id"])
    assert submitted.outcome == "unknown" and submitted.assistance.category == "unknown"
    evidence_clock.advance()
    corrected = attempt(learner, session, "content")
    evidence_clock.advance()
    passed = verify(learner, session, corrected["id"]).json()
    assert passed["status"] == "passed"
    writes = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(database.engine, "before_cursor_execute", capture)
    try:
        batch = extraction(learner, database, session, evidence_clock)
        assert extraction(learner, database, session, evidence_clock) == batch
    finally:
        event.remove(database.engine, "before_cursor_execute", capture)
    assert writes == []
    assert {item.competency for item in batch.observations} == {
        "prediction",
        "modification",
        "verification",
        "debugging",
    }
    assert find(batch, "prediction_submitted")[0].outcome == "success"
    runs = find(batch, "verification_finished")
    assert [item.outcome for item in runs] == ["failure", "success"]
    assert [item.source.record_id for item in runs] == [UUID(failed["id"]), UUID(passed["id"])]
    for item in runs:
        assert {check.code for check in item.checks} == CHECK_CODES
        assert {check.origin for check in item.checks} == {"asgi_http", "fresh_database_read"}
        assert all(check.source.kind == "verification_check" for check in item.checks)
    recovery = find(batch, "debugging_recovery_observed")
    assert len(recovery) == 1 and recovery[0].basis == "indirect"
    assert UUID(failed["id"]) in {ref.record_id for ref in recovery[0].related_sources}
    assert find(batch, "transfer_completed") == []
    assert next(item for item in batch.observations if item.id == submitted.id) == submitted
    assert all(item.lesson.version == "1.0.0" for item in batch.observations)
    assert batch.lesson == batch.observations[0].lesson
    assert coverage(batch, "investigation").availability == "unavailable"
    assert coverage(batch, "investigation").observed_in_window is False
    assert coverage(batch, "transfer").availability == "unavailable"
    assert coverage(batch, "transfer").observed_in_window is False
    serialized = batch.model_dump_json()
    assert "prediction_answer" not in serialized and "expected_field" not in serialized
    assert "The field names differ" not in serialized and "note.content" not in serialized


def complete_tasks(learner, database, clock):
    original = start(learner)
    clock.advance()
    assert predict(learner, original).status_code == 201
    clock.advance()
    correct = attempt(learner, original, "content")
    clock.advance()
    assert verify(learner, original, correct["id"]).json()["status"] == "passed"
    seed_transfer_lesson(SqlLearningRepository(database))
    clock.advance()
    session = start_transfer(learner)
    clock.advance()
    assert predict(learner, session).status_code == 201
    clock.advance()
    flat = mapping(learner, session, "flat").json()
    clock.advance()
    assert verify(learner, session, flat["id"]).json()["status"] == "failed"
    clock.advance()
    nested = mapping(learner, session, "nested").json()
    clock.advance()
    passed = verify(learner, session, nested["id"]).json()
    assert passed["status"] == "passed"
    return original, session, passed


def test_tasks_actual_runtime_transfer_and_unchanged_retrieval_schedule(
    learner, database, evidence_clock
):
    original, session, passed = complete_tasks(learner, database, evidence_clock)
    batch = extraction(learner, database, session, evidence_clock)
    assert all(
        item.lesson.lesson_id == "fastapi-nested-payload-transfer" for item in batch.observations
    )
    transfer = find(batch, "transfer_completed")
    assert len(transfer) == 1 and transfer[0].outcome == "success"
    assert transfer[0].source.record_id == UUID(passed["id"])
    assert UUID(original) not in {ref.record_id for ref in transfer[0].related_sources}
    assert len(find(batch, "debugging_recovery_observed")) == 1
    runs = find(batch, "verification_finished")
    assert [item.outcome for item in runs] == ["failure", "success"]
    assert all({check.code for check in item.checks} == CHECK_CODES for item in runs)
    with database.session() as fresh:
        tasks = fresh.scalars(
            select(m.RuntimeTask).where(m.RuntimeTask.run_id == UUID(passed["id"]))
        ).all()
        assert [(row.title, row.priority) for row in tasks] == [
            ("Prepare the product demo", "high")
        ]
    checkpoints = journey(learner)["checkpoints"]
    assert [datetime.fromisoformat(item["due_at"]) for item in checkpoints] == [
        evidence_clock() + timedelta(days=days) for days in (1, 7)
    ]
    assert all(item.competency != "investigation" for item in batch.observations)
    assert coverage(batch, "transfer").availability == "partial"
    assert coverage(batch, "transfer").limitations == ("exact_notes_parent_not_pinned",)
    assert coverage(batch, "transfer").observed_in_window is True


def test_retrieval_answers_keep_actual_question_pins_and_deterministic_outcomes(
    learner, database, evidence_clock
):
    _, session, _ = complete_tasks(learner, database, evidence_clock)
    checkpoint = journey(learner)["checkpoints"][0]
    evidence_clock.now = datetime.fromisoformat(checkpoint["due_at"])
    path = f"/retrievals/{checkpoint['id']}/attempts"
    wrong = post(learner, path, {"selection": "a"}).json()
    evidence_clock.advance()
    key = str(uuid4())
    correct = post(learner, path, {"selection": "b"}, key).json()
    assert post(learner, path, {"selection": "b"}, key).json() == correct
    batch = extraction(learner, database, session, evidence_clock)
    answers = batch.retrieval_events
    assert [item.outcome for item in answers] == ["failure", "success"]
    assert [item.source.record_id for item in answers] == [UUID(wrong["id"]), UUID(correct["id"])]
    assert all(not hasattr(item, "competency") for item in answers)
    assert all(item.question.question_id == "shipping-contract-v1" for item in answers)
    assert all(item.checkpoint.record_id == UUID(checkpoint["id"]) for item in answers)
    assert all(item.assistance.category == "unknown" for item in answers)
    assert len({item.id for item in answers}) == 2
    assert find(batch, "retrieval_answered") == []
    assert len(find(batch, "prediction_submitted")) == 1
    assert all(item.lesson == batch.lesson for item in answers)
    only_retrieval = extraction(
        learner,
        database,
        session,
        evidence_clock,
        start_at=datetime.fromisoformat(checkpoint["due_at"]),
    )
    assert only_retrieval.retrieval_events == answers
    assert only_retrieval.observations == only_retrieval.hint_events == ()
    assert all(not item.observed_in_window for item in only_retrieval.coverage)


def test_absent_actions_remain_absent_and_unknown_not_independent(
    learner, database, evidence_clock
):
    session = start(learner)
    batch = extraction(learner, database, session, evidence_clock, max_records=1)
    assert batch.observations == batch.hint_events == batch.retrieval_events == ()
    assert batch.lesson.lesson_id == "fastapi-payload-mismatch"
    assert batch.lesson.version == "1.0.0"
    assert tuple(item.competency for item in batch.coverage) == tuple(Competency)
    assert all(not item.observed_in_window for item in batch.coverage)
    assert coverage(batch, "investigation").availability == "unavailable"
    assert coverage(batch, "investigation").limitations == ("investigation_not_recorded",)
    evidence_clock.advance()
    assert predict(learner, session).status_code == 201
    batch = extraction(learner, database, session, evidence_clock)
    assert len(batch.observations) == 1
    assert batch.observations[0].assistance.category == "unknown"
    assert coverage(batch, "prediction").observed_in_window is True
    assert all(
        not item.observed_in_window
        for item in batch.coverage
        if item.competency != Competency.PREDICTION
    )


@pytest.mark.parametrize("foreign", [True, False])
def test_ownership_gate_treats_foreign_and_missing_sessions_equally(
    learner, database, evidence_clock, foreign
):
    session = start(learner)
    query = evidence_query(
        learner,
        session if foreign else uuid4(),
        evidence_clock(),
        **({"owner_learner_id": uuid4()} if foreign else {}),
    )
    with pytest.raises(LearningError) as caught:
        EngineeringEvidenceService(SqlLearningRepository(database)).extract(query)
    assert caught.value.code == "not_found"


def test_failed_infrastructure_is_unavailable_not_learner_failure(
    learner, database, learning_app, evidence_clock
):
    class BrokenVerifier:
        def observe(self, *args):
            raise TimeoutError("controlled offline failure")

    learning_app.dependency_overrides[get_notes_verifier] = lambda: BrokenVerifier()
    try:
        session = start(learner)
        evidence_clock.advance()
        predict(learner, session)
        evidence_clock.advance()
        submitted = attempt(learner, session, "content")
        evidence_clock.advance()
        assert verify(learner, session, submitted["id"]).json()["status"] == "error"
    finally:
        learning_app.dependency_overrides.pop(get_notes_verifier)
    batch = extraction(learner, database, session, evidence_clock)
    result = find(batch, "verification_finished")
    assert len(result) == 1 and result[0].outcome == "unavailable"
    assert [check.code for check in result[0].checks] == ["execution"]
    assert find(batch, "debugging_recovery_observed") == []
    assert coverage(batch, "verification").availability == "direct"
    assert coverage(batch, "verification").observed_in_window is True


@pytest.mark.parametrize("fault", ["readback_unavailable", "malformed_response"])
def test_committed_runtime_row_does_not_rewrite_recorded_verifier_failure(
    learner, database, learning_app, evidence_clock, fault
):
    class FaultAfterCommit(AsgiNotesVerifier):
        def observe(self, run_id, field_name):
            observed = super().observe(run_id, field_name)
            if fault == "readback_unavailable":
                return replace(observed, notes=None)
            return replace(observed, response_json="unparseable controlled fixture response")

    learning_app.dependency_overrides[get_notes_verifier] = lambda: FaultAfterCommit(
        SqlLearningRepository(database), 5
    )
    try:
        session = start(learner)
        evidence_clock.advance()
        predict(learner, session)
        evidence_clock.advance()
        submitted = attempt(learner, session, "content")
        evidence_clock.advance()
        recorded = verify(learner, session, submitted["id"]).json()
        assert recorded["status"] == "error"
    finally:
        learning_app.dependency_overrides.pop(get_notes_verifier)
    with database.session() as fresh:
        assert len(fresh.scalars(select(m.RuntimeNote)).all()) == 1
    batch = extraction(learner, database, session, evidence_clock)
    observation = find(batch, "verification_finished")[0]
    assert observation.outcome == "unavailable"
    assert {check.code for check in observation.checks} == CHECK_CODES
    assert {check.code: check.matched for check in observation.checks} == {
        check["code"]: check["matched"] for check in recorded["checks"]
    }
    assert find(batch, "debugging_recovery_observed") == []


def test_frontend_cannot_supply_trusted_evidence_or_verification(learner, database, evidence_clock):
    session = start(learner)
    assert (
        post(
            learner,
            f"/sessions/{session}/prediction",
            {"selected_answer": "rejected", "competency": "prediction", "correct": True},
        ).status_code
        == 422
    )
    predict(learner, session)
    submitted = attempt(learner, session)
    assert (
        post(
            learner,
            f"/sessions/{session}/attempts/{submitted['id']}/verify",
            {"status": "passed", "checks": [{"code": "http_status", "matched": True}]},
        ).status_code
        == 422
    )
    assert post(learner, "/engineering-evidence", {"outcome": "success"}).status_code == 404
    batch = extraction(learner, database, session, evidence_clock)
    assert find(batch, "verification_finished") == []


def test_bounded_window_halfopen_and_cap_rejects_partial_evidence(
    learner, database, evidence_clock
):
    session, _, _ = notes_failure(learner, evidence_clock)
    batch = extraction(learner, database, session, evidence_clock)
    prediction = find(batch, "prediction_submitted")[0]
    bounded = extraction(
        learner,
        database,
        session,
        evidence_clock,
        start_at=prediction.occurred_at,
        end_at=prediction.occurred_at + timedelta(microseconds=1),
    )
    assert bounded.observations == (prediction,)
    with pytest.raises(LearningError) as caught:
        extraction(learner, database, session, evidence_clock, max_records=1)
    assert caught.value.code == "evidence_limit"


class AlteredRepository:
    """Corruption/fault injection at the trusted storage adapter boundary only."""

    def __init__(self, repository, method, transform):
        self.repository, self.method, self.transform = repository, method, transform

    @contextmanager
    def read(self):
        with self.repository.read() as source:
            method, transform = self.method, self.transform

            class Store:
                def __getattr__(self, name):
                    original = getattr(source, name)
                    if name == method:
                        return lambda *args: transform(original(*args))
                    return original

            yield Store()

    def write(self):
        raise AssertionError("Evidence extraction must never request a write transaction")


@pytest.mark.parametrize(
    "corruption",
    [
        "question_digest",
        "ordinal",
        "duplicate_ordinal",
        "completion_missing",
        "completion_time",
        "answer_checkpoint",
        "answer_correctness",
        "after_correct",
    ],
)
def test_retrieval_pins_completion_and_answer_provenance_fail_closed(
    learner, database, evidence_clock, corruption
):
    _, session, _ = complete_tasks(learner, database, evidence_clock)
    checkpoint = journey(learner)["checkpoints"][0]
    evidence_clock.now = datetime.fromisoformat(checkpoint["due_at"])
    response = post(learner, f"/retrievals/{checkpoint['id']}/attempts", {"selection": "b"})
    assert response.status_code == 201 and response.json()["correct"] is True
    changes = {
        "question_digest": (
            "checkpoints",
            lambda rows: [replace(rows[0], question_hash="0" * 64), *rows[1:]],
        ),
        "ordinal": ("checkpoints", lambda rows: [replace(rows[0], ordinal=3), *rows[1:]]),
        "duplicate_ordinal": ("checkpoints", lambda rows: [*rows, replace(rows[0], id=uuid4())]),
        "completion_missing": (
            "checkpoints",
            lambda rows: [replace(rows[0], completed_at=None), *rows[1:]],
        ),
        "completion_time": (
            "checkpoints",
            lambda rows: [
                replace(rows[0], completed_at=evidence_clock() + timedelta(seconds=1)),
                *rows[1:],
            ],
        ),
        "answer_checkpoint": (
            "retrieval_attempts",
            lambda rows: [replace(row, checkpoint_id=uuid4()) for row in rows],
        ),
        "answer_correctness": (
            "retrieval_attempts",
            lambda rows: [replace(row, correct=False) for row in rows],
        ),
        "after_correct": (
            "retrieval_attempts",
            lambda rows: (
                [
                    *rows,
                    replace(
                        rows[0],
                        id=uuid4(),
                        number=2,
                        selection="a",
                        correct=False,
                        created_at=evidence_clock() + timedelta(seconds=1),
                    ),
                ]
                if rows
                else []
            ),
        ),
    }
    repository = AlteredRepository(SqlLearningRepository(database), *changes[corruption])
    with pytest.raises(LearningError) as caught:
        EngineeringEvidenceService(repository).extract(
            evidence_query(learner, session, evidence_clock())
        )
    assert caught.value.code == "evidence_integrity"


@pytest.mark.parametrize(
    "corruption",
    [
        "version_id",
        "version",
        "digest",
        "family",
        "prediction_session",
        "prediction_time",
        "attempt_session",
        "attempt_duplicate",
        "run_session",
        "run_attempt",
        "run_duplicate",
        "check_run",
        "check_origin",
        "check_duplicate",
        "check_missing",
        "check_false_outcome",
        "check_flag_http_status",
        "check_flag_api_response",
        "check_flag_validation",
        "check_flag_row_count",
        "check_flag_stored_values",
    ],
)
def test_forged_records_or_pins_fail_closed(learner, database, evidence_clock, corruption):
    session, _, _ = notes_failure(learner, evidence_clock)
    replacements = {
        "version_id": ("version_by_id", lambda row: replace(row, id=uuid4())),
        "version": ("version_by_id", lambda row: replace(row, version="2.0.0")),
        "digest": ("version_by_id", lambda row: replace(row, content_hash="0" * 64)),
        "family": ("version_by_id", lambda row: replace(row, lesson_id="untrusted-lesson")),
        "prediction_session": ("prediction", lambda row: replace(row, session_id=uuid4())),
        "prediction_time": (
            "prediction",
            lambda row: replace(row, created_at=datetime(1999, 1, 1, tzinfo=UTC)),
        ),
        "attempt_session": ("attempts", lambda rows: [replace(rows[0], session_id=uuid4())]),
        "attempt_duplicate": ("attempts", lambda rows: [*rows, rows[0]]),
        "run_session": ("runs", lambda rows: [replace(rows[0], session_id=uuid4())]),
        "run_attempt": ("runs", lambda rows: [replace(rows[0], attempt_id=uuid4())]),
        "run_duplicate": ("runs", lambda rows: [*rows, rows[0]]),
        "check_run": ("checks", lambda rows: [replace(row, run_id=uuid4()) for row in rows]),
        "check_origin": ("checks", lambda rows: [replace(rows[0], source="frontend"), *rows[1:]]),
        "check_duplicate": ("checks", lambda rows: [*rows, rows[0]]),
        "check_missing": ("checks", lambda rows: rows[1:]),
        "check_false_outcome": (
            "checks",
            lambda rows: [replace(row, matched=True) for row in rows],
        ),
    }
    if corruption.startswith("check_flag_"):
        code = corruption.removeprefix("check_flag_")
        replacements[corruption] = (
            "checks",
            lambda rows: [
                replace(row, matched=not row.matched) if row.code == code else row for row in rows
            ],
        )
    repository = AlteredRepository(SqlLearningRepository(database), *replacements[corruption])
    with pytest.raises(LearningError) as caught:
        EngineeringEvidenceService(repository).extract(
            evidence_query(learner, session, evidence_clock())
        )
    assert caught.value.code == "evidence_integrity"


def test_out_of_order_store_results_are_deterministic(learner, database, evidence_clock):
    session, _, _ = notes_failure(learner, evidence_clock)
    evidence_clock.advance()
    attempt(learner, session, "content")
    expected = extraction(learner, database, session, evidence_clock)
    repository = AlteredRepository(
        SqlLearningRepository(database), "attempts", lambda rows: list(reversed(rows))
    )
    actual = EngineeringEvidenceService(repository).extract(
        evidence_query(learner, session, evidence_clock())
    )
    assert actual == expected


def test_finalized_source_rows_remain_append_only(learner, database, evidence_clock):
    from sqlalchemy import update

    session, wrong, _ = notes_failure(learner, evidence_clock)
    before = extraction(learner, database, session, evidence_clock)
    with pytest.raises(IntegrityError), database.session() as fresh, fresh.begin():
        fresh.execute(
            update(m.Attempt).where(m.Attempt.id == UUID(wrong["id"])).values(field_name="content")
        )
    assert extraction(learner, database, session, evidence_clock) == before


@pytest.mark.parametrize("delivered", [True, False])
def test_hint_requests_results_retries_and_causal_assistance(
    learner, database, evidence_clock, delivered
):
    class FailedTutor(FakeTutorProvider):
        def generate_hint(self, request):
            raise TimeoutError("controlled fixture failure")

    session, _, _ = notes_failure(learner, evidence_clock)
    owner = UUID(learner.get("/api/v1/learners/me").json()["learner_id"])
    service = LearningService(
        SqlLearningRepository(database),
        FakeTutorProvider() if delivered else FailedTutor(),
        evidence_clock,
    )
    key = str(uuid4())
    evidence_clock.advance()
    hint = service.hint(owner, UUID(session), None, key)
    assert service.hint(owner, UUID(session), None, key) == hint
    evidence_clock.advance()
    submitted = service.attempt(owner, UUID(session), "body", "", str(uuid4()))
    batch = extraction(learner, database, session, evidence_clock)
    requests = [item for item in batch.hint_events if item.event_type == "hint_requested"]
    results = [item for item in batch.hint_events if item.event_type == "hint_finalized"]
    assert len(requests) == len(results) == 1
    assert requests[0].outcome == "requested"
    assert results[0].outcome == ("delivered" if delivered else "error")
    assert requests[0].id != results[0].id
    observation = next(
        item
        for item in find(batch, "modification_submitted")
        if item.source.record_id == submitted.id
    )
    assert observation.assistance.category == ("tutor_assisted" if delivered else "unknown")
    assert [ref.record_id for ref in observation.assistance.requested_before] == [hint.id]
    assert [ref.record_id for ref in observation.assistance.delivered_before] == (
        [hint.id] if delivered else []
    )


def test_pending_help_is_not_delivered_and_later_delivery_does_not_rewrite_attempt(
    learner, database, evidence_clock
):
    session, _, _ = notes_failure(learner, evidence_clock)
    owner = UUID(learner.get("/api/v1/learners/me").json()["learner_id"])
    tutor = BlockingTutor()
    service = LearningService(SqlLearningRepository(database), tutor, evidence_clock)
    evidence_clock.advance()
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.hint, owner, UUID(session), None, key)
        try:
            assert tutor.entered.wait(5)
            evidence_clock.advance()
            submitted = service.attempt(owner, UUID(session), "body", "", str(uuid4()))
            pending = extraction(learner, database, session, evidence_clock)
            observation = next(
                item
                for item in find(pending, "modification_submitted")
                if item.source.record_id == submitted.id
            )
            assert submitted.hints_before == 1
            assert observation.assistance.category == "unknown"
            assert len(observation.assistance.requested_before) == 1
            assert observation.assistance.delivered_before == ()
            assert [item.outcome for item in pending.hint_events] == ["requested"]
            evidence_clock.advance()
        finally:
            tutor.release.set()
        assert future.result(timeout=5).status == "delivered"
    finalized = extraction(learner, database, session, evidence_clock)
    assert next(item for item in finalized.observations if item.id == observation.id) == observation
    assert len(finalized.hint_events) == 2


def test_no_new_hint_does_not_restore_independence_after_assisted_attempt(
    learner, database, evidence_clock
):
    session, _, _ = notes_failure(learner, evidence_clock)
    owner = UUID(learner.get("/api/v1/learners/me").json()["learner_id"])
    service = LearningService(SqlLearningRepository(database), FakeTutorProvider(), evidence_clock)
    evidence_clock.advance()
    service.hint(owner, UUID(session), None, str(uuid4()))
    evidence_clock.advance()
    wrong = service.attempt(owner, UUID(session), "body", "", str(uuid4()))
    evidence_clock.advance()
    assert verify(learner, session, str(wrong.id)).json()["status"] == "failed"
    evidence_clock.advance()
    corrected = service.attempt(owner, UUID(session), "content", "", str(uuid4()))
    batch = extraction(learner, database, session, evidence_clock)
    observed = [
        item
        for item in find(batch, "modification_submitted")
        if item.source.record_id in {wrong.id, corrected.id}
    ]
    assert len(observed) == 2
    assert all(item.assistance.category == "tutor_assisted" for item in observed)
    assert observed[0].assistance.delivered_before == observed[1].assistance.delivered_before


def test_historical_delivered_hint_has_no_invented_request_timestamp(
    learner, database, evidence_clock
):
    session, _, _ = notes_failure(learner, evidence_clock)
    repository = SqlLearningRepository(database)
    evidence_clock.advance()
    historical = TutorInteraction(
        uuid4(),
        UUID(session),
        None,
        1,
        "Recorded historical fixture guidance.",
        "delivered",
        str(uuid4()),
        evidence_clock(),
    )
    # This is the pre-reservation source shape, retained by migration 0007.
    with repository.write() as store:
        store.add_hint(historical)
    evidence_clock.advance()
    submitted = attempt(learner, session, "content")
    batch = extraction(learner, database, session, evidence_clock)
    assert [item.event_type for item in batch.hint_events] == ["hint_finalized"]
    observation = next(
        item
        for item in find(batch, "modification_submitted")
        if item.source.record_id == UUID(submitted["id"])
    )
    assert observation.assistance.category == "tutor_assisted"
    assert observation.assistance.requested_before == ()
    assert [ref.record_id for ref in observation.assistance.delivered_before] == [historical.id]


def test_equal_delivery_and_action_timestamps_do_not_prove_causal_assistance(
    learner, database, evidence_clock
):
    session, _, _ = notes_failure(learner, evidence_clock)
    owner = UUID(learner.get("/api/v1/learners/me").json()["learner_id"])
    service = LearningService(SqlLearningRepository(database), FakeTutorProvider(), evidence_clock)
    evidence_clock.advance()
    result = service.hint(owner, UUID(session), None, str(uuid4()))
    submitted = service.attempt(owner, UUID(session), "content", "", str(uuid4()))
    assert result.created_at == submitted.created_at
    batch = extraction(learner, database, session, evidence_clock)
    observation = next(
        item
        for item in find(batch, "modification_submitted")
        if item.source.record_id == submitted.id
    )
    assert observation.assistance.category == "unknown"
    assert observation.assistance.delivered_before == ()


def test_session_uses_exact_pin_even_after_later_version_is_published(
    learner, database, evidence_clock
):
    session, _, _ = notes_failure(learner, evidence_clock)
    repository = SqlLearningRepository(database)
    original = extraction(learner, database, session, evidence_clock)
    with repository.write() as store:
        pin = store.version_by_id(original.observations[0].lesson.version_id)
        store.publish(replace(pin, id=uuid4(), version="1.1.0"))
    assert extraction(learner, database, session, evidence_clock) == original


def test_offset_query_timestamps_normalize_to_utc_without_changing_event_identity(
    learner, database, evidence_clock
):
    session, _, _ = notes_failure(learner, evidence_clock)
    query = evidence_query(learner, session, evidence_clock())
    offset = timezone(timedelta(hours=5, minutes=30))
    equivalent = EvidenceQuery.model_validate(
        {
            **query.model_dump(),
            "start_at": query.start_at.astimezone(offset),
            "end_at": query.end_at.astimezone(offset),
            "as_of": query.as_of.astimezone(offset),
        }
    )
    service = EngineeringEvidenceService(SqlLearningRepository(database))
    assert service.extract(query) == service.extract(equivalent)
