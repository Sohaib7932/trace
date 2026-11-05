"""Disposable upgrades of both published learning-content migration lineages."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import insert, inspect, update
from sqlalchemy.exc import DBAPIError

from alembic import command
from app.ai.providers.fake import FakeTutorProvider
from app.core.settings import Settings
from app.db import models as m
from app.db.base import Base
from app.db.custom_lesson_models import (
    CustomChallengeAnswerRow,
    CustomChallengeRow,
    CustomLessonRequestRow,
    CustomLessonRow,
)
from app.db.github_models import (
    GitHubInstallationGrant,
    GitHubProjectSnapshot,
    GitHubRepositoryConnection,
)
from app.db.guide_models import PrivateLearningGuide
from app.db.learning import SqlLearningRepository
from app.db.migrations import expected_heads, migration_config
from app.db.project_knowledge_models import GitHubRepositoryKnowledge
from app.db.session import Database
from app.services.catalog import LESSON_ID, seed_first_lesson
from app.services.learning import LearningService

MERGE = "0014_merge_learning_heads"
LATEST = "0015_project_learning_paths"
MAIN = "0010_custom_lessons"
FEATURE = "0013_repository_knowledge"
NOW = datetime(2026, 11, 4, tzinfo=UTC)


@pytest.fixture
def branch_database(settings: Settings) -> Iterator[Database]:
    database = Database(settings)
    try:
        yield database
    finally:
        database.dispose()


def migrate(database, target="head", *, downgrade=False):
    config = migration_config()
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        operation = command.downgrade if downgrade else command.upgrade
        operation(config, target)


def heads(database):
    with database.engine.connect() as connection:
        return frozenset(MigrationContext.configure(connection).get_current_heads())


def snapshot(database):
    """Capture every existing non-version table, not just newly introduced rows."""
    result = {}
    with database.engine.connect() as connection:
        for name in inspect(connection).get_table_names():
            if name == "alembic_version":
                continue
            quoted = connection.dialect.identifier_preparer.quote(name)
            rows = connection.exec_driver_sql(f"SELECT * FROM {quoted}")
            result[name] = (tuple(rows.keys()), tuple(sorted(map(tuple, rows), key=repr)))
    return result


def assert_integrity(database):
    with database.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []


def seed_legacy(database):
    """Use the real legacy service to preserve a pinned prediction and attempt."""
    learner, owner = uuid4(), uuid4()
    with database.engine.begin() as connection:
        connection.execute(insert(m.Learner), {"id": learner, "created_at": NOW})
        connection.execute(
            insert(m.User),
            {"id": owner, "created_at": NOW, "updated_at": NOW, "status": "active"},
        )
        connection.execute(insert(m.UserRole), {"user_id": owner, "role": "learner"})
        connection.execute(
            insert(m.AccountLearner),
            {
                "user_id": owner,
                "learner_id": learner,
                "claim_key": None,
                "claimed_credential_id": None,
                "created_at": NOW,
            },
        )
    repository = SqlLearningRepository(database)
    seed_first_lesson(repository)
    service = LearningService(repository, FakeTutorProvider(), lambda: NOW)
    session = service.create_session(learner, LESSON_ID, "1.0.0", "migration-session")
    service.predict(learner, session.id, "rejected", "The fields differ.", "migration-prediction")
    service.attempt(
        learner, session.id, "content", "Use the authored mapping.", "migration-attempt"
    )
    return owner


def seed_custom_history(database, owner):
    request, lesson, challenge = uuid4(), uuid4(), uuid4()
    with database.engine.begin() as connection:
        connection.execute(
            insert(CustomLessonRequestRow),
            {
                "id": request,
                "account_id": owner,
                "idempotency_key": "migration-custom",
                "request_hash": "a" * 64,
                "status": "ready",
                "error_code": None,
                "topic": "Python bindings",
                "language": "Python",
                "framework": None,
                "level": "beginner",
                "goal": "learn",
                "lesson_count": 1,
                "practice_styles": ["multiple_choice"],
                "created_at": NOW,
                "updated_at": NOW,
                "completed_at": NOW,
            },
        )
        connection.execute(
            insert(CustomLessonRow),
            {
                "id": lesson,
                "request_id": request,
                "account_id": owner,
                "position": 0,
                "title": "Names and values",
                "objective": "Recognize binding.",
                "language": "Python",
                "level": "beginner",
                "sections": [{"heading": "Names", "body": "A name refers to a value."}],
                "created_at": NOW,
            },
        )
        connection.execute(
            insert(CustomChallengeRow),
            {
                "id": challenge,
                "lesson_id": lesson,
                "position": 0,
                "kind": "multiple_choice",
                "prompt": "Which name is bound?",
                "code": None,
                "options": ["count", "other"],
                "hints": ["Read the assignment."],
                "explanation": "The left name is bound.",
                "verification_mode": "answer_key",
                "correct_option": 0,
                "model_answer": None,
            },
        )
        connection.execute(
            insert(CustomChallengeAnswerRow),
            {
                "id": uuid4(),
                "challenge_id": challenge,
                "account_id": owner,
                "idempotency_key": "migration-answer",
                "request_hash": "b" * 64,
                "correct": True,
                "created_at": NOW,
            },
        )


def seed_feature_history(database, owner):
    connection_id = uuid4()
    with database.engine.begin() as connection:
        connection.execute(
            insert(PrivateLearningGuide),
            {
                "id": uuid4(),
                "owner_id": owner,
                "creation_key": uuid4(),
                "request_sha256": "c" * 64,
                "request_payload": {"topic": "Python bindings"},
                "status": "generating",
                "version": "1.0.0",
                "content": None,
                "content_sha256": None,
                "source": None,
                "generation_provenance": None,
                "created_at": NOW,
                "updated_at": NOW,
                "reservation_expires_at": NOW + timedelta(minutes=1),
            },
        )
        connection.execute(
            insert(GitHubInstallationGrant),
            {
                "owner_id": owner,
                "installation_id": 11,
                "github_user_id": 22,
                "repository_ids": [33],
                "authorized_at": NOW,
                "token_ciphertext": "synthetic-migration-ciphertext",
                "credential_expires_at": NOW + timedelta(hours=1),
                "authorization_revision": 2,
            },
        )
        connection.execute(
            insert(GitHubRepositoryConnection),
            {
                "id": connection_id,
                "owner_id": owner,
                "installation_id": 11,
                "repository_id": 33,
                "full_name": "fixture/repository",
                "private": True,
                "created_at": NOW,
                "connection_revision": 2,
            },
        )
        for model in (GitHubProjectSnapshot, GitHubRepositoryKnowledge):
            connection.execute(
                insert(model),
                {
                    "connection_id": connection_id,
                    "commit_sha": "d" * 40,
                    "digest": "e" * 64,
                    "payload": {"preserve": "migration history"},
                    "created_at": NOW,
                },
            )


@pytest.mark.parametrize("dialect", ["sqlite", "postgresql"])
def test_both_dialect_graphs_have_one_head_and_retain_published_merge_and_branches(dialect):
    graph = ScriptDirectory.from_config(migration_config(dialect))
    assert graph.get_heads() == [LATEST]
    assert graph.get_revision(LATEST).down_revision == MERGE
    assert set(graph.get_revision(MERGE).down_revision) == {MAIN, FEATURE}
    assert graph.get_revision(MAIN).down_revision == "0009_durable_ai_controls"
    assert graph.get_revision("0010_private_learning_guides").down_revision == (
        "0009_durable_ai_controls"
    )
    baseline = graph.get_revision("0007_tutor_reservations")
    assert baseline.down_revision == (
        None if dialect == "postgresql" else "0006_candidate_lifecycle"
    )


@pytest.mark.parametrize("starting_head", [MAIN, FEATURE])
def test_populated_published_head_upgrades_without_changing_existing_rows(
    branch_database, starting_head
):
    database = branch_database
    migrate(database, starting_head)
    assert heads(database) == {starting_head}
    owner = seed_legacy(database)
    if starting_head == MAIN:
        seed_custom_history(database, owner)
    else:
        seed_feature_history(database, owner)
    before = snapshot(database)
    migrate(database)
    after = snapshot(database)
    assert {name: after[name] for name in before} == before
    assert heads(database) == expected_heads() == {LATEST}
    assert set(after) == set(Base.metadata.tables)
    assert {"custom_lessons", "private_learning_guides", "github_repository_knowledge"} <= set(
        after
    )
    with database.engine.begin() as connection:
        config = migration_config()
        config.attributes["connection"] = connection
        command.check(config)
    with pytest.raises(DBAPIError), database.engine.begin() as connection:
        connection.execute(
            update(m.Prediction).values(reasoning="Historical evidence cannot change.")
        )
    assert snapshot(database) == after
    assert_integrity(database)


def test_empty_merge_downgrade_and_reupgrade_preserve_both_branch_schemas(branch_database):
    database = branch_database
    migrate(database, MERGE)
    before = snapshot(database)
    migrate(database, FEATURE, downgrade=True)
    assert heads(database) == {MAIN, FEATURE}
    assert snapshot(database) == before
    migrate(database, MERGE)
    assert heads(database) == {MERGE}
    assert snapshot(database) == before
    migrate(database, "base", downgrade=True)
    assert inspect(database.engine).get_table_names() == ["alembic_version"]
    migrate(database)
    assert set(inspect(database.engine).get_table_names()) == set(Base.metadata.tables) | {
        "alembic_version"
    }
    assert_integrity(database)


def test_merge_refuses_entry_to_unguarded_published_custom_history_rollback(branch_database):
    database = branch_database
    migrate(database, MAIN)
    seed_custom_history(database, seed_legacy(database))
    migrate(database, MERGE)
    before = snapshot(database)
    with pytest.raises(RuntimeError, match="Custom lesson history exists"):
        migrate(database, "0009_durable_ai_controls", downgrade=True)
    assert heads(database) == {MERGE}
    assert snapshot(database) == before
    assert_integrity(database)


def test_published_feature_immutable_knowledge_and_downgrade_guards_survive_merge(branch_database):
    database = branch_database
    migrate(database, FEATURE)
    seed_feature_history(database, seed_legacy(database))
    migrate(database, MERGE)
    before = snapshot(database)
    with pytest.raises(DBAPIError), database.engine.begin() as connection:
        connection.execute(update(GitHubRepositoryKnowledge).values(digest="f" * 64))
    with pytest.raises(RuntimeError, match="Repository knowledge history exists"):
        migrate(database, "0012_github_authorization", downgrade=True)
    assert heads(database) == {MERGE}
    assert snapshot(database) == before
    assert_integrity(database)
