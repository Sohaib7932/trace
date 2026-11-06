"""Startup and status reads share the established staleness boundary, never process guesses."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.custom_lesson_settings import CustomLessonSettings
from app.db.custom_lessons import SqlCustomLessonRepository
from app.db.models import User
from app.repositories.custom_lessons import RequestFields
from app.services.custom_lessons import CustomLessonService, Owner


@pytest.mark.parametrize("status", ["queued", "generating"])
@pytest.mark.parametrize("offset_microseconds,stale", [(-1, False), (0, False), (1, True)])
@pytest.mark.parametrize("stale_seconds", [60, 600])
def test_recovery_and_status_read_use_identical_configured_strict_cutoff(
    database, status, offset_microseconds, stale, stale_seconds
):
    now, owner = datetime.now(UTC), uuid4()
    updated = now - timedelta(seconds=stale_seconds, microseconds=offset_microseconds)
    with database.session() as session, session.begin():
        session.add(User(id=owner, status="active", created_at=updated, updated_at=updated))
    repository = SqlCustomLessonRepository(database)
    service = CustomLessonService(
        repository,
        CustomLessonSettings(_env_file=None, stale_after_seconds=stale_seconds),
        lambda: now,
        available=False,
    )

    def create():
        result = repository.create_request(
            owner,
            str(uuid4()),
            "stale-boundary",
            RequestFields(
                "Python loops", "Python", None, "beginner", "understand", 1, ("multiple_choice",)
            ),
            updated,
            per_minute=5,
            per_day=5,
        )
        assert result.kind == "created"
        if status == "generating":
            assert repository.start_generation(result.view.id, updated) is not None
        return result.view.id

    recovered_id = create()
    assert service.recover_interrupted() == int(stale)
    read_id = create()
    read = service.get_request(Owner(owner), read_id)
    recovered = service.get_request(Owner(owner), recovered_id)
    expected = "failed" if stale else status
    assert read.status == recovered.status == expected
    assert read.error_code == recovered.error_code == ("interrupted" if stale else None)
    assert service.recover_interrupted() == 0


@pytest.mark.parametrize("terminal", ["cancelled", "failed", "rejected", "ready"])
def test_recovery_does_not_rewrite_terminal_requests(database, terminal):
    now, owner = datetime.now(UTC), uuid4()
    old = now - timedelta(hours=2)
    with database.session() as session, session.begin():
        session.add(User(id=owner, status="active", created_at=old, updated_at=old))
    repository = SqlCustomLessonRepository(database)
    result = repository.create_request(
        owner,
        str(uuid4()),
        "terminal-request",
        RequestFields(
            "Python loops", "Python", None, "beginner", "understand", 1, ("multiple_choice",)
        ),
        old,
        per_minute=1,
        per_day=5,
    )
    repository.finish(result.view.id, terminal, None, old)
    assert repository.recover_interrupted(now, timedelta(seconds=600)) == 0
    assert repository.status(result.view.id) == terminal
