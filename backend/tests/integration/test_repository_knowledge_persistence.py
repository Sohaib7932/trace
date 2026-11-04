"""Immutable V2 persistence with real SQL authorization leases, no external calls."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Event
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from alembic import command
from app.core.errors import ApplicationError
from app.db.github_models import GitHubProjectSnapshot
from app.db.migrations import migration_config
from app.db.project_knowledge import SqlProjectKnowledgeRepository
from app.db.project_knowledge_models import GitHubRepositoryKnowledge
from app.schemas.project_knowledge import RepositoryKnowledgeSnapshot
from app.services.project_ingestion import knowledge_digest
from tests.integration.test_github_projects import (
    SHA,
    connected,
)
from tests.integration.test_github_projects import (
    project as project,  # noqa: F401
)


def artifact(connection, *, commit_sha=SHA, text_suffix=""):
    refs, catalog = [], []
    for category, path, body in (
        ("frontend", "frontend/auth.tsx", "export function SignIn() {\n  return null;\n}"),
        ("backend", "backend/auth.py", "def authenticate(subject):\n    return subject"),
    ):
        body += text_suffix
        blob = hashlib.sha1(body.encode()).hexdigest()
        refs.append(
            {
                "reference_id": hashlib.sha256((commit_sha + path + body).encode()).hexdigest(),
                "digest": hashlib.sha256(body.encode()).hexdigest(),
                "path": path,
                "line_start": 1,
                "line_end": len(body.splitlines()),
                "text": body,
                "category": category,
                "blob_sha": blob,
            }
        )
        catalog.append(
            {
                "path": path,
                "kind": "file",
                "blob_sha": blob,
                "size": len(body.encode()),
                "category": category,
                "content_included": True,
            }
        )
    payload = {
        "connection_id": connection.id,
        "commit_sha": commit_sha,
        "digest": "0" * 64,
        "repository": {
            "repository_id": connection.repository_id,
            "full_name": connection.full_name,
            "private": connection.private,
            "default_branch": "main",
        },
        "catalog": catalog,
        "references": refs,
        "coverage": {
            "tree_complete": True,
            "history_complete": True,
            "changed_files_complete": True,
            "catalog_entries": 2,
            "fetched_files": 2,
            "omitted_files": 0,
        },
    }
    value = RepositoryKnowledgeSnapshot.model_validate(payload)
    return RepositoryKnowledgeSnapshot.model_validate(
        {**value.model_dump(mode="json"), "digest": knowledge_digest(value)}
    )


@pytest.fixture
def persisted(project):
    connection = connected(project)
    identity = UUID(connection.id)
    lease = project.service.authorize_connection(project.owner, identity)
    return SqlProjectKnowledgeRepository(project.db), artifact(connection), lease


def count(database):
    with database.session() as session:
        return session.scalar(select(func.count()).select_from(GitHubRepositoryKnowledge))


def test_save_load_duplicate_and_same_commit_collision_preserve_first_artifact(project, persisted):
    repository, value, lease = persisted
    assert repository.save(value, project.clock(), lease) is True
    assert repository.load(UUID(value.connection_id), value.commit_sha) == value
    assert repository.save(value, project.clock(), lease) is False
    alternative = artifact(lease.connection, text_suffix="\n# Another exact source")
    with pytest.raises(ApplicationError):
        repository.save(alternative, project.clock(), lease)
    assert repository.load(UUID(value.connection_id), value.commit_sha) == value
    assert count(project.db) == 1


def test_concurrent_identical_inserts_are_idempotent(project, persisted):
    repository, value, lease = persisted
    barrier = Barrier(2)

    def insert(_):
        barrier.wait(timeout=5)
        return repository.save(value, project.clock(), lease)

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(insert, (1, 2)))
    assert sorted(results) == [False, True]
    assert count(project.db) == 1


def test_foreign_owner_lease_cannot_save_or_change_owner_authorization(project, persisted):
    repository, value, lease = persisted
    foreign = replace(lease, owner_id=uuid4())
    with pytest.raises(ApplicationError) as denied:
        repository.save(value, project.clock(), foreign)
    assert denied.value.status_code == 409
    assert count(project.db) == 0
    project.service.assert_authorization(project.owner, lease)


def test_disconnected_connection_cannot_finalize_old_lease(project, persisted):
    repository, value, lease = persisted
    project.service.disconnect_connection(project.owner, UUID(value.connection_id))
    with pytest.raises(ApplicationError) as denied:
        repository.save(value, project.clock(), lease)
    assert denied.value.status_code == 409
    assert count(project.db) == 0


def test_reconnected_connection_still_rejects_prior_revision(project, persisted):
    repository, value, lease = persisted
    project.service.disconnect_connection(project.owner, UUID(value.connection_id))
    project.service.connect(project.owner, 11, 22)
    with pytest.raises(ApplicationError) as denied:
        repository.save(value, project.clock(), lease)
    assert denied.value.status_code == 409
    assert count(project.db) == 0


def test_rebound_authorization_rejects_prior_revision(project, persisted):
    repository, value, lease = persisted
    grants = project.service.repository
    before = grants.authorization_grant(project.owner, 11)
    assert before is not None and before.token_ciphertext and before.credential_expires_at
    current = grants.bind_installation(
        project.owner,
        11,
        before.github_user_id,
        list(before.repository_ids),
        project.clock(),
        token_ciphertext=before.token_ciphertext,
        credential_expires_at=before.credential_expires_at,
    )
    assert current.authorization_revision == before.authorization_revision + 1
    with pytest.raises(ApplicationError) as denied:
        repository.save(value, project.clock(), lease)
    assert denied.value.status_code == 409
    assert count(project.db) == 0


def test_expired_authorization_cannot_finalize(project, persisted):
    repository, value, lease = persisted
    project.clock.advance(301)
    with pytest.raises(ApplicationError) as denied:
        repository.save(value, project.clock(), lease)
    assert denied.value.status_code == 409
    assert count(project.db) == 0


def test_disconnect_committed_while_worker_waits_prevents_late_finalization(project, persisted):
    repository, value, lease = persisted
    release = Event()

    def finalize():
        assert release.wait(timeout=5)
        return repository.save(value, project.clock(), lease)

    with ThreadPoolExecutor(max_workers=1) as worker:
        future = worker.submit(finalize)
        project.service.disconnect_installation(project.owner, 11)
        release.set()
        with pytest.raises(ApplicationError) as denied:
            future.result(timeout=5)
    assert denied.value.status_code == 409
    assert count(project.db) == 0


@pytest.mark.parametrize("action", ("UPDATE", "DELETE"))
def test_knowledge_sql_triggers_reject_update_and_delete(project, persisted, action):
    repository, value, lease = persisted
    repository.save(value, project.clock(), lease)
    statement = (
        "UPDATE github_repository_knowledge SET digest = :digest"
        if action == "UPDATE"
        else "DELETE FROM github_repository_knowledge"
    )
    with (
        project.db.session() as session,
        session.begin(),
        pytest.raises(DBAPIError, match="immutable repository knowledge"),
    ):
        session.execute(text(statement), {"digest": "f" * 64})
    assert repository.load(UUID(value.connection_id), value.commit_sha) == value


def test_incorrect_digest_is_rejected_before_storage(project, persisted):
    repository, value, lease = persisted
    corrupt = value.model_copy(update={"digest": "f" * 64})
    with pytest.raises(ApplicationError):
        repository.save(corrupt, project.clock(), lease)
    assert count(project.db) == 0


def test_mismatched_connection_or_repository_metadata_is_rejected(project, persisted):
    repository, value, lease = persisted
    for updates in (
        {"connection_id": str(uuid4())},
        {"repository": {**value.repository.model_dump(), "repository_id": 999}},
        {"repository": {**value.repository.model_dump(), "full_name": "other/repository"}},
        {"repository": {**value.repository.model_dump(), "private": False}},
    ):
        wrong = RepositoryKnowledgeSnapshot.model_validate({**value.model_dump(), **updates})
        wrong = wrong.model_copy(update={"digest": knowledge_digest(wrong)})
        with pytest.raises(ApplicationError):
            repository.save(wrong, project.clock(), lease)
    assert count(project.db) == 0


def test_missing_and_corrupted_database_rows_fail_safely(project, persisted):
    repository, value, lease = persisted
    assert repository.load(UUID(value.connection_id), value.commit_sha) is None
    repository.save(value, project.clock(), lease)
    # Fault injection is confined to this disposable database. The production
    # trigger is separately asserted above and is not disabled in application code.
    with project.db.session() as session, session.begin():
        session.execute(text("DROP TRIGGER github_knowledge_no_update"))
        session.execute(update(GitHubRepositoryKnowledge).values(digest="e" * 64))
    with pytest.raises(ApplicationError) as denied:
        repository.load(UUID(value.connection_id), value.commit_sha)
    assert denied.value.status_code == 503


def test_empty_0013_downgrade_upgrade_preserves_legacy_v1_snapshot_and_digest(project):
    connection = connected(project)
    identity = UUID(connection.id)
    original = project.service.sync(project.owner, identity, SHA)
    with project.db.session() as session:
        row = session.get(GitHubProjectSnapshot, (identity, SHA))
        old_payload, old_digest = row.payload, row.digest
    migration = migration_config()
    with project.db.engine.begin() as connection:
        migration.attributes["connection"] = connection
        command.downgrade(migration, "0012_github_authorization")
        command.upgrade(migration, "head")
        assert connection.scalar(text("PRAGMA integrity_check")) == "ok"
        assert list(connection.execute(text("PRAGMA foreign_key_check"))) == []
    with project.db.session() as session:
        row = session.get(GitHubProjectSnapshot, (identity, SHA))
        assert row.payload == old_payload and row.digest == old_digest
    assert project.service.snapshot(project.owner, identity, SHA) == original


def test_populated_0013_downgrade_refuses_to_erase_knowledge(project, persisted):
    repository, value, lease = persisted
    repository.save(value, project.clock(), lease)
    migration = migration_config()
    with project.db.engine.begin() as connection:
        migration.attributes["connection"] = connection
        with pytest.raises(RuntimeError, match="history exists"):
            command.downgrade(migration, "0012_github_authorization")
    assert repository.load(UUID(value.connection_id), value.commit_sha) == value


def test_v2_write_does_not_change_existing_v1_receipt(project, persisted):
    repository, value, lease = persisted
    identity = UUID(value.connection_id)
    original = project.service.sync(project.owner, identity, SHA)
    repository.save(value, project.clock(), lease)
    assert project.service.snapshot(project.owner, identity, SHA) == original
    assert repository.load(identity, SHA) == value
