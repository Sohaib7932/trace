"""Upgrade/downgrade the additive archive against disposable populated SQLite only."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, inspect, text

from alembic import command
from app.db import models as m
from app.db.knowledge_models import KnowledgeRevisionRow
from app.db.learning import SqlLearningRepository
from app.db.migrations import migration_config
from app.db.session import Database
from app.domain.learning import Attempt, LearningSession, Prediction
from app.services.catalog import seed_first_lesson, seed_transfer_lesson
from tests.conftest import migrate
from tests.integration.test_knowledge_archive import archive_context
from tests.lifecycle_fixtures import NOW

TABLES = {
    "knowledge_sources",
    "knowledge_revisions",
    "knowledge_events",
    "knowledge_manifests",
    "knowledge_publications",
    "knowledge_indexes",
    "knowledge_receipts",
}


def rows(connection, table):
    return [dict(row) for row in connection.execute(text(f'SELECT * FROM "{table}"')).mappings()]


def test_additive_archive_upgrade_empty_downgrade_and_metadata_preserve_legacy(settings):
    database = Database(settings)
    try:
        migrate(database, "0007_tutor_reservations")
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
                    uuid4(), session.id, 1, "content", "Compare the contract.", 0, str(uuid4()), NOW
                )
            )
        with database.engine.begin() as connection:
            names = set(inspect(connection).get_table_names()) - {"alembic_version"}
            before = {name: rows(connection, name) for name in names}
            old_schema = connection.execute(
                text(
                    "SELECT type,name,sql FROM sqlite_master "
                    "WHERE type IN ('table','trigger','index') AND name NOT LIKE 'sqlite_%'"
                )
            ).all()
            config = migration_config()
            config.attributes["connection"] = connection
            command.upgrade(config, "0008_knowledge_archive")
            assert set(inspect(connection).get_table_names()) == names | TABLES | {
                "alembic_version"
            }
            assert {name: rows(connection, name) for name in names} == before
            new_schema = {
                row.name: row.sql
                for row in connection.execute(
                    text(
                        "SELECT name,sql FROM sqlite_master "
                        "WHERE type IN ('table','trigger','index')"
                    )
                )
            }
            assert all(new_schema[name] == sql for _, name, sql in old_schema)
            target = MetaData(naming_convention=m.Base.metadata.naming_convention)
            for name in names | TABLES:
                m.Base.metadata.tables[name].to_metadata(target)
            assert compare_metadata(MigrationContext.configure(connection), target) == []
            assert connection.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
            command.downgrade(config, "0007_tutor_reservations")
            assert {name: rows(connection, name) for name in names} == before
            command.upgrade(config, "0008_knowledge_archive")
    finally:
        database.dispose()


def test_archive_history_refuses_downgrade_without_deleting_records(settings):
    database = Database(settings)
    try:
        migrate(database, "0008_knowledge_archive")
        context = archive_context(database)
        history = context.service.ingest(
            context.package.documents[0], revision="2.0.0", key=str(uuid4()), actor=context.admin
        )
        with database.engine.begin() as connection:
            before = {name: rows(connection, name) for name in TABLES}
            config = migration_config()
            config.attributes["connection"] = connection
            with pytest.raises(RuntimeError, match="downgrade refused"):
                command.downgrade(config, "0007_tutor_reservations")
            assert {name: rows(connection, name) for name in TABLES} == before
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "0008_knowledge_archive"
            )
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        with database.session() as session:
            assert session.get(KnowledgeRevisionRow, UUID(history.revision.id)) is not None
    finally:
        database.dispose()
