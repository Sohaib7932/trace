"""Actual owner-scoped persistence and bounded fake generation; no external provider calls."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event, local
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import event, func, select, update

from alembic import command
from app.db import models as m
from app.db.accounts import SqlAccountRepository
from app.db.guide_models import PrivateLearningGuide
from app.db.migrations import migration_config
from app.db.private_guides import SqlPrivateGuideRepository
from app.domain.accounts import AuthenticatedAccount, VerifiedIdentity
from app.domain.learning import LearningError
from app.schemas.private_guides import GuideContent, GuideCreate
from app.services.accounts import AccountService
from app.services.private_guides import PrivateGuideService
from tests.auth_fixtures import AuthClock


def content():
    return {
        "schema_version": "private-learning-guide-v1",
        "title": "Python variables",
        "description": "Explore names and values using small unexecuted examples.",
        "learning_objectives": ["Describe a name binding", "Reassign a value"],
        "sections": [
            {
                "id": "binding",
                "title": "Name binding",
                "explanation": "A name refers to a value.",
                "example": {
                    "language": "python",
                    "code": "count = 2\nprint(count)",
                    "explanation": "This unexecuted example binds a number.",
                },
                "practice": "Write a name bound to a different number.",
                "expected_outcome": "Describe what the name refers to.",
            },
            {
                "id": "reassignment",
                "title": "Reassignment",
                "explanation": "Bind a new value.",
                "example": None,
                "practice": "Explain a second assignment in your own words.",
                "expected_outcome": "Distinguish the name from its current value.",
            },
        ],
        "summary": "Try the examples yourself; this guide does not grade your work.",
    }


class FakeGenerator:
    def __init__(self):
        self.calls = []
        self.callback = None
        self.error = None

    def generate(self, request, *, subject, timeout_seconds):
        self.calls.append((request, subject, timeout_seconds))
        if self.callback:
            self.callback()
        if self.error:
            raise self.error
        return GuideContent.model_validate(content()), "test_fixture"


@pytest.fixture
def guides(database):
    clock = AuthClock()
    identity = VerifiedIdentity(
        "https://auth.example.test", str(uuid4()), clock() + timedelta(hours=1)
    )
    account = AccountService(SqlAccountRepository(database), clock).bootstrap(identity)
    auth = AuthenticatedAccount(account, identity)
    provider = FakeGenerator()
    service = PrivateGuideService(SqlPrivateGuideRepository(database), provider, clock)
    request = GuideCreate(
        topic="Python variables",
        start_level="beginner",
        target_level="intermediate",
        practical=True,
    )
    return SimpleNamespace(
        service=service,
        auth=auth,
        clock=clock,
        provider=provider,
        request=request,
        database=database,
    )


def test_private_guide_persists_strict_content_digest_version_and_owner_readback(guides):
    saved = guides.service.create(guides.auth, uuid4(), guides.request)
    assert saved.status == "ready" and saved.source == "test_fixture"
    assert saved.ungraded and saved.execution_status == "not_executed"
    assert saved.version == "1.0.0" and len(saved.content_sha256) == 64
    assert saved.content.schema_version == "private-learning-guide-v1"
    assert guides.service.get(guides.auth, saved.id) == saved
    listed = guides.service.list(guides.auth)
    assert len(listed) == 1 and listed[0].id == saved.id
    assert "content" not in listed[0].model_dump()
    assert str(guides.auth.account.id) not in guides.provider.calls[0][1]
    assert guides.provider.calls[0][0] == guides.request
    with guides.database.session() as session:
        assert session.scalars(select(m.LearningSession)).all() == []


def test_duplicate_same_key_replays_without_generation_and_conflicting_body_is_rejected(guides):
    key = uuid4()
    saved = guides.service.create(guides.auth, key, guides.request)
    assert guides.service.create(guides.auth, key, guides.request) == saved
    assert len(guides.provider.calls) == 1
    with pytest.raises(LearningError, match="Idempotency") as caught:
        guides.service.create(
            guides.auth, key, guides.request.model_copy(update={"topic": "Loops"})
        )
    assert caught.value.code == "conflict"


def test_other_accounts_cannot_list_or_read_a_private_guide(guides):
    saved = guides.service.create(guides.auth, uuid4(), guides.request)
    identity = VerifiedIdentity(
        guides.auth.identity.issuer, str(uuid4()), guides.auth.identity.expires_at
    )
    account = AccountService(SqlAccountRepository(guides.database)).bootstrap(identity)
    foreign = AuthenticatedAccount(account, identity)
    assert guides.service.list(foreign) == ()
    for identity in (saved.id, uuid4()):
        with pytest.raises(LearningError) as caught:
            guides.service.get(foreign, identity)
        assert caught.value.code == "not_found"


@pytest.mark.parametrize(
    "error", [TimeoutError("private-message"), RuntimeError("private-message")]
)
def test_provider_failure_is_persisted_honestly_and_not_replayed(guides, error):
    guides.provider.error = error
    key = uuid4()
    saved = guides.service.create(guides.auth, key, guides.request)
    assert saved.status == "unavailable"
    assert saved.content is saved.source is saved.content_sha256 is None
    assert "private-message" not in saved.model_dump_json()
    assert guides.service.create(guides.auth, key, guides.request) == saved
    assert len(guides.provider.calls) == 1


def test_slow_generation_releases_database_transaction_and_concurrent_duplicate_does_not_generate(
    guides,
):
    started, release = Event(), Event()

    def pause():
        started.set()
        assert release.wait(10)

    guides.provider.callback = pause
    key = uuid4()
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(guides.service.create, guides.auth, key, guides.request)
        try:
            assert started.wait(5)
            replay = pool.submit(guides.service.create, guides.auth, key, guides.request).result(5)
            assert replay.status == "generating"
            with guides.database.session() as session, session.begin():
                session.execute(
                    update(m.User)
                    .where(m.User.id == guides.auth.account.id)
                    .values(updated_at=guides.clock())
                )
        finally:
            release.set()
        saved = pending.result(5)
    assert saved.id == replay.id and saved.status == "ready"
    assert len(guides.provider.calls) == 1


def test_expired_worker_cannot_finalize_and_crashed_reservation_recovers_unavailable(guides):
    reserved, _ = guides.service.repository.reserve(
        guides.auth.account.id, uuid4(), guides.request, guides.clock()
    )
    guides.clock.advance(61)
    expired = guides.service.get(guides.auth, reserved.id)
    assert expired.status == "unavailable"
    late = guides.service.repository.finish(
        guides.auth.account.id,
        reserved.id,
        GuideContent.model_validate(content()),
        "test_fixture",
        guides.clock(),
    )
    assert late == expired


@pytest.mark.parametrize("revocation", ["expired", "disabled", "role_removed"])
def test_fresh_authorization_withholds_content_when_revoked_during_generation(guides, revocation):
    def revoke():
        if revocation == "expired":
            guides.clock.advance(3601)
        else:
            with guides.database.session() as session, session.begin():
                if revocation == "disabled":
                    session.execute(
                        update(m.User)
                        .where(m.User.id == guides.auth.account.id)
                        .values(status="disabled")
                    )
                else:
                    from sqlalchemy import delete

                    session.execute(
                        delete(m.UserRole).where(m.UserRole.user_id == guides.auth.account.id)
                    )

    guides.provider.callback = revoke
    with pytest.raises(LearningError) as caught:
        guides.service.create(guides.auth, uuid4(), guides.request)
    assert caught.value.code in {"unauthenticated", "forbidden"}
    with guides.database.session() as session:
        row = session.scalar(select(PrivateLearningGuide))
        assert row.content is None and row.source is None


def test_content_tampering_fails_digest_integrity(guides):
    saved = guides.service.create(guides.auth, uuid4(), guides.request)
    changed = content()
    changed["title"] = "Forged title"
    with guides.database.session() as session, session.begin():
        session.execute(
            update(PrivateLearningGuide)
            .where(PrivateLearningGuide.id == saved.id)
            .values(content=changed)
        )
    with pytest.raises(ValidationError):
        guides.service.get(guides.auth, saved.id)


def test_additive_migration_downgrade_upgrade_preserves_users_and_learner_history(guides):
    from app.ai.providers.fake import FakeTutorProvider
    from app.db.learning import SqlLearningRepository
    from app.services.catalog import LESSON_ID, seed_first_lesson
    from app.services.learning import LearningService

    repository = SqlLearningRepository(guides.database)
    seed_first_lesson(repository)
    owner = AccountService(SqlAccountRepository(guides.database), guides.clock).learner(
        guides.auth.account
    )
    learning = LearningService(repository, FakeTutorProvider(), guides.clock)
    historical = learning.create_session(owner, LESSON_ID, "1.0.0", str(uuid4()))
    prediction = learning.predict(
        owner, historical.id, "rejected", "Inspect field names.", str(uuid4())
    )
    before = learning.progress(owner, historical.id)
    configuration = migration_config()
    with guides.database.engine.begin() as connection:
        configuration.attributes["connection"] = connection
        command.downgrade(configuration, "0009_durable_ai_controls")
        command.upgrade(configuration, "0010_private_learning_guides")
    saved = guides.service.create(guides.auth, uuid4(), guides.request)
    assert saved.status == "ready"
    after = learning.progress(owner, historical.id)
    assert after == before and after.prediction == prediction


def test_populated_guide_downgrade_refuses_to_delete_private_user_work(guides):
    from alembic.runtime.migration import MigrationContext

    saved = guides.service.create(guides.auth, uuid4(), guides.request)
    configuration = migration_config()
    with guides.database.engine.connect() as connection:
        before = MigrationContext.configure(connection).get_current_heads()
    with (
        pytest.raises(RuntimeError, match="Private guide history exists"),
        guides.database.engine.begin() as connection,
    ):
        configuration.attributes["connection"] = connection
        command.downgrade(configuration, "0009_durable_ai_controls")
    assert guides.service.get(guides.auth, saved.id) == saved
    with guides.database.engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_heads() == before


@pytest.mark.parametrize("existing", [False, True], ids=["new-key", "duplicate-key"])
def test_guide_reservation_waits_before_reading_while_list_writes(guides, existing):
    """A list writer must not create a SQLite read-to-write upgrade deadlock."""
    assert guides.database.engine.dialect.name == "sqlite"
    owner, now, key = guides.auth.account.id, guides.clock(), uuid4()
    saved = guides.service.create(guides.auth, key, guides.request) if existing else None
    repository = guides.service.repository
    writer_updated, release_writer, reservation_attempted = Event(), Event(), Event()
    reservation_read = Event()
    role = local()
    statements = []

    def before_sql(connection, cursor, statement, parameters, context, executemany):
        if getattr(role, "name", None) != "reserve":
            return
        normalized = " ".join(statement.lower().split())
        statements.append(normalized)
        reservation_attempted.set()
        if normalized.startswith("select") and "private_learning_guides" in normalized:
            reservation_read.set()

    def after_sql(connection, cursor, statement, parameters, context, executemany):
        if getattr(role, "name", None) == "list" and statement.lower().lstrip().startswith(
            "update private_learning_guides"
        ):
            writer_updated.set()
            assert release_writer.wait(5), "The test must release the actual list writer."

    def list_while_held():
        role.name = "list"
        return repository.list(owner, now)

    def reserve():
        role.name = "reserve"
        return repository.reserve(owner, key, guides.request, now)

    event.listen(guides.database.engine, "before_cursor_execute", before_sql)
    event.listen(guides.database.engine, "after_cursor_execute", after_sql)
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            listing = workers.submit(list_while_held)
            try:
                assert writer_updated.wait(5), "The list must hold a real reserved write lock."
                reservation = workers.submit(reserve)
                assert reservation_attempted.wait(5)
                assert statements[0].startswith("update write_gate "), (
                    "Reservation must acquire the shared write gate before its first read."
                )
                assert not reservation_read.is_set()
                assert not reservation.done()
            finally:
                release_writer.set()
            listed = listing.result(timeout=5)
            result, created = reservation.result(timeout=5)
    finally:
        release_writer.set()
        event.remove(guides.database.engine, "before_cursor_execute", before_sql)
        event.remove(guides.database.engine, "after_cursor_execute", after_sql)

    assert created is not existing
    assert result.status == ("ready" if existing else "generating")
    assert tuple(item.id for item in listed) == ((saved.id,) if saved else ())
    assert len(guides.provider.calls) == (1 if existing else 0)
    replay, created_again = repository.reserve(owner, key, guides.request, now)
    assert replay == result and created_again is False
    with guides.database.session() as session:
        assert session.scalar(select(func.count()).select_from(PrivateLearningGuide)) == 1
