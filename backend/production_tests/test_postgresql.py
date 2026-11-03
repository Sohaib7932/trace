"""Actual PostgreSQL equivalence; invoked explicitly by the PostgreSQL CI job."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event

import pytest
from sqlalchemy import inspect, select, text, update
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.db import models as m
from app.db.learning import SqlLearningRepository
from app.db.migrations import expected_heads, migration_config
from app.db.session import Database
from app.services.catalog import seed_first_lesson
from tests.integration.test_learning import (
    post,
    predict,
    start,
)
from tests.integration.test_learning import (
    test_complete_real_journey_preserves_prediction_attempts_and_fresh_evidence as real_journey,
)
from tests.integration.test_tutor_operation_migration import (
    test_reservation_constraints_and_triggers_enforce_identity_and_result as reservation_guards,
)


def test_baseline_and_schema_drift(database):
    config = migration_config("postgresql")
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.check(config)
        assert {
            connection.scalar(text("SELECT version_num FROM alembic_version"))
        } == expected_heads()
        guards = connection.scalar(
            text(
                "SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal "
                "AND tgrelid IN (SELECT c.oid FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=current_schema())"
            )
        )
        assert guards >= 54
        index = connection.scalar(
            text(
                "SELECT indexdef FROM pg_indexes WHERE schemaname=current_schema() "
                "AND indexname='uq_hint_operations_pending_session'"
            )
        )
        assert "WHERE" in index and "pending" in index


def test_legacy_notes_journey_and_five_checks(learner, database):
    real_journey(learner, database)


def test_existing_reservation_guard_contract(database):
    reservation_guards(database)


def test_three_finalized_hints_are_permitted_but_fourth_is_rejected(learner):
    session = start(learner)
    assert predict(learner, session).status_code == 201
    for level in (1, 2, 3):
        result = post(learner, f"/sessions/{session}/hints", {})
        assert result.status_code == 201, result.text
        assert result.json()["sequence"] == level
    assert post(learner, f"/sessions/{session}/hints", {}).status_code == 409


def test_append_only_and_foreign_key_constraints(database):
    version = seed_first_lesson(SqlLearningRepository(database))
    with pytest.raises(IntegrityError), database.session() as session, session.begin():
        session.execute(
            update(m.LessonVersion).where(m.LessonVersion.id == version.id).values(version="2.0.0")
        )
    with pytest.raises(IntegrityError), database.session() as session, session.begin():
        session.execute(
            text("INSERT INTO user_roles(user_id,role) VALUES(:id,'learner')"),
            {"id": "00000000-0000-0000-0000-000000000001"},
        )


def test_baseline_floor_refuses_downgrade_without_removing_rows(database):
    config = migration_config("postgresql")
    with (
        pytest.raises(RuntimeError, match="preservation floor"),
        database.engine.begin() as connection,
    ):
        config.attributes["connection"] = connection
        command.downgrade(config, "base")
    assert "learners" in inspect(database.engine).get_table_names()


def test_nonempty_schema_refuses_baseline(settings):
    database = Database(settings)
    try:
        with database.engine.begin() as connection:
            connection.execute(text("CREATE TABLE user_work(id integer primary key)"))
            connection.execute(text("INSERT INTO user_work VALUES(1)"))
        config = migration_config("postgresql")
        with (
            pytest.raises(RuntimeError, match="empty application schema"),
            database.engine.begin() as connection,
        ):
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with database.engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM user_work")) == 1
        assert "learners" not in inspect(database.engine).get_table_names()
    finally:
        database.dispose()


def test_wrong_migration_lineage_refuses_before_changes(settings):
    database = Database(settings)
    try:
        config = migration_config("sqlite")
        with (
            pytest.raises(RuntimeError, match="explicit Alembic"),
            database.engine.begin() as connection,
        ):
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        assert not inspect(database.engine).get_table_names()
    finally:
        database.dispose()


def test_short_read_snapshot_is_consistent_and_writes_remain_read_committed(database):
    with database.session() as session, session.begin():
        row = m.Learner(created_at=datetime.now(UTC))
        session.add(row)
        session.flush()
        identity = row.id
    with database.consistent_read() as first:
        before = first.scalar(select(m.Learner.created_at).where(m.Learner.id == identity))
        with database.session() as other, other.begin():
            assert other.scalar(text("SHOW transaction_isolation")) == "read committed"
            other.execute(
                update(m.Learner)
                .where(m.Learner.id == identity)
                .values(created_at=datetime(2027, 1, 1, tzinfo=UTC))
            )
        assert first.scalar(select(m.Learner.created_at).where(m.Learner.id == identity)) == before
        assert first.scalar(text("SHOW transaction_read_only")) == "on"
    with database.consistent_read() as fresh:
        assert fresh.scalar(select(m.Learner.created_at).where(m.Learner.id == identity)) != before


def test_write_gate_serializes_separate_repositories(database):
    entered, release, second = Event(), Event(), Event()
    first = SqlLearningRepository(database)
    other = SqlLearningRepository(database)

    def hold():
        with first.write():
            entered.set()
            assert release.wait(5)

    def acquire():
        with other.write():
            second.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        initial = pool.submit(hold)
        assert entered.wait(5)
        waiting = pool.submit(acquire)
        try:
            assert not second.wait(0.1)
        finally:
            release.set()
        initial.result(timeout=5)
        waiting.result(timeout=5)
    assert second.is_set()
