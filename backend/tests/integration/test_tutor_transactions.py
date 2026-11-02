"""Hint requests reserve once without holding the learner write gate during tutoring."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError

from app.ai.providers.fake import FakeTutorProvider
from app.api.presentation import present_progress
from app.db import models as m
from app.db.learning import SqlLearningRepository
from app.domain.learning import LearningError, LearningEvent
from app.schemas.tutoring import TutorMessage
from app.services.learning import LearningService
from tests.integration.test_learning import attempt, predict, start, verify


class MutableClock:
    def __init__(self):
        self.now = datetime.now(UTC)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


class BlockingTutor(FakeTutorProvider):
    def __init__(self):
        self.entered, self.release = Event(), Event()
        self.calls = []

    def generate_hint(self, request):
        self.calls.append(request)
        self.entered.set()
        if not self.release.wait(10):
            raise TimeoutError("controlled fixture deadline")
        return super().generate_hint(request)


def setup_service(learner, database, tutor=None, clock=None):
    session = UUID(start(learner))
    predict(learner, str(session))
    owner = UUID(learner.get("/api/v1/learners/me").json()["learner_id"])
    clock = clock or MutableClock()
    tutor = tutor or FakeTutorProvider()
    repository = SqlLearningRepository(database)
    return LearningService(repository, tutor, clock), owner, session, clock


def operations(database):
    with database.session() as db:
        return db.scalars(select(m.HintOperation).order_by(m.HintOperation.sequence)).all()


def test_blocked_provider_allows_independent_write_and_truthful_attempt_history(learner, database):
    tutor = BlockingTutor()
    service, owner, session, clock = setup_service(learner, database, tutor)
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.hint, owner, session, None, key)
        try:
            assert tutor.entered.wait(5)
            with SqlLearningRepository(database).write() as store:
                store.add_event(LearningEvent(uuid4(), session, "independent_write", None, clock()))
            pending = present_progress(service.progress(owner, session))
            assert pending.summary.hint_request_count == 1
            assert pending.summary.hints_delivered == 0 and pending.hints == []
            clock.advance(1)
            submitted = service.attempt(owner, session, "body", "", str(uuid4()))
            assert submitted.hints_before == 1
            clock.advance(1)
        finally:
            tutor.release.set()
        delivered = future.result(timeout=5)
    assert delivered.status == "delivered" and delivered.created_at > submitted.created_at
    assert service.hint(owner, session, None, key) == delivered
    assert len(tutor.calls) == 1 and operations(database)[0].status == "finalized"


def test_concurrent_retries_do_not_call_provider_or_consume_another_slot(learner, database):
    tutor = BlockingTutor()
    service, owner, session, _ = setup_service(learner, database, tutor)
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.hint, owner, session, None, key)
        try:
            assert tutor.entered.wait(5)
            for duplicate_key in (key, str(uuid4())):
                with pytest.raises(LearningError) as exc:
                    service.hint(owner, session, None, duplicate_key)
                assert exc.value.code == "conflict"
            assert len(operations(database)) == len(tutor.calls) == 1
            with pytest.raises(LearningError) as exc:
                service.hint(uuid4(), session, None, key)
            assert exc.value.code == "not_found"
        finally:
            tutor.release.set()
        result = future.result(timeout=5)
    assert service.hint(owner, session, None, key) == result
    assert len(tutor.calls) == 1


def test_stale_retry_finalizes_error_and_late_worker_cannot_overwrite_it(learner, database):
    tutor = BlockingTutor()
    service, owner, session, clock = setup_service(learner, database, tutor)
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.hint, owner, session, None, key)
        try:
            assert tutor.entered.wait(5)
            clock.advance(31)
            recovered = service.hint(owner, session, None, key)
            assert recovered.status == "error" and recovered.text is None
            assert operations(database)[0].status == "finalized"
        finally:
            tutor.release.set()
        assert future.result(timeout=5) == recovered
    assert len(tutor.calls) == 1
    second = service.hint(owner, session, None, str(uuid4()))
    assert second.sequence == 2 and len(tutor.calls) == 2


def test_expired_third_reservation_is_committed_even_when_new_request_hits_quota(learner, database):
    tutor = BlockingTutor()
    tutor.release.set()
    service, owner, session, clock = setup_service(learner, database, tutor)
    for _ in range(2):
        assert service.hint(owner, session, None, str(uuid4())).status == "delivered"
    tutor.entered.clear()
    tutor.release.clear()
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.hint, owner, session, None, key)
        try:
            assert tutor.entered.wait(5)
            clock.advance(31)
            with pytest.raises(LearningError) as exc:
                service.hint(owner, session, None, str(uuid4()))
            assert exc.value.code == "hint_limit"
            assert [operation.status for operation in operations(database)] == ["finalized"] * 3
            saved = service.progress(owner, session).hints
            assert len(saved) == 3 and saved[-1].status == "error"
        finally:
            tutor.release.set()
        assert future.result(timeout=5) == saved[-1]
    assert len(tutor.calls) == 3


@pytest.mark.parametrize("terminal", ["abandoned", "completed"])
def test_session_terminal_during_provider_work_never_receives_guidance(learner, database, terminal):
    tutor = BlockingTutor()
    service, owner, session, clock = setup_service(learner, database, tutor)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.hint, owner, session, None, str(uuid4()))
        try:
            assert tutor.entered.wait(5)
            if terminal == "abandoned":
                service.abandon(owner, session)
            else:
                submitted = attempt(learner, str(session), "content")
                assert verify(learner, str(session), submitted["id"]).json()["status"] == "passed"
            clock.advance(1)
        finally:
            tutor.release.set()
        result = future.result(timeout=5)
    assert result.status == "error" and result.text is None
    assert service.progress(owner, session).session.state == terminal


def test_authorization_expiry_is_checked_before_and_after_provider(learner, database):
    clock = MutableClock()

    class Slow(FakeTutorProvider):
        calls = 0

        def generate_hint(self, request):
            self.calls += 1
            clock.advance(5)
            return super().generate_hint(request)

    tutor = Slow()
    service, owner, session, _ = setup_service(learner, database, tutor, clock)
    key = str(uuid4())
    with pytest.raises(LearningError) as exc:
        service.hint(owner, session, None, key, authorization_expires_at=clock())
    assert exc.value.code == "unauthenticated" and not operations(database) and tutor.calls == 0
    deadline = clock() + timedelta(seconds=3)
    with pytest.raises(LearningError) as exc:
        service.hint(owner, session, None, key, authorization_expires_at=deadline)
    assert exc.value.code == "unauthenticated" and tutor.calls == 1
    stored = service.progress(owner, session).hints[0]
    assert stored.status == "error" and operations(database)[0].deadline_at == deadline
    assert service.hint(owner, session, None, key) == stored
    assert tutor.calls == 1


@pytest.mark.parametrize("kind", ["exception", "none", "empty", "ai", "authority"])
def test_invalid_or_failed_tutor_output_is_sanitized_once(learner, database, kind, capsys, caplog):
    class Invalid(FakeTutorProvider):
        calls = 0

        def generate_hint(self, request):
            self.calls += 1
            if kind == "exception":
                raise RuntimeError("private-provider-token")
            if kind == "none":
                return None
            return TutorMessage.model_construct(
                text="" if kind == "empty" else "private-provider-token",
                source="ai" if kind == "ai" else "test_fixture",
                interpretation_only=kind != "authority",
            )

    tutor = Invalid()
    service, owner, session, _ = setup_service(learner, database, tutor)
    key = str(uuid4())
    result = service.hint(owner, session, None, key)
    assert result.status == "error" and result.text is None
    assert service.hint(owner, session, None, key) == result and tutor.calls == 1
    assert "private-provider-token" not in caplog.text + capsys.readouterr().err


def test_finalization_commit_failure_leaves_reservation_for_safe_error_recovery(learner, database):
    class Counting(FakeTutorProvider):
        calls = 0

        def generate_hint(self, request):
            self.calls += 1
            return super().generate_hint(request)

    tutor = Counting()
    service, owner, session, clock = setup_service(learner, database, tutor)
    key = str(uuid4())

    def mark(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO TUTOR_INTERACTIONS"):
            connection.info["fail_hint_commit"] = True

    def fail(connection):
        if connection.info.pop("fail_hint_commit", False):
            raise OperationalError("private-statement", {}, RuntimeError("private-token"))

    event.listen(database.engine, "before_cursor_execute", mark)
    event.listen(database.engine, "commit", fail)
    try:
        with pytest.raises(LearningError) as exc:
            service.hint(owner, session, None, key)
        assert exc.value.code == "dependency_unavailable"
    finally:
        event.remove(database.engine, "before_cursor_execute", mark)
        event.remove(database.engine, "commit", fail)
    assert tutor.calls == 1 and service.progress(owner, session).hints == []
    assert operations(database)[0].status == "pending"
    with pytest.raises(LearningError) as exc:
        service.hint(owner, session, None, key)
    assert exc.value.code == "conflict"
    clock.advance(31)
    assert service.hint(owner, session, None, key).status == "error" and tutor.calls == 1


def test_reservation_commit_failure_never_invokes_tutor(learner, database):
    class Counting(FakeTutorProvider):
        calls = 0

        def generate_hint(self, request):
            self.calls += 1
            return super().generate_hint(request)

    tutor = Counting()
    service, owner, session, _ = setup_service(learner, database, tutor)

    def mark(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO HINT_OPERATIONS"):
            connection.info["fail_reservation_commit"] = True

    def fail(connection):
        if connection.info.pop("fail_reservation_commit", False):
            raise OperationalError("private-statement", {}, RuntimeError("private-token"))

    event.listen(database.engine, "before_cursor_execute", mark)
    event.listen(database.engine, "commit", fail)
    try:
        with pytest.raises(LearningError) as exc:
            service.hint(owner, session, None, str(uuid4()))
        assert exc.value.code == "dependency_unavailable"
    finally:
        event.remove(database.engine, "before_cursor_execute", mark)
        event.remove(database.engine, "commit", fail)
    assert tutor.calls == 0 and operations(database) == []
    progress = service.progress(owner, session)
    assert progress.hints == [] and progress.hint_request_count == 0
    assert not any(item.event_type == "hint_requested" for item in progress.events)


def test_worker_resuming_after_reservation_deadline_does_not_start_tutor(
    learner, database, monkeypatch
):
    class Counting(FakeTutorProvider):
        calls = 0

        def generate_hint(self, request):
            self.calls += 1
            return super().generate_hint(request)

    tutor = Counting()
    service, owner, session, clock = setup_service(learner, database, tutor)
    reserve = service._reserve_hint

    def reserve_then_suspend(*args):
        result = reserve(*args)
        clock.advance(31)
        return result

    monkeypatch.setattr(service, "_reserve_hint", reserve_then_suspend)
    result = service.hint(owner, session, None, str(uuid4()))
    assert result.status == "error" and result.text is None
    assert tutor.calls == 0 and operations(database)[0].status == "finalized"


def test_foreign_attempt_and_idempotency_context_are_preserved(learner, database):
    service, owner, session, _ = setup_service(learner, database)
    another = start(learner)
    predict(learner, another)
    foreign = attempt(learner, another)
    with pytest.raises(LearningError) as exc:
        service.hint(owner, session, UUID(foreign["id"]), str(uuid4()))
    assert exc.value.code == "not_found" and not operations(database)
    key = str(uuid4())
    service.hint(owner, session, None, key)
    submitted = service.attempt(owner, session, "body", "", str(uuid4()))
    with pytest.raises(LearningError) as exc:
        service.hint(owner, session, submitted.id, key)
    assert exc.value.code == "conflict" and len(operations(database)) == 1


@pytest.mark.parametrize("timeout", [0, -1, 121, True, float("inf"), float("nan")])
def test_operation_timeout_is_bounded(database, timeout):
    with pytest.raises(ValueError):
        LearningService(
            SqlLearningRepository(database), FakeTutorProvider(), hint_timeout_seconds=timeout
        )
