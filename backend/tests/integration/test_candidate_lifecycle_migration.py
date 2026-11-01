"""Additive provenance migration on disposable populated databases only."""

from datetime import timedelta
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, inspect, select, text

from alembic import command
from app.db import models as m
from app.db.candidates import SqlCandidateRepository
from app.db.learning import SqlLearningRepository
from app.db.migrations import migration_config
from app.db.session import Database
from app.domain.learning import Attempt, LearningSession, Prediction
from app.services.candidate_lifecycle import CandidateLifecycleService
from app.services.candidate_validation import CandidateValidationService
from app.services.catalog import seed_first_lesson, seed_transfer_lesson
from tests.conftest import migrate
from tests.lifecycle_fixtures import NOW, inputs

TABLES = {"generated_candidates", "candidate_lifecycle_events"}


@pytest.fixture
def candidate_database(settings):
    database = Database(settings)
    try:
        migrate(database, "0006_candidate_lifecycle")
        yield database
    finally:
        database.dispose()


def table_rows(connection, table):
    return [dict(row) for row in connection.execute(text(f'SELECT * FROM "{table}"')).mappings()]


def test_candidate_upgrade_and_empty_downgrade_preserve_all_legacy_rows_and_schema(settings):
    database = Database(settings)
    try:
        migrate(database, "0005_account_identity")
        repository = SqlLearningRepository(database)
        lesson = seed_first_lesson(repository)
        seed_transfer_lesson(repository)
        with repository.write() as store:
            credential = store.create_identity("0" * 64, NOW + timedelta(days=30))
            session = LearningSession(
                uuid4(),
                credential.learner_id,
                lesson.id,
                "awaiting_prediction",
                str(uuid4()),
                NOW,
                None,
            )
            store.add_session(session)
            store.add_prediction(
                Prediction(
                    uuid4(),
                    session.id,
                    "rejected",
                    "Inspect the receiving fields.",
                    str(uuid4()),
                    NOW,
                )
            )
            store.set_state(session.id, "ready_for_attempt")
            store.add_attempt(
                Attempt(
                    uuid4(),
                    session.id,
                    1,
                    "content",
                    "Compare the contract.",
                    0,
                    str(uuid4()),
                    NOW,
                )
            )
        with database.engine.begin() as connection:
            names = set(inspect(connection).get_table_names()) - {"alembic_version"}
            before = {name: table_rows(connection, name) for name in names}
            old_schema = connection.execute(
                text(
                    "SELECT type,name,sql FROM sqlite_master "
                    "WHERE type IN ('table','trigger','index') "
                    "AND name NOT LIKE 'sqlite_%'"
                )
            ).all()
            config = migration_config()
            config.attributes["connection"] = connection
            command.upgrade(config, "0006_candidate_lifecycle")
            assert set(inspect(connection).get_table_names()) == names | TABLES | {
                "alembic_version"
            }
            assert {name: table_rows(connection, name) for name in names} == before
            upgraded = {
                row.name: row.sql
                for row in connection.execute(
                    text(
                        "SELECT name,sql FROM sqlite_master "
                        "WHERE type IN ('table','trigger','index')"
                    )
                )
            }
            assert all(upgraded[name] == sql for _, name, sql in old_schema)
            assert connection.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
            target = MetaData(naming_convention=m.Base.metadata.naming_convention)
            for name in names | TABLES:
                m.Base.metadata.tables[name].to_metadata(target)
            assert compare_metadata(MigrationContext.configure(connection), target) == []
            command.downgrade(config, "0005_account_identity")
            assert {name: table_rows(connection, name) for name in names} == before
            assert set(inspect(connection).get_table_names()) == names | {"alembic_version"}
            command.upgrade(config, "0006_candidate_lifecycle")
    finally:
        database.dispose()


def test_candidate_history_blocks_downgrade_without_deleting_anything(candidate_database):
    database = candidate_database
    service = CandidateLifecycleService(
        SqlCandidateRepository(database), CandidateValidationService(), lambda: NOW
    )
    history = service.create(**inputs())
    service.validate(history.snapshot.id, key=str(uuid4()), expected_revision=0)
    with database.engine.begin() as connection:
        before = {name: table_rows(connection, name) for name in TABLES}
        config = migration_config()
        config.attributes["connection"] = connection
        with pytest.raises(RuntimeError, match="downgrade refused"):
            command.downgrade(config, "0005_account_identity")
        assert {name: table_rows(connection, name) for name in TABLES} == before
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == "0006_candidate_lifecycle"
        )


def test_database_rejects_invalid_initial_transition_and_release_claims(database):
    service = CandidateLifecycleService(
        SqlCandidateRepository(database), CandidateValidationService(), lambda: NOW
    )
    history = service.create(**inputs())
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError), database.session() as session, session.begin():
        session.add(
            m.CandidateLifecycleEvent(
                id=uuid4(),
                candidate_id=__import__("uuid").UUID(history.snapshot.id),
                revision=1,
                operation_key=uuid4(),
                action="production_approval",
                previous_state="composed",
                state="production_approved",
                actor_id=None,
                created_at=NOW,
                payload={},
                release_eligible=False,
            )
        )
    with pytest.raises(IntegrityError), database.session() as session, session.begin():
        session.add(
            m.GeneratedCandidate(
                id=uuid4(),
                generation_request_id=uuid4(),
                creation_key=uuid4(),
                created_at=NOW,
                snapshot={},
                composition_sha256="0" * 64,
                release_eligible=True,
            )
        )
    with database.session() as session:
        assert len(session.scalars(select(m.CandidateLifecycleEvent)).all()) == 1
