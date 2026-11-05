"""Custom-lesson writes share the database gate with account and learning writes."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import event, update

from app.db.custom_lessons import SqlCustomLessonRepository
from app.db.models import User, WriteGate
from app.repositories.custom_lessons import RequestFields


@pytest.fixture
def requests(database):
    now, owner = datetime.now(UTC), uuid4()
    with database.session() as session, session.begin():
        session.add(User(id=owner, status="active", created_at=now, updated_at=now))
    repository = SqlCustomLessonRepository(database)
    fields = RequestFields("Python loops", "Python", None, "beginner", "understand", 1, ())

    def create(key):
        return repository.create_request(
            owner, key, "same-body", fields, now, per_minute=1, per_day=10
        )

    return create


def test_creation_waits_for_writer(database, requests):
    attempted_write = Event()

    def observe_write(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith(("INSERT INTO custom_lesson_requests", "UPDATE write_gate")):
            attempted_write.set()

    with ThreadPoolExecutor(max_workers=1) as workers:
        with database.session() as writer, writer.begin():
            writer.execute(update(WriteGate).where(WriteGate.id == 1).values(id=1))
            event.listen(database.engine, "before_cursor_execute", observe_write)
            try:
                pending = workers.submit(requests, str(uuid4()))
                assert attempted_write.wait(5)
                # The competing writer must wait, rather than fail its lock upgrade.
                with pytest.raises(TimeoutError):
                    pending.result(timeout=0.1)
            finally:
                event.remove(database.engine, "before_cursor_execute", observe_write)
        assert pending.result(timeout=5).kind == "created"


@pytest.mark.parametrize("same_key", [False, True])
def test_creation_preserves_quota_and_idempotency(requests, same_key):
    start = Barrier(2)
    key = str(uuid4())

    def create(candidate):
        start.wait(timeout=5)
        return requests(candidate)

    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(create, key)
        second = workers.submit(create, key if same_key else str(uuid4()))
        outcomes = [first.result(timeout=5), second.result(timeout=5)]
    assert sorted(outcome.kind for outcome in outcomes) == [
        "created",
        "replayed" if same_key else "rate_limited",
    ]
    if same_key:
        assert outcomes[0].view.id == outcomes[1].view.id
