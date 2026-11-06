from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event, Lock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from app.db import models as m
from app.db.learning import SqlLearningRepository
from app.db.session import Database
from app.services.catalog import seed_transfer_lesson
from app.verification.asgi_notes import AsgiNotesVerifier
from app.verification.asgi_tasks import AsgiTasksVerifier
from tests.integration.test_learning import attempt, post, predict, progress, start, verify
from tests.integration.test_transfer_retrieval import complete_original, mapping, start_transfer


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.mark.parametrize("exercise", ["notes", "tasks"])
@pytest.mark.parametrize("concurrent_action", ["recover", "replace", "abandon"])
def test_late_real_verifier_respects_persisted_completion_authority(
    learner: TestClient,
    learning_app: FastAPI,
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
    exercise: str,
    concurrent_action: str,
) -> None:
    clock = MutableClock()
    learning_app.state.clock = clock
    if exercise == "notes":
        session = start(learner)
        assert predict(learner, session).status_code == 201
        candidate = attempt(learner, session, "content")
        verifier_type = AsgiNotesVerifier
        runtime_type = m.RuntimeNote
    else:
        seed_transfer_lesson(SqlLearningRepository(database))
        complete_original(learner)
        session = start_transfer(learner)
        assert predict(learner, session).status_code == 201
        flat = mapping(learner, session, "flat")
        assert flat.status_code == 201
        assert verify(learner, session, flat.json()["id"]).json()["status"] == "failed"
        corrected = mapping(learner, session, "nested")
        assert corrected.status_code == 201
        candidate = corrected.json()
        verifier_type = AsgiTasksVerifier
        runtime_type = m.RuntimeTask

    ready, resume, lock = Event(), Event(), Lock()
    original_observe = verifier_type.observe
    observations = 0

    def pause_after_real_fresh_read(self, run_id, field_name):
        nonlocal observations
        # The real private FastAPI endpoint commits a row and independently
        # reads it back before this worker is paused; evidence is never mocked.
        observed = original_observe(self, run_id, field_name)
        with lock:
            observations += 1
            first = observations == 1
        if first:
            ready.set()
            assert resume.wait(5), "The paused verification must be released"
        return observed

    monkeypatch.setattr(verifier_type, "observe", pause_after_real_fresh_read)
    late_writes = []

    def capture_late_write(connection, cursor, statement, parameters, context, executemany):
        operation = statement.lstrip().split(None, 1)[0].upper()
        if operation in {"INSERT", "UPDATE", "DELETE"}:
            compiled = getattr(context.compiled, "statement", None)
            table = getattr(getattr(compiled, "table", None), "name", None)
            late_writes.append((operation, table))

    capture_enabled = False
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=1) as workers:
        pending = workers.submit(verify, learner, session, candidate["id"], key)
        try:
            assert ready.wait(5), "The actual verifier must reach its independent read"
            recovered = None
            if concurrent_action == "abandon":
                assert post(learner, f"/sessions/{session}/abandon", {}).status_code == 200
            else:
                clock.now += timedelta(seconds=61)
                recovered = verify(learner, session, candidate["id"], key)
                assert recovered.status_code == 200
                assert recovered.json()["status"] == "error"
                assert [check["code"] for check in recovered.json()["checks"]] == ["execution"]
                if concurrent_action == "replace":
                    replacement = verify(learner, session, candidate["id"], str(uuid4()))
                    assert replacement.status_code == 200
                    assert replacement.json()["status"] == "passed"
                    assert len(replacement.json()["checks"]) == 5
                    assert all(check["matched"] for check in replacement.json()["checks"])
            before = progress(learner, session)
            journey_before = learner.get("/api/v1/learners/me/journey").json()
            run_ids = [UUID(run["id"]) for run in before["verifications"]]
            with database.session() as fresh:
                rows_before = fresh.scalar(
                    select(func.count())
                    .select_from(runtime_type)
                    .where(runtime_type.run_id.in_(run_ids))
                )
            if concurrent_action != "abandon":
                # Observe only late finalization, after its real independent
                # evidence read and after the competing recovery has committed.
                event.listen(database.engine, "before_cursor_execute", capture_late_write)
                capture_enabled = True
        finally:
            resume.set()
        try:
            late = pending.result(timeout=5)
        finally:
            if capture_enabled:
                event.remove(database.engine, "before_cursor_execute", capture_late_write)

    saved = progress(learner, session)
    journey_after = learner.get("/api/v1/learners/me/journey").json()
    with database.session() as fresh:
        assert (
            fresh.scalar(
                select(func.count())
                .select_from(runtime_type)
                .where(runtime_type.run_id.in_(run_ids))
            )
            == rows_before
        )
    if concurrent_action == "abandon":
        assert late.status_code == 200, late.text
        assert late.json()["status"] == "passed"
        assert len(late.json()["checks"]) == 5
        assert all(check["matched"] for check in late.json()["checks"])
        assert saved["session"]["state"] == "abandoned"
        assert journey_after["checkpoints"] == []
    else:
        # Reject the stale original, while an explicit replay still returns its
        # saved terminal evidence. No late domain write is even attempted.
        assert recovered is not None
        assert late.status_code == 409, late.text
        assert late.json()["error"]["code"] == "conflict"
        assert late.json()["error"]["message"] == "The write conflicts with preserved history."
        # This sole serialization UPDATE belongs to repository.write(), not to
        # evidence/session/checkpoint/event finalization. Match its exact table.
        assert late_writes == [("UPDATE", m.WriteGate.__tablename__)]
        assert saved == before
        assert journey_after == journey_before
        replay = verify(learner, session, candidate["id"], key)
        assert replay.status_code == 200
        assert replay.json() == recovered.json()
        assert saved["session"]["state"] == (
            "completed" if concurrent_action == "replace" else "verification_pending"
        )
        if exercise == "tasks" and concurrent_action == "replace":
            assert [
                datetime.fromisoformat(item["due_at"]) for item in journey_after["checkpoints"]
            ] == [clock.now + timedelta(days=days) for days in (1, 7)]
        else:
            assert journey_after["checkpoints"] == []
