"""Real adapter execution with bounded, deterministic worker interleavings."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event, Lock
from uuid import UUID, uuid4

import anyio
import pytest
from sqlalchemy import select

from app.ai.providers.fake import FakeTutorProvider
from app.db import models as m
from app.db.learning import SqlLearningRepository
from app.domain.learning import LearningError
from app.services.catalog import seed_transfer_lesson
from app.services.learning import LearningService
from app.services.verification import VerificationService
from app.verification import asgi_notes, asgi_tasks
from tests.integration.test_learning import attempt, predict, start, verify
from tests.integration.test_transfer_retrieval import (
    MutableClock,
    complete_original,
    mapping,
    start_transfer,
)


class PauseFirstObservation:
    def __init__(self, delegate, phase="after"):
        self.delegate, self.phase = delegate, phase
        self.entered, self.release, self.lock = Event(), Event(), Lock()
        self.run_id = None

    def observe(self, run_id, field):
        with self.lock:
            first = self.run_id is None
            if first:
                self.run_id = run_id
        if not first:
            return self.delegate.observe(run_id, field)
        result = self.delegate.observe(run_id, field) if self.phase == "after" else None
        self.entered.set()
        if not self.release.wait(15):
            raise RuntimeError("Test failed to release its controlled worker")
        return result if self.phase == "after" else self.delegate.observe(run_id, field)


@pytest.fixture(params=["notes", "tasks"])
def exercise(request, learner, database):
    clock = MutableClock()
    learner.app.state.clock = clock
    repository = SqlLearningRepository(database)
    if request.param == "tasks":
        seed_transfer_lesson(repository)
        complete_original(learner)
        session = start_transfer(learner)
        assert predict(learner, session).status_code == 201
        flat = mapping(learner, session, "flat").json()
        assert verify(learner, session, flat["id"]).json()["status"] == "failed"
        candidate = mapping(learner, session, "nested").json()
        adapter = asgi_tasks.AsgiTasksVerifier(repository, 2)
        model = m.RuntimeTask
    else:
        session = start(learner)
        assert predict(learner, session).status_code == 201
        candidate = attempt(learner, session, "content")
        adapter = asgi_notes.AsgiNotesVerifier(repository, 2)
        model = m.RuntimeNote
    owner = UUID(learner.get("/api/v1/learners/me").json()["learner_id"])

    def service(observation_adapter=adapter):
        return VerificationService(
            repository,
            observation_adapter
            if request.param == "notes"
            else asgi_notes.AsgiNotesVerifier(repository, 2),
            2,
            tasks_verifier=observation_adapter if request.param == "tasks" else None,
            clock=clock,
        )

    return {
        "kind": request.param,
        "database": database,
        "repository": repository,
        "clock": clock,
        "owner": owner,
        "session": UUID(session),
        "attempt": UUID(candidate["id"]),
        "adapter": adapter,
        "model": model,
        "service": service,
    }


def rows_for(exercise, run_id):
    with exercise["database"].session() as fresh:
        return fresh.scalars(
            select(exercise["model"]).where(exercise["model"].run_id == run_id)
        ).all()


def saved(exercise):
    return LearningService(exercise["repository"], FakeTutorProvider()).progress(
        exercise["owner"], exercise["session"]
    )


def test_concurrent_verification_reserves_once_and_replays_without_duplicate_writes(exercise):
    gate = PauseFirstObservation(exercise["adapter"])
    service = exercise["service"](gate)
    args = exercise["owner"], exercise["session"], exercise["attempt"]
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=4) as pool:
        first = pool.submit(service.verify, *args, key)
        try:
            assert gate.entered.wait(10)
            competitors = [
                pool.submit(service.verify, *args, candidate)
                for candidate in [key, key, str(uuid4())]
            ]
            for pending in competitors:
                with pytest.raises(LearningError, match="already running"):
                    pending.result(timeout=10)
            assert saved(exercise).session.state == "verification_pending"
        finally:
            gate.release.set()
        result = first.result(timeout=10)
    assert result.status == "passed"
    assert service.verify(*args, key) == result
    assert service.verify(*args, str(uuid4())) == result
    assert len(rows_for(exercise, result.id)) == 1
    runs = [run for run, _ in saved(exercise).runs if run.attempt_id == exercise["attempt"]]
    assert runs == [result]


def test_late_success_keeps_evidence_but_cannot_reopen_an_abandoned_session(exercise):
    gate = PauseFirstObservation(exercise["adapter"])
    service = exercise["service"](gate)
    args = exercise["owner"], exercise["session"], exercise["attempt"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(service.verify, *args, str(uuid4()))
        try:
            assert gate.entered.wait(10)
            abandoned = LearningService(exercise["repository"], FakeTutorProvider()).abandon(
                *args[:2]
            )
            assert abandoned.state == "abandoned"
        finally:
            gate.release.set()
        result = pending.result(timeout=10)
    assert result.status == "passed"
    history = saved(exercise)
    assert history.session.state == "abandoned" and history.session.completed_at is None
    assert len(rows_for(exercise, result.id)) == 1
    with exercise["repository"].read() as store:
        assert store.checkpoints(exercise["owner"]) == []


@pytest.mark.parametrize("phase", ["before", "after"])
def test_stale_worker_cannot_finalize_or_write_into_a_recovered_run(exercise, phase):
    gate = PauseFirstObservation(exercise["adapter"], phase)
    service = exercise["service"](gate)
    args = exercise["owner"], exercise["session"], exercise["attempt"]
    old_key = str(uuid4())
    with ThreadPoolExecutor(max_workers=1) as pool:
        old_worker = pool.submit(service.verify, *args, old_key)
        try:
            assert gate.entered.wait(10)
            exercise["clock"].now += timedelta(seconds=61)
            recovered = service.verify(*args, str(uuid4()))
            assert recovered.status == "passed" and recovered.id != gate.run_id
            replay = service.verify(*args, old_key)
            assert replay.status == "error" and replay.id == gate.run_id
        finally:
            gate.release.set()
        with pytest.raises(LearningError, match="preserved history"):
            old_worker.result(timeout=10)
    assert service.verify(*args, old_key) == replay
    assert len(rows_for(exercise, recovered.id)) == 1
    # An already committed old row is retained in its old scope, never reused.
    assert len(rows_for(exercise, gate.run_id)) == (1 if phase == "after" else 0)
    history = saved(exercise)
    assert history.session.state == "completed"
    assert [
        (r.status, [c.code for c in checks]) for r, checks in history.runs if r.id == gate.run_id
    ] == [
        ("error", ["execution"]),
    ]
    with exercise["repository"].read() as store:
        assert len(store.checkpoints(exercise["owner"])) == (
            2 if exercise["kind"] == "tasks" else 0
        )


def test_real_asgi_timeout_records_error_and_new_key_can_retry(exercise, monkeypatch):
    module = asgi_notes if exercise["kind"] == "notes" else asgi_tasks
    factory_name = "create_notes_app" if exercise["kind"] == "notes" else "create_tasks_app"
    original = getattr(module, factory_name)

    def delayed_app(repository, run_id):
        app = original(repository, run_id)

        @app.middleware("http")
        async def delay(request, call_next):
            await anyio.sleep(1)
            return await call_next(request)

        return app

    monkeypatch.setattr(module, factory_name, delayed_app)
    adapter_type = (
        module.AsgiNotesVerifier if exercise["kind"] == "notes" else module.AsgiTasksVerifier
    )
    service = exercise["service"](adapter_type(exercise["repository"], 0.01))
    args = exercise["owner"], exercise["session"], exercise["attempt"]
    key = str(uuid4())
    error = service.verify(*args, key)
    assert error.status == "error"
    assert rows_for(exercise, error.id) == []
    assert saved(exercise).session.state == "verification_pending"
    assert service.verify(*args, key) == error
    monkeypatch.setattr(module, factory_name, original)
    recovered = exercise["service"]().verify(*args, str(uuid4()))
    assert recovered.status == "passed" and recovered.id != error.id
    assert len(rows_for(exercise, recovered.id)) == 1
    assert service.verify(*args, key) == error
