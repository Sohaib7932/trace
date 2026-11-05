"""Append-only generated-path persistence and migrations on disposable databases."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier, Event
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, insert, inspect, select, text, update
from sqlalchemy.exc import DBAPIError

from alembic import command
from app.core.errors import ApplicationError
from app.db.github_models import GitHubProjectLearningPath, GitHubProjectSnapshot
from app.db.github_projects import SqlGitHubProjectRepository
from app.db.migrations import migration_config
from app.domain.project_learning import canonical_digest
from app.schemas.github_projects import ProjectLearningPath
from tests.integration.test_github_projects import SHA, connected
from tests.integration.test_github_projects import project as project  # noqa: F401


def path_value(snapshot, generated_at, *, identity=None, title="Explore the greeting"):
    source = next(item for item in snapshot.references if item.kind == "source")
    return ProjectLearningPath.model_validate(
        {
            "id": str(identity or uuid4()),
            "status": "ready",
            "source": "test_fixture",
            "snapshot_digest": snapshot.digest,
            "commit_sha": snapshot.commit_sha,
            "generation": {
                "provider_id": "mock",
                "requested_model_id": "fixture-model",
                "returned_model_id": "fixture-model",
                "generated_at": generated_at,
            },
            "content": {
                "title": title,
                "steps": [
                    {
                        "title": "Read the function",
                        "explanation": "Inspect the supplied greeting function.",
                        "question": "What does the function return?",
                        "reference_ids": [source.reference_id],
                    }
                ],
            },
        }
    )


@pytest.fixture
def persisted_path(project):
    connection = connected(project)
    identity = UUID(connection.id)
    snapshot = project.service.sync(project.owner, identity, SHA)
    lease = project.service.authorize_connection(project.owner, identity)
    return (
        project.service.repository,
        path_value(snapshot, project.clock()),
        lease,
        snapshot,
    )


def count(project):
    with project.db.session() as session:
        return session.scalar(select(func.count()).select_from(GitHubProjectLearningPath))


def test_save_commits_payload_provenance_digest_and_exact_replay_is_idempotent(
    project, persisted_path
):
    repository, value, lease, snapshot = persisted_path
    repository.save_learning_path(value, lease=lease, now=project.clock())
    fresh = SqlGitHubProjectRepository(project.db)
    assert fresh.load_learning_path(project.owner, UUID(lease.connection.id), SHA) == value
    with project.db.session() as session:
        row = session.get(GitHubProjectLearningPath, UUID(value.id))
        assert row.payload == value.model_dump(mode="json")
        assert row.payload_digest == canonical_digest(row.payload)
        assert row.snapshot_digest == snapshot.digest
        assert row.generated_at == value.generation.generated_at
    repository.save_learning_path(value, lease=lease, now=project.clock())
    assert count(project) == 1
    assert repository.load_snapshot(UUID(lease.connection.id), SHA) == snapshot


def test_generated_timestamp_survives_later_transaction_clock(project, persisted_path):
    repository, value, lease, _ = persisted_path
    project.clock.advance(1)
    repository.save_learning_path(value, lease=lease, now=project.clock())
    with project.db.session() as session:
        assert session.get(GitHubProjectLearningPath, UUID(value.id)).generated_at == (
            value.generation.generated_at
        )


def test_multiple_generations_are_append_only_and_latest_is_selected(project, persisted_path):
    repository, first, lease, snapshot = persisted_path
    repository.save_learning_path(first, lease=lease, now=project.clock())
    project.clock.advance(1)
    second = path_value(snapshot, project.clock(), title="Explore the same pinned source again")
    repository.save_learning_path(second, lease=lease, now=project.clock())
    assert repository.load_learning_path(project.owner, UUID(lease.connection.id), SHA) == second
    with project.db.session() as session:
        assert session.get(GitHubProjectLearningPath, UUID(first.id)).payload == first.model_dump(
            mode="json"
        )
    assert count(project) == 2


def test_equal_generation_times_use_descending_id_as_deterministic_tie_breaker(
    project, persisted_path
):
    repository, _, lease, snapshot = persisted_path
    lower = path_value(snapshot, project.clock(), identity=UUID(int=1))
    higher = path_value(snapshot, project.clock(), identity=UUID(int=2))
    for value in (higher, lower):
        repository.save_learning_path(value, lease=lease, now=project.clock())
    assert repository.load_learning_path(project.owner, UUID(lease.connection.id), SHA) == higher


def test_conflicting_payload_cannot_replace_a_path_identity(project, persisted_path):
    repository, value, lease, snapshot = persisted_path
    repository.save_learning_path(value, lease=lease, now=project.clock())
    changed = path_value(snapshot, project.clock(), identity=UUID(value.id), title="Different text")
    with pytest.raises(ApplicationError) as conflict:
        repository.save_learning_path(changed, lease=lease, now=project.clock())
    assert conflict.value.status_code == 503
    assert repository.load_learning_path(project.owner, UUID(lease.connection.id), SHA) == value
    assert count(project) == 1


def test_owner_connection_and_commit_filters_never_release_foreign_payloads(
    project, persisted_path
):
    repository, value, lease, _ = persisted_path
    repository.save_learning_path(value, lease=lease, now=project.clock())
    assert repository.load_learning_path(uuid4(), UUID(lease.connection.id), SHA) is None
    assert repository.load_learning_path(project.owner, uuid4(), SHA) is None
    assert repository.load_learning_path(project.owner, UUID(lease.connection.id), "b" * 40) is None


@pytest.mark.parametrize(
    "mode", ["foreign", "disconnected", "reconnected", "reauthorized", "expired"]
)
def test_stale_or_foreign_lease_cannot_append(project, persisted_path, mode):
    repository, value, lease, snapshot = persisted_path
    if mode == "foreign":
        lease = replace(lease, owner_id=uuid4())
    elif mode in {"disconnected", "reconnected"}:
        project.service.disconnect_connection(project.owner, UUID(lease.connection.id))
        if mode == "reconnected":
            project.service.connect(project.owner, 11, 22)
    elif mode == "reauthorized":
        grant = repository.authorization_grant(project.owner, 11)
        repository.bind_installation(
            project.owner,
            11,
            grant.github_user_id,
            list(grant.repository_ids),
            project.clock(),
            token_ciphertext=grant.token_ciphertext,
            credential_expires_at=grant.credential_expires_at,
        )
    else:
        project.clock.advance(301)
        value = path_value(snapshot, project.clock())
    with pytest.raises(ApplicationError) as changed:
        repository.save_learning_path(value, lease=lease, now=project.clock())
    assert changed.value.status_code == 409
    assert count(project) == 0


def test_committed_disconnect_blocks_a_waiting_finalizer(project, persisted_path):
    repository, value, lease, _ = persisted_path
    release = Event()

    def save():
        assert release.wait(timeout=5)
        repository.save_learning_path(value, lease=lease, now=project.clock())

    with ThreadPoolExecutor(max_workers=1) as worker:
        pending = worker.submit(save)
        try:
            project.service.disconnect_installation(project.owner, 11)
        finally:
            release.set()
        with pytest.raises(ApplicationError) as changed:
            pending.result(timeout=10)
    assert changed.value.status_code == 409
    assert count(project) == 0


def test_concurrent_exact_replays_create_one_immutable_row(project, persisted_path):
    repository, value, lease, _ = persisted_path
    barrier = Barrier(2)

    def save(_):
        barrier.wait(timeout=5)
        return repository.save_learning_path(value, lease=lease, now=project.clock())

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert list(workers.map(save, (1, 2))) == [None, None]
    assert count(project) == 1


def test_commit_failure_rolls_back_and_sanitizes_sql_failure(project, persisted_path):
    repository, value, lease, _ = persisted_path

    def fail_commit(_):
        raise RuntimeError("fixture-private-database-failure")

    event.listen(project.db.engine, "commit", fail_commit)
    try:
        with pytest.raises(ApplicationError) as failed:
            repository.save_learning_path(value, lease=lease, now=project.clock())
        assert failed.value.status_code == 503
        assert "fixture-private" not in str(failed.value)
    finally:
        event.remove(project.db.engine, "commit", fail_commit)
    assert count(project) == 0
    repository.save_learning_path(value, lease=lease, now=project.clock())
    assert count(project) == 1


@pytest.mark.parametrize("mode", ["digest", "citation", "missing_snapshot", "future_timestamp"])
def test_invalid_content_or_pin_never_persists(project, persisted_path, mode):
    repository, value, lease, _ = persisted_path
    payload = value.model_dump()
    if mode == "digest":
        payload["snapshot_digest"] = "f" * 64
    elif mode == "citation":
        payload["content"]["steps"][0]["reference_ids"] = ["f" * 64]
    elif mode == "missing_snapshot":
        payload["commit_sha"] = "b" * 40
    else:
        payload["generation"]["generated_at"] += timedelta(seconds=1)
    wrong = ProjectLearningPath.model_validate(payload)
    with pytest.raises(ApplicationError) as failed:
        repository.save_learning_path(wrong, lease=lease, now=project.clock())
    assert failed.value.status_code == 503
    assert count(project) == 0


@pytest.mark.parametrize("column", ["payload_digest", "snapshot_digest", "payload", "generated_at"])
def test_corrupt_archived_rows_fail_closed(project, persisted_path, column):
    repository, value, lease, _ = persisted_path
    repository.save_learning_path(value, lease=lease, now=project.clock())
    change = {column: "f" * 64}
    if column == "payload":
        payload = value.model_dump(mode="json")
        payload["id"] = str(uuid4())
        change = {"payload": payload, "payload_digest": canonical_digest(payload)}
    elif column == "generated_at":
        change = {"generated_at": project.clock() + timedelta(seconds=1)}
    # Fault injection changes only this disposable DB; application code never
    # disables the immutable triggers.
    with project.db.session() as session, session.begin():
        session.execute(text("DROP TRIGGER github_learning_paths_no_update"))
        session.execute(update(GitHubProjectLearningPath).values(**change))
    with pytest.raises(ApplicationError) as failed:
        repository.load_learning_path(project.owner, UUID(lease.connection.id), SHA)
    assert failed.value.status_code == 503


@pytest.mark.parametrize("action", ["UPDATE", "DELETE"])
def test_path_history_is_sql_immutable(project, persisted_path, action):
    repository, value, lease, _ = persisted_path
    repository.save_learning_path(value, lease=lease, now=project.clock())
    statement = (
        "UPDATE github_project_learning_paths SET payload_digest = :digest"
        if action == "UPDATE"
        else "DELETE FROM github_project_learning_paths"
    )
    with (
        project.db.session() as session,
        session.begin(),
        pytest.raises(DBAPIError, match="immutable project learning path"),
    ):
        session.execute(text(statement), {"digest": "f" * 64})
    assert count(project) == 1


@pytest.mark.parametrize("violation", ["missing_snapshot", "digest_length"])
def test_sql_constraints_require_an_existing_snapshot_and_complete_digests(
    project, persisted_path, violation
):
    _, value, lease, snapshot = persisted_path
    payload = value.model_dump(mode="json")
    fields = {
        "id": UUID(value.id),
        "owner_id": project.owner,
        "connection_id": UUID(lease.connection.id),
        "commit_sha": "b" * 40 if violation == "missing_snapshot" else SHA,
        "snapshot_digest": snapshot.digest,
        "payload": payload,
        "payload_digest": "short" if violation == "digest_length" else canonical_digest(payload),
        "generated_at": project.clock(),
    }
    with project.db.session() as session, session.begin(), pytest.raises(DBAPIError):
        session.execute(insert(GitHubProjectLearningPath), fields)
    assert count(project) == 0


def test_empty_0015_round_trip_preserves_existing_snapshot_and_tables(project, persisted_path):
    repository, _, lease, snapshot = persisted_path
    before_tables = set(inspect(project.db.engine).get_table_names())
    with project.db.session() as session:
        row = session.get(GitHubProjectSnapshot, (UUID(lease.connection.id), SHA))
        payload, digest = row.payload, row.digest
    migration = migration_config()
    with project.db.engine.begin() as connection:
        migration.attributes["connection"] = connection
        command.downgrade(migration, "0014_merge_learning_heads")
        assert "github_project_learning_paths" not in inspect(connection).get_table_names()
        command.upgrade(migration, "head")
        assert connection.scalar(text("PRAGMA integrity_check")) == "ok"
        assert list(connection.execute(text("PRAGMA foreign_key_check"))) == []
    assert set(inspect(project.db.engine).get_table_names()) == before_tables
    with project.db.session() as session:
        row = session.get(GitHubProjectSnapshot, (UUID(lease.connection.id), SHA))
        assert (row.payload, row.digest) == (payload, digest)
    assert repository.load_snapshot(UUID(lease.connection.id), SHA) == snapshot


def test_populated_0015_downgrade_refuses_loss_and_preserves_history(project, persisted_path):
    repository, value, lease, _ = persisted_path
    repository.save_learning_path(value, lease=lease, now=project.clock())
    migration = migration_config()
    with project.db.engine.begin() as connection:
        migration.attributes["connection"] = connection
        with pytest.raises(RuntimeError, match="Project learning path history exists"):
            command.downgrade(migration, "0014_merge_learning_heads")
    assert repository.load_learning_path(project.owner, UUID(lease.connection.id), SHA) == value
    assert count(project) == 1
