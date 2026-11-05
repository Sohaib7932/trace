"""Durable private paths with deterministic providers and disposable databases only."""

import json
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update

from app.core.errors import ApplicationError
from app.db.github_models import GitHubProjectLearningPath
from app.db.github_projects import SqlGitHubProjectRepository
from app.db.models import User
from app.schemas.github_projects import ProjectLearningPath
from app.services.github_projects import GitHubProjectService
from tests.integration.test_github_projects import SHA, FakeAI, FakeGitHub, config, connected
from tests.integration.test_github_projects import project as project  # noqa: F401
from tests.integration.test_live_ai_http import api as api  # noqa: F401


def prepare(project):
    identity = UUID(connected(project).id)
    snapshot = project.service.sync(project.owner, identity, SHA)
    return identity, snapshot


def count(project):
    with project.db.session() as db:
        return db.scalar(select(func.count()).select_from(GitHubProjectLearningPath))


def test_generation_is_committed_with_exact_content_citations_and_safe_provenance(project):
    identity, snapshot = prepare(project)
    result = project.service.learning_path(project.owner, identity, SHA)
    assert result.status == "ready" and result.id and result.generation
    assert result.generation.provider_id == "mock"
    assert result.generation.requested_model_id == "fixture-project-model"
    assert result.generation.generated_at == project.clock()
    # Independent session observes committed data before the service reports ready.
    with project.db.session() as db:
        row = db.get(GitHubProjectLearningPath, UUID(result.id))
        assert row.owner_id == project.owner
        assert row.connection_id == identity and row.commit_sha == SHA
        assert row.snapshot_digest == snapshot.digest
        assert row.payload == result.model_dump(mode="json")
        assert row.payload["content"]["steps"][0]["reference_ids"] == [
            snapshot.references[0].reference_id
        ]
        serialized = json.dumps(row.payload)
        for forbidden in (
            "fixture-user-token",
            "fixture-installation-token",
            "fixture-only-secret",
        ):
            assert forbidden not in serialized
        assert "request_id" not in row.payload["generation"]
    assert count(project) == 1


def test_fresh_service_can_load_latest_saved_path_without_calling_ai(project):
    identity, _ = prepare(project)
    first = project.service.learning_path(project.owner, identity, SHA)
    project.clock.advance(1)
    second = project.service.learning_path(project.owner, identity, SHA)
    assert first.id != second.id and count(project) == 2
    fresh_ai = FakeAI()
    fresh = GitHubProjectService(
        SqlGitHubProjectRepository(project.db), config(), project.client, fresh_ai, project.clock
    )
    assert fresh.saved_learning_path(project.owner, identity, SHA) == second
    assert fresh_ai.calls == []


def test_missing_saved_path_is_404_without_generating(project):
    identity, _ = prepare(project)
    with pytest.raises(ApplicationError) as error:
        project.service.saved_learning_path(project.owner, identity, SHA)
    assert error.value.status_code == 404
    assert project.ai.calls == [] and count(project) == 0


@pytest.mark.parametrize("operation", ["saved_learning_path", "learning_path"])
def test_other_owner_cannot_generate_or_load_saved_content(project, operation):
    identity, _ = prepare(project)
    project.service.learning_path(project.owner, identity, SHA)
    before = len(project.ai.calls)
    for target in (identity, uuid4()):
        with pytest.raises(ApplicationError) as denied:
            getattr(project.service, operation)(uuid4(), target, SHA)
        assert denied.value.status_code == 404
    assert len(project.ai.calls) == before and count(project) == 1


@pytest.mark.parametrize("reason", ["disconnect", "expire", "revoke"])
def test_saved_read_respects_current_authorization(project, reason):
    identity, _ = prepare(project)
    project.service.learning_path(project.owner, identity, SHA)
    if reason == "disconnect":
        project.service.disconnect_connection(project.owner, identity)
    elif reason == "expire":
        project.clock.advance(301)
    else:
        project.client.revoked = True
    with pytest.raises(ApplicationError):
        project.service.saved_learning_path(project.owner, identity, SHA)
    assert count(project) == 1  # revocation preserves private historical records
    assert len(project.ai.calls) == 1


@pytest.mark.parametrize("reason", ["invalid", "fail", "secret"])
def test_invalid_failed_or_sensitive_provider_output_is_never_persisted(project, reason):
    identity, _ = prepare(project)
    if reason == "secret":
        project.ai.claim = "github_pat_" + "a" * 30
    else:
        setattr(project.ai, reason, True)
    result = project.service.learning_path(project.owner, identity, SHA)
    assert result.status == "unavailable"
    assert result.id is None and result.generation is None and result.content is None
    assert count(project) == 0


def test_provider_work_holds_no_learner_write_transaction(project, monkeypatch):
    identity, _ = prepare(project)
    original = project.ai.complete

    def during_provider(**kwargs):
        with project.db.session() as db, db.begin():
            db.execute(
                update(User).where(User.id == project.owner).values(updated_at=project.clock())
            )
        return original(**kwargs)

    monkeypatch.setattr(project.ai, "complete", during_provider)
    assert project.service.learning_path(project.owner, identity, SHA).status == "ready"


def test_generation_with_advancing_clock_commits_before_receipt_release(project):
    identity, _ = prepare(project)
    current = project.clock()

    def advancing():
        nonlocal current
        current += timedelta(microseconds=1)
        return current

    project.service.clock = advancing
    result = project.service.learning_path(project.owner, identity, SHA)
    assert result.status == "ready" and result.generation.generated_at < current
    assert project.service.saved_learning_path(project.owner, identity, SHA) == result


@pytest.mark.parametrize("field", ["provider_id", "requested_model_id", "returned_model_id"])
def test_unsafe_generation_metadata_is_rejected_without_persistence(project, monkeypatch, field):
    identity, _ = prepare(project)
    original = project.ai.complete

    def invalid_metadata(**kwargs):
        value = original(**kwargs)
        setattr(value, field, "github_pat_" + "x" * 30)
        return value

    monkeypatch.setattr(project.ai, "complete", invalid_metadata)
    result = project.service.learning_path(project.owner, identity, SHA)
    assert result.status == "unavailable" and count(project) == 0


@pytest.mark.parametrize("mutation", ["commit", "snapshot", "citation", "status"])
def test_saved_content_is_revalidated_before_release(project, monkeypatch, mutation):
    identity, _ = prepare(project)
    saved = project.service.learning_path(project.owner, identity, SHA)
    if mutation == "commit":
        bad = saved.model_copy(update={"commit_sha": "b" * 40})
    elif mutation == "snapshot":
        bad = saved.model_copy(update={"snapshot_digest": "f" * 64})
    elif mutation == "status":
        bad = saved.model_copy(update={"status": "unavailable"})
    else:
        step = saved.content.steps[0].model_copy(update={"reference_ids": ("f" * 64,)})
        bad = saved.model_copy(
            update={"content": saved.content.model_copy(update={"steps": (step,)})}
        )
    monkeypatch.setattr(project.service.repository, "load_learning_path", lambda *args: bad)
    with pytest.raises(ApplicationError) as denied:
        project.service.saved_learning_path(project.owner, identity, SHA)
    assert denied.value.status_code == 503
    assert len(project.ai.calls) == 1


def setup_http(api):
    github = FakeGitHub(config())
    ai = FakeAI()
    api.app.state.github_projects = GitHubProjectService(
        SqlGitHubProjectRepository(api.database), config(), github, ai, api.clock
    )
    prefix = "/api/v1/projects/github"
    state = api.client.post(prefix + "/installations/start").json()["state"]
    assert (
        api.client.post(
            prefix + "/installations/complete", json={"state": state, "code": "fixture-code"}
        ).status_code
        == 200
    )
    connection = api.client.post(
        prefix + "/repositories", json={"installation_id": 11, "repository_id": 22}
    ).json()
    base = prefix + "/repositories/" + connection["id"]
    assert api.client.post(base + "/sync", json={"commit_sha": SHA}).status_code == 200
    return github, ai, base + "/learning-path"


def test_http_generate_then_load_returns_committed_private_receipt(api):
    github, ai, path = setup_http(api)
    try:
        generated = api.client.post(path, json={"commit_sha": SHA})
        assert generated.status_code == 200
        saved = ProjectLearningPath.model_validate_json(generated.text)
        with api.database.session() as db:
            assert db.get(GitHubProjectLearningPath, UUID(saved.id)) is not None
        loaded = api.client.get(path, params={"commit_sha": SHA})
        assert loaded.status_code == 200 and loaded.json() == generated.json()
        assert loaded.headers["cache-control"] == "no-store"
        assert loaded.headers["referrer-policy"] == "no-referrer"
        assert len(ai.calls) == 1
    finally:
        github.close()


def test_http_missing_saved_result_does_not_generate(api):
    github, ai, path = setup_http(api)
    try:
        missing = api.client.get(path, params={"commit_sha": SHA})
        assert missing.status_code == 404 and missing.headers["cache-control"] == "no-store"
        assert ai.calls == []
    finally:
        github.close()


def test_http_saved_path_rejects_guest_and_foreign_owner(api, project):
    identity, _ = prepare(project)
    project.service.learning_path(project.owner, identity, SHA)
    api.app.state.github_projects = project.service
    base = "/api/v1/projects/github/repositories/"
    for target in (identity, uuid4()):
        denied = api.client.get(base + str(target) + "/learning-path", params={"commit_sha": SHA})
        assert denied.status_code == 404 and "Explore the greeting" not in denied.text
    api.client.headers.pop("Authorization")
    denied = api.client.get(base + str(identity) + "/learning-path", params={"commit_sha": SHA})
    assert denied.status_code == 401 and "Explore the greeting" not in denied.text


def test_http_save_failure_never_returns_ready_or_database_details(api, monkeypatch):
    github, _, path = setup_http(api)
    try:

        def failed(*args, **kwargs):
            raise ApplicationError("dependency_unavailable", "Unable to save learning path.", 503)

        monkeypatch.setattr(api.app.state.github_projects.repository, "save_learning_path", failed)
        response = api.client.post(path, json={"commit_sha": SHA})
        assert response.status_code == 503 and response.headers["cache-control"] == "no-store"
        assert "Explore the greeting" not in response.text and '"ready"' not in response.text
        with api.database.session() as db:
            assert db.scalar(select(func.count()).select_from(GitHubProjectLearningPath)) == 0
    finally:
        github.close()
