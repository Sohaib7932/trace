"""Durable encrypted GitHub authorization and local disconnect, without live calls."""

import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Event, get_ident
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import event, func, select, text, update

from alembic import command
from app.core.errors import ApplicationError
from app.core.github_credentials import GitHubCredentialVault
from app.db.github_models import GitHubAuthorizationState, GitHubProjectSnapshot
from app.db.github_projects import SqlGitHubProjectRepository
from app.db.migrations import migration_config
from app.schemas.github_projects import InstallationComplete
from app.services.github_projects import GitHubProjectService
from tests.integration.test_github_projects import (
    SHA,
    FakeAI,
    FakeGitHub,
    config,
    connected,
)
from tests.integration.test_github_projects import (
    project as project,  # noqa: F401
)
from tests.integration.test_live_ai_http import api as api  # noqa: F401


def test_encrypted_authorization_survives_new_service_and_client(project):
    connection = connected(project)
    repository = SqlGitHubProjectRepository(project.db)
    grant = repository.authorization_grant(project.owner, 11)
    assert grant is not None and grant.token_ciphertext
    assert "fixture-user-token" not in grant.token_ciphertext
    assert "fixture-user-token" not in repr(grant)
    fresh_client = FakeGitHub(config())
    try:
        fresh_service = GitHubProjectService(
            repository, config(), fresh_client, FakeAI(), project.clock
        )
        assert fresh_service.repositories(project.owner, 11)[0].repository_id == 22
        assert fresh_service.authorize_connection(
            project.owner, UUID(connection.id)
        ).connection == (connection)
        assert fresh_client.exchanges == 0
    finally:
        fresh_client.close()


def test_ciphertext_is_bound_to_owner_installation_and_github_identity(project):
    connected(project)
    grant = project.service.repository.authorization_grant(project.owner, 11)
    assert grant is not None
    vault = GitHubCredentialVault(config().token_encryption_key)
    assert vault.decrypt(grant).get_secret_value() == "fixture-user-token"
    for changed in (
        replace(grant, owner_id=uuid4()),
        replace(grant, installation_id=12),
        replace(grant, github_user_id=999),
        replace(grant, token_ciphertext="tampered-ciphertext"),
    ):
        with pytest.raises(ApplicationError) as denied:
            vault.decrypt(changed)
        assert denied.value.code == "github_reauthorization_required"
        assert "fixture-user-token" not in str(denied.value)
    other = GitHubCredentialVault(SecretStr(base64.urlsafe_b64encode(b"x" * 32).decode()))
    with pytest.raises(ApplicationError):
        other.decrypt(grant)


def test_disconnect_connection_is_owned_idempotent_and_preserves_snapshot(project):
    connection = connected(project)
    identity = UUID(connection.id)
    snapshot = project.service.sync(project.owner, identity, SHA)
    lease = project.service.authorize_connection(project.owner, identity)
    result = project.service.disconnect_connection(project.owner, identity)
    assert result.id == connection.id and result.status == "disconnected"
    assert project.service.disconnect_connection(project.owner, identity) == result
    assert project.service.connections(project.owner)[0].status == "disconnected"
    with pytest.raises(ApplicationError) as denied:
        project.service.snapshot(project.owner, identity, SHA)
    assert denied.value.status_code == 404
    assert not project.service.repository.lease_current(lease, project.clock())
    with project.db.session() as db:
        saved = db.get(GitHubProjectSnapshot, (identity, SHA))
        assert saved is not None and saved.digest == snapshot.digest
    # An explicit authenticated connect is needed to reactivate this repository.
    reconnected = project.service.connect(project.owner, 11, 22)
    assert reconnected.id == connection.id and reconnected.status == "connected"
    with pytest.raises(ApplicationError):
        project.service.assert_authorization(project.owner, lease)
    assert project.service.snapshot(project.owner, identity, SHA) == snapshot


def test_disconnect_installation_wipes_ciphertext_and_retains_history(project):
    connection = connected(project)
    snapshot = project.service.sync(project.owner, UUID(connection.id), SHA)
    result = project.service.disconnect_installation(project.owner, 11)
    assert result.status == "disconnected" and result.authorization_expires_at is None
    grant = project.service.repository.authorization_grant(project.owner, 11)
    assert grant is not None and grant.token_ciphertext is None
    assert grant.disconnected_at == project.clock()
    project.service.disconnect_installation(project.owner, 11)
    again = project.service.repository.authorization_grant(project.owner, 11)
    assert again is not None and again.authorization_revision == grant.authorization_revision
    assert project.service.installations(project.owner)[0].status == "disconnected"
    with pytest.raises(ApplicationError):
        project.service.snapshot(project.owner, UUID(connection.id), SHA)
    with project.db.session() as db:
        assert db.get(GitHubProjectSnapshot, (UUID(connection.id), SHA)).digest == snapshot.digest


def test_foreign_disconnect_does_not_change_owner_grants_or_connections(project):
    connection = connected(project)
    lease = project.service.authorize_connection(project.owner, UUID(connection.id))
    for operation in (
        lambda: project.service.disconnect_connection(uuid4(), UUID(connection.id)),
        lambda: project.service.disconnect_installation(uuid4(), 11),
    ):
        with pytest.raises(ApplicationError) as missing:
            operation()
        assert missing.value.status_code == 404
    project.service.assert_authorization(project.owner, lease)


def test_disconnect_during_source_fetch_cannot_save_or_release_snapshot(project, monkeypatch):
    connection = connected(project)
    identity = UUID(connection.id)
    original = project.client.content

    def disconnected(*args, **kwargs):
        result = original(*args, **kwargs)
        project.service.disconnect_connection(project.owner, identity)
        return result

    monkeypatch.setattr(project.client, "content", disconnected)
    with pytest.raises(ApplicationError):
        project.service.sync(project.owner, identity, SHA)
    with project.db.session() as db:
        assert db.scalar(select(func.count()).select_from(GitHubProjectSnapshot)) == 0


def test_disconnect_during_ai_call_cannot_release_learning_path(project, monkeypatch):
    connection = connected(project)
    identity = UUID(connection.id)
    project.service.sync(project.owner, identity, SHA)
    original = project.ai.complete

    def disconnected(**kwargs):
        result = original(**kwargs)
        project.service.disconnect_installation(project.owner, 11)
        return result

    monkeypatch.setattr(project.ai, "complete", disconnected)
    with pytest.raises(ApplicationError):
        project.service.learning_path(project.owner, identity, SHA)
    assert len(project.ai.calls) == 1


def test_reauthorization_changes_revision_and_invalidates_old_lease(project):
    connection = connected(project)
    lease = project.service.authorize_connection(project.owner, UUID(connection.id))
    state = project.service.start(project.owner)
    project.service.complete(
        project.owner,
        InstallationComplete(installation_id=11, state=state.state, code="fixture-code"),
    )
    fresh = project.service.authorize_connection(project.owner, UUID(connection.id))
    assert fresh.authorization_revision > lease.authorization_revision
    with pytest.raises(ApplicationError) as stale:
        project.service.assert_authorization(project.owner, lease)
    assert stale.value.code == "github_access_changed"


def test_expired_proof_is_reported_and_cannot_be_used_after_restart(project):
    connected(project)
    project.clock.advance(301)
    assert project.service.installations(project.owner)[0].status == "reauthorization_required"
    service = GitHubProjectService(
        SqlGitHubProjectRepository(project.db), config(), project.client, FakeAI(), project.clock
    )
    with pytest.raises(ApplicationError) as expired:
        service.repositories(project.owner, 11)
    assert expired.value.code == "github_reauthorization_required"


def test_concurrent_disconnects_are_idempotent(project):
    connection = connected(project)
    identity = UUID(connection.id)
    before = project.service.authorize_connection(project.owner, identity)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(
            workers.map(
                lambda _: project.service.disconnect_connection(project.owner, identity), (1, 2)
            )
        )
    assert all(item.status == "disconnected" for item in results)
    current = project.service.repository.connection_lease(project.owner, identity)
    assert current.connection_revision == before.connection_revision + 1


def test_binding_waits_for_concurrent_state_writer_without_read_lock_upgrade(project):
    """Reproduce callback interleaving without a timing-dependent stress race.

    SQLite cannot upgrade a SHARED read lock while another transaction owns the
    writer reservation and needs that reader to finish before commit. Binding
    must enter through write admission; retaining a grant SELECT before its
    first write reproduces the published CI failure under this interleaving.
    """
    repository = SqlGitHubProjectRepository(project.db)
    now, state_id = project.clock(), uuid4()
    expiry = now + timedelta(minutes=5)
    repository.reserve_state(project.owner, state_id, expiry)
    ciphertext = GitHubCredentialVault(config().token_encryption_key).encrypt(
        project.owner, 11, 321, SecretStr("fixture-user-token"), expiry
    )
    writer_ready, binding_attempted, writer_committing = Event(), Event(), Event()
    writer_identity = []

    def before_write(connection, cursor, statement, parameters, context, executemany):
        sql = statement.lstrip().upper()
        if sql.startswith(
            ("UPDATE GITHUB_INSTALLATION_GRANTS", "INSERT INTO GITHUB_INSTALLATION_GRANTS")
        ):
            binding_attempted.set()
            assert writer_committing.wait(timeout=5)

    def before_commit(connection):
        if writer_identity and get_ident() == writer_identity[0]:
            # SQLAlchemy emits this immediately before DBAPI commit. A previous
            # grant SELECT would still hold its SHARED lock at this exact point.
            writer_committing.set()

    def state_writer():
        writer_identity.append(get_ident())
        with project.db.session() as session, session.begin():
            changed = session.execute(
                update(GitHubAuthorizationState)
                .where(GitHubAuthorizationState.id == state_id)
                .values(consumed_at=now)
            )
            assert changed.rowcount == 1
            writer_ready.set()
            assert binding_attempted.wait(timeout=5)

    def bind():
        return repository.bind_installation(
            project.owner,
            11,
            321,
            [22],
            now,
            token_ciphertext=ciphertext,
            credential_expires_at=expiry,
        )

    event.listen(project.db.engine, "before_cursor_execute", before_write)
    event.listen(project.db.engine, "commit", before_commit)
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            writer = workers.submit(state_writer)
            assert writer_ready.wait(timeout=5)
            binding = workers.submit(bind)
            try:
                result = binding.result(timeout=10)
            finally:
                # Release both workers even if an assertion or driver call fails.
                binding_attempted.set()
                writer_committing.set()
                writer.result(timeout=10)
    finally:
        event.remove(project.db.engine, "before_cursor_execute", before_write)
        event.remove(project.db.engine, "commit", before_commit)
    assert result.owner_id == project.owner and result.repository_ids == (22,)
    assert repository.authorization_grant(project.owner, 11) == result


def test_empty_authorization_migration_round_trip(database):
    migration = migration_config()
    with database.engine.begin() as connection:
        migration.attributes["connection"] = connection
        command.downgrade(migration, "0011_github_projects")
        command.upgrade(migration, "head")
        assert connection.scalar(text("PRAGMA integrity_check")) == "ok"
        assert list(connection.execute(text("PRAGMA foreign_key_check"))) == []


def test_populated_authorization_migration_refuses_loss_of_private_history(project):
    connected(project)
    migration = migration_config()
    with project.db.engine.begin() as connection:
        migration.attributes["connection"] = connection
        with pytest.raises(RuntimeError, match="history exists"):
            command.downgrade(migration, "0011_github_projects")


def test_enabled_configuration_requires_independent_valid_encryption_key():
    values = config().model_dump()
    for key in ("", "not-a-valid-fernet-key"):
        with pytest.raises(ValidationError) as invalid:
            type(config())(_env_file=None, **{**values, "token_encryption_key": SecretStr(key)})
        if key:
            assert key not in str(invalid.value)


def test_http_disconnect_requires_account_origin_and_ownership(api, project):
    # Use the real API's own learner so successful disconnect can be exercised.
    from tests.integration.test_github_projects import config as fixture_config

    service = GitHubProjectService(
        SqlGitHubProjectRepository(api.database),
        fixture_config(),
        project.client,
        FakeAI(),
        api.clock,
    )
    api.app.state.github_projects = service
    prefix = "/api/v1/projects/github"
    state = api.client.post(prefix + "/installations/start").json()["state"]
    assert (
        api.client.post(
            prefix + "/installations/complete",
            json={"installation_id": 11, "state": state, "code": "fixture-code"},
        ).status_code
        == 200
    )
    connection = api.client.post(
        prefix + "/repositories", json={"installation_id": 11, "repository_id": 22}
    ).json()
    path = prefix + f"/repositories/{connection['id']}/disconnect"
    assert api.client.post(path, headers={"Origin": "https://evil.test"}).status_code == 403
    result = api.client.post(path)
    assert result.status_code == 200 and result.json()["status"] == "disconnected"
    assert result.headers["cache-control"] == "no-store"
    assert "fixture-user-token" not in result.text
    missing = api.client.post(prefix + f"/repositories/{uuid4()}/disconnect")
    assert missing.status_code == 404
    installation = api.client.post(prefix + "/installations/11/disconnect")
    assert installation.status_code == 200 and installation.json()["status"] == "disconnected"
    assert "token" not in installation.text
