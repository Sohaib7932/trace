"""SQLite no-op compatibility and preservation of the published guard migrations."""

import hashlib
from pathlib import Path

from sqlalchemy import text

from alembic import command
from app.db.learning import SqlLearningRepository
from app.db.migrations import migration_config
from app.services.catalog import seed_first_lesson, seed_transfer_lesson
from tests.integration.test_merged_learning_migrations import snapshot

OLD = "0015_project_learning_paths"
NEW = "0016_guard_search_paths"


def migrate(database, *, downgrade=False):
    with database.engine.begin() as connection:
        config = migration_config()
        config.attributes["connection"] = connection
        (command.downgrade if downgrade else command.upgrade)(config, OLD if downgrade else NEW)


def definitions(database):
    with database.engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT type,name,sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
            )
        ).all()


def test_sqlite_upgrade_downgrade_reupgrade_preserves_all_tables_guards_and_rows(database):
    migrate(database, downgrade=True)
    repository = SqlLearningRepository(database)
    seed_first_lesson(repository)
    seed_transfer_lesson(repository)
    before_rows, before_definitions = snapshot(database), definitions(database)
    for downgrade in (False, True, False):
        migrate(database, downgrade=downgrade)
        assert snapshot(database) == before_rows
        assert definitions(database) == before_definitions
        with database.engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                OLD if downgrade else NEW
            )
            assert connection.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []


def test_published_trigger_migration_text_is_unchanged():
    # Normalize platform line endings only, preserving the published Python text.
    names = (
        "0008_knowledge_archive.py",
        "0011_github_projects.py",
        "0013_repository_knowledge.py",
        "0015_project_learning_paths.py",
    )
    hashes = (
        "274bfe629606e6b853bd2564342d9e65a452279582f71c01d8f64ad11249926e",
        "1aa835d2dd46fff2413c0731d5b03d824fffc14941654cd6f3eb670b6b7bc358",
        "1507d51ef0f09871831dc652d58cba030bc75cc9a52957f64a8d023b7a7b7a32",
        "1675d14a95e7b714b9d10cbea9d49757a42a760c1075ad929d177e7ae105f9ab",
    )
    expected = dict(zip(names, hashes, strict=True))
    directory = Path(__file__).resolve().parents[2] / "alembic" / "shared_versions"
    assert {
        name: hashlib.sha256((directory / name).read_text(encoding="utf-8").encode()).hexdigest()
        for name in expected
    } == expected
