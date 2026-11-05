"""Actual protected routes and SQL with controlled repository/AI transports only."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ai.client import AITransportError
from app.db.github_projects import SqlGitHubProjectRepository
from app.db.project_knowledge import SqlProjectKnowledgeRepository
from app.schemas.github_projects import RepositoryView
from app.services.github_projects import GitHubProjectService
from app.services.project_knowledge import ProjectKnowledgeService
from tests.integration.test_github_projects import FakeGitHub, config
from tests.integration.test_live_ai_http import api as api  # noqa: F401
from tests.unit.test_project_ingestion import SHA, FixtureRepository


class WholeRepository(FakeGitHub):
    def __init__(self):
        super().__init__(config())
        self.fixture = FixtureRepository()
        for name in ("repository", "tree", "commit_page", "history_page", "content"):
            setattr(self, name, getattr(self.fixture, name))

    def accessible_repositories(self, token, installation_id):
        super().accessible_repositories(token, installation_id)
        return [RepositoryView(repository_id=22, full_name="fixture/architecture", private=True)]


@pytest.fixture
def project_http(api):
    client = WholeRepository()
    service = GitHubProjectService(
        SqlGitHubProjectRepository(api.database),
        config(),
        client,
        api.app.state.ai_resources.client,
        api.clock,
    )
    api.app.state.github_projects = service
    api.app.state.project_knowledge = ProjectKnowledgeService(
        service,
        SqlProjectKnowledgeRepository(api.database),
        api.app.state.ai_resources.client,
        api.clock,
    )
    prefix = "/api/v1/projects/github"
    started = api.client.post(prefix + "/installations/start")
    assert started.status_code == 200
    completed = api.client.post(
        prefix + "/installations/complete",
        json={
            "installation_id": 11,
            "state": started.json()["state"],
            "code": "fixture-code",
        },
    )
    assert completed.status_code == 200, completed.text
    connection = api.client.post(
        prefix + "/repositories", json={"installation_id": 11, "repository_id": 22}
    )
    assert connection.status_code == 200, connection.text
    path = prefix + "/repositories/" + connection.json()["id"]
    try:
        yield SimpleNamespace(api=api, client=client, service=service, path=path)
    finally:
        client.close()


def ingest(project):
    response = project.api.client.post(project.path + "/ingest", json={"commit_sha": SHA})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    source = next(ref for ref in result["references"] if ref["path"] == "backend/identity.py")
    project.api.provider.text = json.dumps(
        {
            "schema_version": "project-answer-v1",
            "status": "answered",
            "sections": [
                {
                    "explanation": "The supplied authenticate function returns its subject.",
                    "citations": [
                        {
                            "reference_id": source["reference_id"],
                            "quote": "def authenticate(subject):",
                        }
                    ],
                }
            ],
        }
    )
    return result


def ask(project, **changes):
    return project.api.client.post(
        project.path + "/ask",
        json={
            "commit_sha": SHA,
            "question": "Teach me authentication in this project",
            **changes,
        },
    )


def test_owned_ingestion_readback_question_followup_and_privacy(project_http):
    project = project_http
    saved = ingest(project)
    assert saved["schema_version"] == "project-repository-v2"
    assert not saved["complete_repository"]
    assert {"frontend", "backend", "database", "migration", "documentation"} <= {
        ref["category"] for ref in saved["references"]
    }
    read = project.api.client.get(project.path + "/knowledge", params={"commit_sha": SHA})
    assert read.status_code == 200 and read.json() == saved
    answer = ask(project)
    assert answer.status_code == 200, answer.text
    payload = answer.json()
    assert payload["status"] == "answered" and payload["source"] == "ai"
    assert payload["sections"][0]["citations"][0]["path"] == "backend/identity.py"
    assert payload["sections"][0]["citations"][0]["line_start"] == 1
    assert not payload["can_complete_lesson"]
    followup = ask(
        project,
        question="Why does that function return its subject?",
        history=[
            {"role": "user", "text": "Teach me authentication in this project"},
            {"role": "assistant", "text": "The authenticate function returns its subject."},
        ],
    )
    assert followup.status_code == 200 and followup.json()["status"] == "answered"
    assert "fixture-user-token" not in answer.text + read.text
    assert "token_ciphertext" not in answer.text + read.text


def test_missing_auth_foreign_ownership_and_bad_origin_fail_closed(project_http):
    project = project_http
    ingest(project)
    saved = project.api.client.headers.pop("Authorization")
    assert ask(project).status_code == 401
    project.api.client.headers["Authorization"] = "Bearer " + project.api.signer.token(
        {
            "sub": str(uuid4()),
        }
    )
    foreign = ask(project)
    assert foreign.status_code == 404 and "fixture/architecture" not in foreign.text
    project.api.client.headers["Authorization"] = saved
    forbidden = project.api.client.post(
        project.path + "/ask",
        headers={"Origin": "https://untrusted.test"},
        json={"commit_sha": SHA, "question": "Explain auth"},
    )
    assert forbidden.status_code == 403
    assert project.api.provider.calls == []


def test_no_snapshot_and_invalid_request_do_not_call_ai(project_http):
    project = project_http
    assert ask(project).status_code == 404
    malformed = ask(project, source_ids=["a" * 64], question="private-attempt-should-not-echo")
    assert malformed.status_code == 422
    assert "private-attempt-should-not-echo" not in malformed.text
    assert project.api.provider.calls == []


@pytest.mark.parametrize("outcome", ["timeout", "unavailable", "invalid", "revoked"])
def test_provider_failures_invalid_citations_and_revocation_are_honest(project_http, outcome):
    project = project_http
    ingest(project)
    if outcome == "timeout":
        project.api.provider.error = AITransportError("timeout")
    elif outcome == "unavailable":
        project.api.provider.error = AITransportError("transport_error")
    elif outcome == "invalid":
        data = json.loads(project.api.provider.text)
        data["sections"][0]["citations"][0]["reference_id"] = "f" * 64
        project.api.provider.text = json.dumps(data)
    else:
        project.api.provider.callback = lambda: setattr(project.client, "revoked", True)
    reply = ask(project)
    assert reply.headers["cache-control"] == "no-store"
    if outcome == "revoked":
        assert reply.status_code == 503
    else:
        assert reply.status_code == 200 and reply.json()["status"] == "unavailable"
        assert reply.json()["sections"] == []


def test_disconnect_prevents_history_read_and_new_question_without_deleting_artifact(project_http):
    project = project_http
    ingest(project)
    disconnected = project.api.client.post(project.path + "/disconnect")
    assert disconnected.status_code == 200
    assert (
        project.api.client.get(project.path + "/knowledge", params={"commit_sha": SHA}).status_code
        == 404
    )
    assert ask(project).status_code == 404
    assert project.api.provider.calls == []


def test_question_route_uses_existing_rate_admission(project_http):
    project = project_http
    ingest(project)
    # GitHub HTTP admission allows 30 account requests per minute, independently
    # of AI provider quotas. Setup/ingestion already consumed four requests.
    for _ in range(30 - 4):
        assert (
            project.api.client.get(
                project.path + "/knowledge", params={"commit_sha": SHA}
            ).status_code
            == 200
        )
    limited = ask(project)
    assert limited.status_code == 429 and limited.headers["cache-control"] == "no-store"
    assert project.api.provider.calls == []


def test_parallel_question_is_rejected_while_first_provider_request_is_active(project_http):
    project = project_http
    ingest(project)
    entered, release = Event(), Event()

    def wait_for_release():
        entered.set()
        assert release.wait(5)

    project.api.provider.callback = wait_for_release
    with ThreadPoolExecutor(max_workers=1) as workers:
        first = workers.submit(ask, project)
        try:
            assert entered.wait(3)
            concurrent = ask(project)
            assert concurrent.status_code == 429
        finally:
            release.set()
        completed = first.result(timeout=5)
    assert completed.status_code == 200 and completed.json()["status"] == "answered"
    assert len(project.api.provider.calls) == 1
