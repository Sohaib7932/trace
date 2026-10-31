from pathlib import Path

import pytest
from alembic.runtime.migration import MigrationContext
from pydantic import SecretStr
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.core.settings import Settings
from app.db.base import Base
from app.db.health import SqlReadinessProbe
from app.db.migrations import expected_heads, migration_config
from app.db.session import Database
from tests.conftest import Child, FixtureBase, Parent, migrate


def test_connection_and_session_lifecycle(database: Database) -> None:
    with database.session() as session:
        assert session.scalar(text("SELECT 1")) == 1
        assert database.engine.pool.checkedout() == 1
    assert database.engine.pool.checkedout() == 0


def test_commit_is_observable_from_fresh_session_and_exception_rolls_back(
    database: Database,
) -> None:
    FixtureBase.metadata.create_all(database.engine)
    with database.session() as session, session.begin():
        session.add(Parent(value="committed"))
    with pytest.raises(RuntimeError), database.session() as session, session.begin():
        session.add(Parent(value="rolled back"))
        session.flush()
        raise RuntimeError("Simulate failure after insert")
    with database.session() as fresh:
        assert fresh.scalars(select(Parent.value)).all() == ["committed"]


def test_uncommitted_work_is_not_persisted(database: Database) -> None:
    FixtureBase.metadata.create_all(database.engine)
    with database.session() as session:
        session.add(Parent(value="uncommitted"))
        session.flush()
    with database.session() as fresh:
        assert fresh.scalars(select(Parent)).all() == []


def test_foreign_keys_are_enforced(database: Database) -> None:
    FixtureBase.metadata.create_all(database.engine)
    with pytest.raises(IntegrityError), database.session() as session, session.begin():
        session.add(Child(parent_id=999))
        session.flush()


def test_upgrade_downgrade_and_schema_drift_check(database: Database) -> None:
    config = migration_config()
    assert set(inspect(database.engine).get_table_names()) == set(Base.metadata.tables) | {
        "alembic_version"
    }
    assert {
        "learners",
        "learner_credentials",
        "lesson_versions",
        "learning_sessions",
        "predictions",
        "attempts",
        "tutor_interactions",
        "verification_runs",
        "verification_checks",
        "learning_events",
        "runtime_notes",
    } <= set(Base.metadata.tables)
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.check(config)
        assert (
            frozenset(MigrationContext.configure(connection).get_current_heads())
            == expected_heads()
        )
        command.downgrade(config, "base")
    assert not SqlReadinessProbe(database.engine, expected_heads()).check().ready
    migrate(database)
    assert SqlReadinessProbe(database.engine, expected_heads()).check().ready


def test_two_databases_are_isolated(database: Database, tmp_path: Path) -> None:
    other = Database(
        Settings(
            _env_file=None, database_url=SecretStr(f"sqlite+pysqlite:///{tmp_path / 'other.db'}")
        )
    )
    try:
        migrate(other)
        FixtureBase.metadata.create_all(database.engine)
        with database.session() as session, session.begin():
            session.add(Parent(value="only in first database"))
        assert set(inspect(other.engine).get_table_names()) == set(Base.metadata.tables) | {
            "alembic_version"
        }
        assert "fixture_parent" not in inspect(other.engine).get_table_names()
    finally:
        other.dispose()


def test_in_memory_database_survives_connection_change() -> None:
    db = Database(Settings(_env_file=None, database_url=SecretStr("sqlite+pysqlite:///:memory:")))
    try:
        migrate(db)
        with db.engine.connect() as first:
            assert first.scalar(text("SELECT 1")) == 1
        assert SqlReadinessProbe(db.engine, expected_heads()).check().ready
    finally:
        db.dispose()
