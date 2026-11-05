"""Existing installations require real user proof before encrypted local binding."""

from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.ai.providers.github_app import GitHubAppClient
from app.core.errors import ApplicationError
from app.db.github_projects import SqlGitHubProjectRepository
from app.schemas.github_projects import InstallationComplete
from app.services.github_projects import GitHubProjectService
from tests.integration.test_github_projects import FakeAI, FakeGitHub, config
from tests.integration.test_github_projects import project as project  # noqa: F401
from tests.integration.test_live_ai_http import api as api  # noqa: F401


@pytest.mark.parametrize("installation", [None, 11])
def test_existing_installation_oauth_persists_only_encrypted_user_proof(project, installation):
    state = project.service.start(project.owner)
    fields = {"state": state.state, "code": "fixture-code"}
    if installation is not None:
        fields["installation_id"] = installation
    request = InstallationComplete.model_validate(fields)
    response = project.service.complete(project.owner, request)
    assert response.installation_id == 11 and response.status == "authorized"
    grant = project.service.repository.authorization_grant(project.owner, 11)
    assert grant is not None and grant.github_user_id == 321
    assert grant.repository_ids == (22,) and grant.token_ciphertext
    assert "fixture-user-token" not in grant.token_ciphertext
    assert "fixture-user-token" not in repr(grant)
    assert "fixture-user-token" not in response.model_dump_json()
    assert project.service.repositories(project.owner, 11)[0].repository_id == 22
    with pytest.raises(ApplicationError) as replay:
        project.service.complete(project.owner, request)
    assert replay.value.code == "github_state_invalid"
    assert project.client.exchanges == 1


@pytest.mark.parametrize(
    ("installations", "installation", "code", "status"),
    [
        ((), None, "github_installation_missing", 404),
        ((11, 12), None, "github_installation_selection_required", 409),
        ((12,), 11, "github_installation_inaccessible", 403),
        ((), 11, "github_installation_inaccessible", 403),
    ],
)
def test_missing_ambiguous_or_inaccessible_installations_never_bind(
    project, monkeypatch, installations, installation, code, status
):
    monkeypatch.setattr(project.client, "accessible_installations", lambda _: installations)
    monkeypatch.setattr(
        project.client, "validate_installation", lambda _: pytest.fail("unproved installation")
    )
    state = project.service.start(project.owner)
    request = InstallationComplete(
        installation_id=installation, state=state.state, code="fixture-code"
    )
    with pytest.raises(ApplicationError) as denied:
        project.service.complete(project.owner, request)
    assert (denied.value.code, denied.value.status_code) == (code, status)
    assert project.service.installations(project.owner) == ()
    with pytest.raises(ApplicationError) as replay:
        project.service.complete(project.owner, request)
    assert replay.value.code == "github_state_invalid" and project.client.exchanges == 1


def test_explicit_accessible_choice_resolves_multiple_installations(project, monkeypatch):
    monkeypatch.setattr(project.client, "accessible_installations", lambda _: (12, 11))
    state = project.service.start(project.owner)
    result = project.service.complete(
        project.owner,
        InstallationComplete(installation_id=11, state=state.state, code="fixture-code"),
    )
    assert result.installation_id == 11
    assert project.service.repository.authorization_grant(project.owner, 12) is None


@pytest.mark.parametrize("failure", ["foreign_owner", "expired_state", "tampered_state"])
def test_oauth_first_state_checks_precede_exchange_and_discovery(project, monkeypatch, failure):
    monkeypatch.setattr(
        project.client, "accessible_installations", lambda _: pytest.fail("state not authorized")
    )
    state = project.service.start(project.owner)
    owner, value = project.owner, state.state
    if failure == "foreign_owner":
        owner = uuid4()
    elif failure == "expired_state":
        project.clock.advance(601)
    else:
        value += "tampered"
    with pytest.raises(ApplicationError) as denied:
        project.service.complete(owner, InstallationComplete(state=value, code="fixture-code"))
    assert denied.value.code == "github_state_invalid"
    assert project.client.exchanges == 0
    assert project.service.installations(project.owner) == ()


@pytest.mark.parametrize("failure_stage", ["user_id", "accessible_installations"])
def test_failed_user_proof_consumes_state_without_persisting_a_grant(
    project, monkeypatch, failure_stage
):
    def unavailable(*_):
        raise ApplicationError("github_unavailable", "GitHub is unavailable.", 503)

    monkeypatch.setattr(project.client, failure_stage, unavailable)
    state = project.service.start(project.owner)
    request = InstallationComplete(state=state.state, code="fixture-code")
    with pytest.raises(ApplicationError) as denied:
        project.service.complete(project.owner, request)
    assert denied.value.code == "github_unavailable"
    assert project.service.installations(project.owner) == ()
    with pytest.raises(ApplicationError) as replay:
        project.service.complete(project.owner, request)
    assert replay.value.code == "github_state_invalid" and project.client.exchanges == 1


def test_user_proof_expiry_is_rechecked_after_installation_discovery(project, monkeypatch):
    discover = project.client.accessible_installations

    def delayed(token):
        project.clock.advance(301)
        return discover(token)

    monkeypatch.setattr(project.client, "accessible_installations", delayed)
    state = project.service.start(project.owner)
    with pytest.raises(ApplicationError) as expired:
        project.service.complete(
            project.owner, InstallationComplete(state=state.state, code="fixture-code")
        )
    assert expired.value.code == "github_reauthorization_required"
    assert project.service.installations(project.owner) == ()


@pytest.mark.parametrize("last_page", ["ambiguous", "provider_failure", "malformed"])
def test_all_discovery_pages_must_succeed_before_a_candidate_can_be_bound(
    project, monkeypatch, last_page
):
    calls = []

    def handler(request):
        calls.append((request.url.path, request.url.params.get("page")))
        if request.url.path == "/login/oauth/access_token":
            return httpx.Response(200, json={"access_token": "fixture-user-token"})
        if request.url.path == "/user":
            return httpx.Response(200, json={"id": 321})
        assert request.url.path == "/user/installations"
        if request.url.params["page"] == "1":
            return httpx.Response(
                200,
                json={
                    "total_count": 26,
                    "installations": [{"id": 11, "app_id": 123}]
                    + [{"id": identity, "app_id": 999} for identity in range(100, 124)],
                },
            )
        assert request.url.params["page"] == "2"
        if last_page == "provider_failure":
            return httpx.Response(503, text="fixture-private-provider-body")
        if last_page == "malformed":
            return httpx.Response(200, json={"total_count": 26, "installations": []})
        return httpx.Response(
            200, json={"total_count": 26, "installations": [{"id": 12, "app_id": 123}]}
        )

    client = GitHubAppClient(config(), transport=httpx.MockTransport(handler))
    monkeypatch.setattr(client, "validate_installation", lambda _: pytest.fail("partial choice"))
    service = GitHubProjectService(
        project.service.repository, config(), client, FakeAI(), project.clock
    )
    try:
        state = service.start(project.owner)
        with pytest.raises(ApplicationError) as denied:
            service.complete(
                project.owner, InstallationComplete(state=state.state, code="fixture-code")
            )
        assert denied.value.status_code == (409 if last_page == "ambiguous" else 503)
        assert "fixture-private-provider-body" not in str(denied.value)
        assert calls == [
            ("/login/oauth/access_token", None),
            ("/user", None),
            ("/user/installations", "1"),
            ("/user/installations", "2"),
        ]
        assert service.installations(project.owner) == ()
    finally:
        client.close()


@pytest.mark.parametrize("installation", [None, 11])
@pytest.mark.parametrize(
    "change",
    [
        {"repository_selection": "all"},
        {"suspended_at": "2026-11-04"},
        {"app_id": 999},
        {"permissions": {"contents": "write", "pull_requests": "read"}},
        {"permissions": {"contents": "read", "pull_requests": "read", "issues": "read"}},
    ],
)
def test_discovered_installation_still_requires_current_app_read_only_validation(
    project, monkeypatch, installation, change
):
    settings = config()
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/login/oauth/access_token":
            assert "Authorization" not in request.headers
            return httpx.Response(200, json={"access_token": "fixture-user-token"})
        if request.url.path == "/user":
            return httpx.Response(200, json={"id": 321})
        if request.url.path == "/user/installations":
            assert request.headers["Authorization"] == "Bearer fixture-user-token"
            return httpx.Response(
                200,
                json={
                    "total_count": 1,
                    "installations": [{"id": 11, "app_id": 123, "account": {"id": 999}}],
                },
            )
        assert request.url.path == "/app/installations/11"
        assert request.headers["Authorization"] == "Bearer fixture-app-token"
        return httpx.Response(
            200,
            json={
                "id": 11,
                "app_id": 123,
                "repository_selection": "selected",
                "permissions": {"contents": "read", "pull_requests": "read"},
                "suspended_at": None,
                **change,
            },
        )

    client = GitHubAppClient(settings, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(client, "app_token", lambda: SecretStr("fixture-app-token"))
    service = GitHubProjectService(
        project.service.repository, settings, client, FakeAI(), project.clock
    )
    try:
        state = service.start(project.owner)
        with pytest.raises(ApplicationError) as denied:
            service.complete(
                project.owner,
                InstallationComplete(
                    installation_id=installation, state=state.state, code="fixture-code"
                ),
            )
        assert denied.value.code == "github_permissions" and denied.value.status_code == 403
        assert calls == [
            "/login/oauth/access_token",
            "/user",
            "/user/installations",
            "/app/installations/11",
        ]
        assert service.installations(project.owner) == ()
    finally:
        client.close()


@pytest.mark.parametrize("value", [True, False, 0, -1, "11", 1.5])
def test_optional_installation_identity_preserves_strict_legacy_validation(value):
    with pytest.raises(ValidationError):
        InstallationComplete(installation_id=value, state="state", code="fixture-code")


def test_http_oauth_first_requires_account_origin_owner_and_single_use_state(api):
    client = FakeGitHub(config())
    service = GitHubProjectService(
        SqlGitHubProjectRepository(api.database), config(), client, FakeAI(), api.clock
    )
    api.app.state.github_projects = service
    prefix = "/api/v1/projects/github"
    try:
        started = api.client.post(prefix + "/installations/start")
        assert started.status_code == 200
        body = {"state": started.json()["state"], "code": "fixture-code"}
        authorization = api.client.headers.pop("Authorization")
        assert api.client.post(prefix + "/installations/complete", json=body).status_code == 401
        api.client.headers["Authorization"] = authorization
        assert (
            api.client.post(
                prefix + "/installations/complete",
                json=body,
                headers={"Origin": "https://evil.test"},
            ).status_code
            == 403
        )
        api.client.headers["Authorization"] = "Bearer " + api.signer.token({"sub": str(uuid4())})
        foreign = api.client.post(prefix + "/installations/complete", json=body)
        assert foreign.status_code == 409 and client.exchanges == 0
        api.client.headers["Authorization"] = authorization
        complete = api.client.post(prefix + "/installations/complete", json=body)
        assert complete.status_code == 200, complete.text
        assert complete.json()["installation_id"] == 11
        assert complete.headers["cache-control"] == "no-store"
        assert "fixture-user-token" not in complete.text
        replay = api.client.post(prefix + "/installations/complete", json=body)
        assert replay.status_code == 409 and client.exchanges == 1
    finally:
        client.close()
