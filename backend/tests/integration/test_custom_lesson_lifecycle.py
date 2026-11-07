"""Custom job/database finalization shares the application's actual shutdown lifetime."""

from datetime import UTC, datetime
from threading import Event, current_thread
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.ai_settings import AIClientSettings
from app.db.models import User
from app.main import create_app
from app.repositories.custom_lessons import RequestFields
from app.services.custom_lesson_generation import GenerationFailed
from tests.unit.test_ai_resources import ClosingTransport


class FailedGenerator:
    def generate(self, *args, **kwargs):
        return GenerationFailed("provider_error")


def test_shutdown_retains_owned_database_and_shared_transport_through_actual_job_commit(
    settings, database, monkeypatch
):
    now, owner = datetime.now(UTC), uuid4()
    with database.session() as session, session.begin():
        session.add(User(id=owner, status="active", created_at=now, updated_at=now))
    entered, release, committed, disposed = Event(), Event(), Event(), Event()
    disposed_after_commit = []
    transport = ClosingTransport()
    original_dispose = database.dispose

    def track_dispose():
        disposed_after_commit.append(committed.is_set())
        original_dispose()
        disposed.set()

    def block_final_update(connection, cursor, statement, parameters, context, executemany):
        if (
            current_thread().name.startswith("trace-custom-lessons")
            and statement.startswith("UPDATE custom_lesson_requests")
            and "completed_at" in statement
        ):
            entered.set()
            assert release.wait(5)

    def record_actual_commit(session):
        if current_thread().name.startswith("trace-custom-lessons") and entered.is_set():
            committed.set()

    event.listen(database.engine, "before_cursor_execute", block_final_update)
    event.listen(Session, "after_commit", record_actual_commit)
    monkeypatch.setattr("app.main._SHUTDOWN_GRACE_SECONDS", 0)
    app = create_app(
        settings,
        ai_settings=AIClientSettings(_env_file=None, mode="mock"),
        ai_transport_factory=lambda: transport,
    )
    runtime = None
    try:
        with (
            patch("app.main.Database", return_value=database),
            patch.object(database, "dispose", side_effect=track_dispose),
        ):
            try:
                with TestClient(app):
                    runtime = app.state.custom_lessons
                    runtime.runner.generator = FailedGenerator()
                    request = runtime.runner.repository.create_request(
                        owner,
                        str(uuid4()),
                        "bounded-fixture",
                        RequestFields(
                            "Python loops",
                            "Python",
                            None,
                            "beginner",
                            "understand",
                            1,
                            ("multiple_choice",),
                        ),
                        now,
                        per_minute=1,
                        per_day=5,
                    )
                    assert request.kind == "created"
                    runtime.runner.submit(request.view.id)
                    assert entered.wait(2)
                assert runtime.client.closed
                assert not runtime.wait_for_idle(0)
                assert not disposed.is_set() and transport.closed_count == 0
                assert app.state.custom_lessons is None
            finally:
                release.set()
            assert disposed.wait(3)
        assert committed.is_set() and disposed_after_commit == [True]
        assert runtime.wait_for_idle(0) and transport.closed_count == 1
        assert runtime.runner.repository.status(request.view.id) == "failed"
    finally:
        release.set()
        if runtime is not None:
            assert runtime.wait_for_idle(3)
        event.remove(database.engine, "before_cursor_execute", block_final_update)
        event.remove(Session, "after_commit", record_actual_commit)


def test_repeated_lifespans_create_and_close_distinct_custom_runtimes(settings, database):
    app = create_app(settings, database)
    with TestClient(app):
        first = app.state.custom_lessons
    assert first.client.closed and first.wait_for_idle(0)
    with TestClient(app):
        second = app.state.custom_lessons
        assert second is not first and not second.client.closed
    assert second.client.closed and second.wait_for_idle(0)


def test_nested_lifespan_cleanup_owns_captured_custom_runtime_not_current_state(settings, database):
    app = create_app(settings, database)
    with TestClient(app):
        outer = app.state.custom_lessons
        with TestClient(app):
            inner = app.state.custom_lessons
            assert inner is not outer
        assert inner.client.closed and not outer.client.closed
    assert outer.client.closed and inner.client.closed
    assert outer.wait_for_idle(0) and inner.wait_for_idle(0)


@pytest.mark.parametrize("status", ["queued", "generating"])
def test_other_application_startup_preserves_fresh_custom_jobs(settings, database, status):
    from app.db.custom_lessons import SqlCustomLessonRepository

    now, owner = datetime.now(UTC), uuid4()
    with database.session() as session, session.begin():
        session.add(User(id=owner, status="active", created_at=now, updated_at=now))
    first = create_app(settings, database, clock=lambda: now)
    second = create_app(settings, database, clock=lambda: now)
    with TestClient(first):
        repository = SqlCustomLessonRepository(database)
        request = repository.create_request(
            owner,
            str(uuid4()),
            "fresh-request",
            RequestFields(
                "Python loops", "Python", None, "beginner", "understand", 1, ("multiple_choice",)
            ),
            now,
            per_minute=1,
            per_day=5,
        )
        assert request.kind == "created"
        if status == "generating":
            assert repository.start_generation(request.view.id, now) is not None
        with TestClient(second):
            assert repository.status(request.view.id) == status
        assert repository.status(request.view.id) == status
