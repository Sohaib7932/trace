"""Actual disposable PostgreSQL function hardening, never a hosted DB or web exploit.

The shadow fixture deliberately has direct SQL write and TEMP privileges. It does
not represent the unauthenticated HTTP caller or change database role grants.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.db import knowledge_models as k
from app.db import models as m
from app.db.migrations import migration_config
from tests.integration.test_knowledge_archive import (
    archive_context,
    publish_corpus,
    versioned_answer,
)
from tests.integration.test_merged_learning_migrations import seed_legacy, snapshot

OLD = "0015_project_learning_paths"
NEW = "0016_guard_search_paths"
FUNCTIONS = {
    "knowledge_immutable_guard",
    "knowledge_admin_guard",
    "knowledge_event_guard",
    "knowledge_publication_guard",
    "github_snapshot_immutable",
    "github_knowledge_immutable",
    "github_learning_path_immutable",
}


def migrate(database, *, downgrade=False):
    with database.engine.begin() as connection:
        config = migration_config("postgresql")
        config.attributes["connection"] = connection
        (command.downgrade if downgrade else command.upgrade)(config, OLD if downgrade else NEW)


def functions(database, schema):
    with database.engine.connect() as connection:
        rows = (
            connection.execute(
                text(
                    "SELECT p.proname,p.prosrc,p.proowner,p.prosecdef,p.proacl,p.proconfig,"
                    "p.prolang,p.prorettype,p.proargtypes::text AS argument_types "
                    "FROM pg_catalog.pg_proc p "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
                    "WHERE n.nspname=:schema AND p.proname::text=ANY(:names) AND p.pronargs=0 "
                    "ORDER BY p.proname"
                ),
                {"schema": schema, "names": sorted(FUNCTIONS)},
            )
            .mappings()
            .all()
        )
    return {row["proname"]: dict(row) for row in rows}


def test_upgrade_downgrade_reupgrade_preserves_bodies_permissions_and_all_rows(database, settings):
    migrate(database, downgrade=True)
    seed_legacy(database)
    before, rows = functions(database, settings.database_schema), snapshot(database)
    assert set(before) == FUNCTIONS
    assert all(not item["prosecdef"] and item["proconfig"] is None for item in before.values())
    for downgrade in (False, True, False):
        migrate(database, downgrade=downgrade)
        after = functions(database, settings.database_schema)
        assert snapshot(database) == rows
        for name, previous in before.items():
            actual = after[name]
            assert {key: value for key, value in actual.items() if key != "proconfig"} == {
                key: value for key, value in previous.items() if key != "proconfig"
            }
            if downgrade:
                assert actual["proconfig"] is None
            else:
                assert len(actual["proconfig"]) == 1
                key, path = actual["proconfig"][0].split("=", 1)
                assert key == "search_path"
                assert tuple(part.strip().strip('"') for part in path.split(",")) == (
                    "pg_catalog",
                    settings.database_schema,
                    "pg_temp",
                )


@pytest.mark.parametrize("explicit_temp_first", [False, True])
def test_temporary_authority_tables_cannot_authorize_non_admin(
    database, settings, explicit_temp_first
):
    actor, at = uuid4(), datetime.now(UTC)
    with database.session() as session, session.begin():
        session.add(m.User(id=actor, status="active", created_at=at, updated_at=at))
        session.flush()
        session.add(m.UserRole(user_id=actor, role="learner"))
    schema = database.engine.dialect.identifier_preparer.quote_identifier(settings.database_schema)
    with database.engine.begin() as connection:
        connection.exec_driver_sql("CREATE TEMP TABLE users(id uuid,status text) ON COMMIT DROP")
        connection.exec_driver_sql(
            "CREATE TEMP TABLE user_roles(user_id uuid,role text) ON COMMIT DROP"
        )
        connection.execute(text("INSERT INTO users VALUES (:actor,'active')"), {"actor": actor})
        connection.execute(text("INSERT INTO user_roles VALUES (:actor,'admin')"), {"actor": actor})
        if explicit_temp_first:
            connection.exec_driver_sql(f"SET LOCAL search_path TO pg_temp,{schema},pg_catalog")
        assert connection.scalar(text("SELECT count(*) FROM user_roles WHERE role='admin'")) == 1
        with pytest.raises(IntegrityError) as denied, connection.begin_nested():
            connection.execute(
                text(
                    f"INSERT INTO {schema}.knowledge_sources(source_id,actor_id,created_at) "
                    "VALUES ('temporary-shadow-denied',:actor,:at)"
                ),
                {"actor": actor, "at": at},
            )
        assert denied.value.orig.sqlstate == "23514"
        assert "knowledge administration requires active admin" in str(denied.value.orig)
        assert (
            connection.scalar(
                text(
                    f"SELECT count(*) FROM {schema}.knowledge_sources "
                    "WHERE source_id='temporary-shadow-denied'"
                )
            )
            == 0
        )


def test_hardened_functions_preserve_real_governance_release_and_immutability(database, settings):
    context = archive_context(database)
    histories, publication = publish_corpus(context)
    receipt = context.service.authorize_release(
        versioned_answer(context.knowledge.snapshot()),
        actor=context.learner,
        request_id="hardened-disposable-postgres",
    )
    assert context.service.get_receipt(receipt.id, actor=context.admin) == receipt
    assert context.knowledge.snapshot().manifest_sha256 == publication.manifest_sha256
    assert all(
        context.service.get(history.revision.id, actor=context.admin).state == "published"
        for history in histories
    )
    assert set(functions(database, settings.database_schema)) == FUNCTIONS
    with pytest.raises(IntegrityError), database.session() as session, session.begin():
        session.execute(delete(k.KnowledgeRevisionRow))
    assert context.knowledge.available
