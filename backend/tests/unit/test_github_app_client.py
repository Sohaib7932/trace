"""Pinned provider contract; synthetic credentials and HTTPX transports only."""

import base64
import gzip
import json

import h11
import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr

from app.ai.providers.github_app import GitHubAppClient
from app.core.errors import ApplicationError
from app.core.github_settings import GitHubSettings
from tests.integration.test_github_projects import config


@pytest.fixture
def signed_settings():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return config().model_copy(update={"private_key": SecretStr(pem)}), key


def test_installation_token_is_scoped_read_only_and_app_jwt_is_short_lived(signed_settings):
    settings, key = signed_settings
    captured = []

    def handler(request):
        captured.append(request)
        assert request.url.host == "api.github.com" and request.url.scheme == "https"
        claims = jwt.decode(
            request.headers["Authorization"].removeprefix("Bearer "),
            key.public_key(),
            algorithms=["RS256"],
        )
        assert claims["iss"] == "123" and claims["exp"] - claims["iat"] <= 330
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 11,
                    "app_id": 123,
                    "repository_selection": "selected",
                    "suspended_at": None,
                    "permissions": {
                        "contents": "read",
                        "metadata": "read",
                        "pull_requests": "read",
                    },
                },
            )
        body = json.loads(request.content)
        assert body["repository_ids"] == [22]
        assert body["permissions"] == {
            "contents": "read",
            "pull_requests": "read",
            "metadata": "read",
        }
        return httpx.Response(201, json={"token": "fixture-install-token"})

    client = GitHubAppClient(settings, transport=httpx.MockTransport(handler))
    try:
        result = client.repository_token(11, 22)
        assert result.get_secret_value() == "fixture-install-token" and len(captured) == 2
    finally:
        client.close()


def test_public_app_id_uses_documented_environment_name(monkeypatch):
    monkeypatch.setenv("TRACE_GITHUB_APP_ID", "123")
    assert GitHubSettings(_env_file=None).app_id == 123


@pytest.mark.parametrize(
    "change",
    [
        {"repository_selection": "all"},
        {"suspended_at": "2026-11-03"},
        {"app_id": 999},
        {"permissions": {"contents": "write", "pull_requests": "read"}},
        {"permissions": {"contents": "read", "pull_requests": "read", "issues": "read"}},
    ],
)
def test_excessive_or_suspended_installations_are_rejected(signed_settings, change):
    settings, _ = signed_settings
    data = {
        "id": 11,
        "app_id": 123,
        "repository_selection": "selected",
        "suspended_at": None,
        "permissions": {"contents": "read", "pull_requests": "read"},
        **change,
    }
    client = GitHubAppClient(
        settings, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data))
    )
    try:
        with pytest.raises(ApplicationError):
            client.validate_installation(11)
    finally:
        client.close()


def test_oauth_exchange_uses_fixed_host_callback_and_keeps_token_private():
    settings = config()

    def handler(request):
        assert str(request.url) == "https://github.com/login/oauth/access_token"
        assert request.method == "POST"
        assert "Authorization" not in request.headers
        assert request.headers["Accept"] == "application/json"
        assert request.headers["Content-Type"] == "application/json"
        body = json.loads(request.content)
        assert body["client_id"] == settings.client_id
        assert body["client_secret"] == settings.client_secret.get_secret_value()
        assert body["redirect_uri"] == settings.callback_url
        assert body["code"] == "fixture-code"
        return httpx.Response(200, json={"access_token": "fixture-user-token"})

    client = GitHubAppClient(settings, transport=httpx.MockTransport(handler))
    try:
        assert "fixture-user-token" not in repr(client.exchange("fixture-code"))
    finally:
        client.close()


@pytest.mark.parametrize("oauth", [True, False], ids=["oauth-exchange", "authenticated-rest"])
def test_real_httpx_requests_serialize_as_http1_with_correct_authentication(oauth):
    """MockTransport alone bypasses the HTTP/1 header validation used on the wire."""
    requests = []

    def handler(request):
        # Serialize the actual HTTPX-built request locally. No socket or external
        # credentials are involved, but an empty `Bearer ` fails h11 validation.
        wire = h11.Connection(h11.CLIENT).send(
            h11.Request(
                method=request.method.encode("ascii"),
                target=request.url.raw_path,
                headers=request.headers.raw,
            )
        )
        assert wire is not None
        requests.append(request)
        if oauth:
            assert "authorization" not in request.headers
            assert b"\r\nauthorization:" not in wire.lower()
            assert request.url.host == "github.com"
            assert request.headers["Content-Type"] == "application/json"
            return httpx.Response(200, json={"access_token": "fixture-user-token"})
        assert request.headers["Authorization"] == "Bearer fixture-user-token"
        assert b"\r\nauthorization: bearer fixture-user-token\r\n" in wire.lower()
        assert request.url.host == "api.github.com"
        return httpx.Response(200, json={"id": 321})

    client = GitHubAppClient(config(), transport=httpx.MockTransport(handler))
    try:
        if oauth:
            credential = client.exchange_authorization("fixture-code")
            assert credential.access_token.get_secret_value() == "fixture-user-token"
        else:
            assert client.user_id(SecretStr("fixture-user-token")) == 321
        assert len(requests) == 1
    finally:
        client.close()


@pytest.mark.parametrize("status", [200, 302, 400, 401, 403, 429, 500])
def test_unsuccessful_oauth_exchange_never_discloses_credentials_or_provider_errors(status):
    settings = config()
    canaries = (
        settings.client_secret.get_secret_value(),
        "fixture-private-code",
        "fixture-private-response-token",
        "fixture-private-provider-description",
    )

    def handler(request):
        assert "Authorization" not in request.headers
        return httpx.Response(
            status,
            json={
                "error": "incorrect_client_credentials",
                "error_description": " ".join(canaries),
            },
        )

    client = GitHubAppClient(settings, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ApplicationError) as failed:
            client.exchange_authorization("fixture-private-code")
        assert failed.value.status_code == (429 if status == 429 else 503)
        assert all(canary not in str(failed.value) for canary in canaries)
        assert "incorrect_client_credentials" not in str(failed.value)
    finally:
        client.close()


@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
def test_errors_and_redirects_never_expose_provider_body(status):
    client = GitHubAppClient(
        config(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                status, text="private-provider-canary", headers={"Location": "https://evil.test"}
            )
        ),
    )
    try:
        with pytest.raises(ApplicationError) as failed:
            client.user_id(SecretStr("fixture-user-token"))
        assert "private-provider-canary" not in str(failed.value)
    finally:
        client.close()


def test_disabled_mode_and_exhausted_deadline_never_call_transport():
    calls = []
    client = GitHubAppClient(
        GitHubSettings(_env_file=None),
        transport=httpx.MockTransport(lambda request: calls.append(request)),
    )
    try:
        with pytest.raises(ApplicationError):
            client.user_id(SecretStr("fixture-token"))
        assert not calls
    finally:
        client.close()
    client = GitHubAppClient(
        config(), transport=httpx.MockTransport(lambda request: calls.append(request))
    )
    try:
        with client.deadline(0), pytest.raises(ApplicationError):
            client.user_id(SecretStr("fixture-token"))
        assert not calls
    finally:
        client.close()


def test_large_wire_body_or_untrusted_repository_names_fail_closed():
    client = GitHubAppClient(
        config(),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 262145)),
    )
    try:
        with pytest.raises(ApplicationError):
            client.user_id(SecretStr("fixture-token"))
    finally:
        client.close()


def test_pinned_blob_read_never_dereferences_source_symlink():
    sha = "a" * 40
    calls = []

    def handler(request):
        calls.append(str(request.url))
        assert (
            str(request.url) == f"https://api.github.com/repos/fixture/repository/git/blobs/{sha}"
        )
        return httpx.Response(
            200,
            json={
                "sha": sha,
                "size": 4,
                "encoding": "base64",
                "content": base64.b64encode(b".env").decode(),
            },
        )

    client = GitHubAppClient(config(), transport=httpx.MockTransport(handler))
    try:
        assert (
            client.content(SecretStr("fixture"), "fixture/repository", "safe.py", sha, blob_sha=sha)
            == ".env"
        )
        assert len(calls) == 1
    finally:
        client.close()


@pytest.mark.parametrize(
    "data",
    [
        {"size": 32769, "encoding": "base64", "content": ""},
        {"size": 100, "encoding": "none", "content": ""},
        {"size": 1, "encoding": "base64", "content": "/w=="},
    ],
)
def test_large_unsupported_or_binary_blobs_are_explicit_omissions(data):
    sha = "a" * 40
    client = GitHubAppClient(
        config(),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"sha": sha, **data})),
    )
    try:
        with pytest.raises(ApplicationError) as failed:
            client.content(SecretStr("fixture"), "fixture/repository", "file.py", sha, blob_sha=sha)
        assert failed.value.code == "github_file_omitted"
    finally:
        client.close()


def test_compressed_wire_response_is_rejected_before_decompression():
    def handler(request):
        assert request.headers["Accept-Encoding"] == "identity"
        return httpx.Response(
            200,
            content=gzip.compress(b"x" * 1_000_000),
            headers={"Content-Encoding": "gzip"},
        )

    client = GitHubAppClient(config(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ApplicationError) as failed:
            client.user_id(SecretStr("fixture"))
        assert failed.value.code == "github_unavailable"
    finally:
        client.close()


@pytest.mark.parametrize("expiry", [None, 300, 100000])
def test_authorization_metadata_is_private_and_lifetime_is_bounded(expiry):
    payload = {"access_token": "fixture-user-token"}
    if expiry is not None:
        payload["expires_in"] = expiry
    client = GitHubAppClient(
        config(), transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )
    try:
        result = client.exchange_authorization("fixture-code")
        assert result.access_token.get_secret_value() == "fixture-user-token"
        assert result.expires_in == (8 * 3600 if expiry is None else min(expiry, 8 * 3600))
        assert "fixture-user-token" not in repr(result)
    finally:
        client.close()


@pytest.mark.parametrize("expiry", [0, -1, True, "300", 1.5])
def test_invalid_authorization_expiry_is_not_coerced(expiry):
    client = GitHubAppClient(
        config(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"access_token": "fixture-user-token", "expires_in": expiry}
            )
        ),
    )
    try:
        with pytest.raises(ApplicationError):
            client.exchange_authorization("fixture-code")
    finally:
        client.close()


def test_selected_repositories_use_bounded_numeric_pages_not_external_links():
    calls = []

    def handler(request):
        assert request.url.host == "api.github.com"
        calls.append(dict(request.url.params))
        page = int(request.url.params["page"])
        assert request.url.params["per_page"] == "25"
        rows = [
            {"id": identifier, "full_name": f"fixture/repo-{identifier}", "private": True}
            for identifier in (range(1, 26) if page == 1 else [26])
        ]
        return httpx.Response(
            200,
            json={"repositories": rows, "total_count": 26},
            headers={"Link": '<https://evil.test/read-secret>; rel="next"'},
        )

    client = GitHubAppClient(config(), transport=httpx.MockTransport(handler))
    try:
        result = client.accessible_repositories(SecretStr("fixture"), 11)
        assert len(result) == 26
        assert [call["page"] for call in calls] == ["1", "2"]
    finally:
        client.close()


@pytest.mark.parametrize(
    "payload",
    [
        {"total_count": 101, "repositories": []},
        {"total_count": True, "repositories": []},
        {"total_count": 30, "repositories": []},
        {
            "total_count": 2,
            "repositories": [
                {"id": 1, "full_name": "fixture/repo", "private": True},
                {"id": 1, "full_name": "fixture/repo", "private": True},
            ],
        },
    ],
)
def test_selected_repository_bounds_and_duplicate_identity_fail_closed(payload):
    client = GitHubAppClient(
        config(), transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )
    try:
        with pytest.raises(ApplicationError):
            client.accessible_repositories(SecretStr("fixture"), 11)
    finally:
        client.close()


def test_tree_commit_and_history_read_only_routes_pin_exact_sha_and_page():
    sha = "a" * 40
    calls = []

    def handler(request):
        assert request.method == "GET" and request.url.host == "api.github.com"
        calls.append(str(request.url))
        if "/git/trees/" in request.url.path:
            assert "recursive" not in request.url.params
            return httpx.Response(200, json={"sha": sha, "tree": [], "truncated": False})
        if request.url.path == "/repos/fixture/repo":
            return httpx.Response(200, json={"id": 22})
        if request.url.params.get("per_page") == "10":
            assert request.url.params["sha"] == sha and request.url.params["page"] == "2"
            return httpx.Response(200, json=[])
        assert request.url.params["page"] == "3" and request.url.params["per_page"] == "25"
        return httpx.Response(200, json={"sha": sha, "files": []})

    client = GitHubAppClient(config(), transport=httpx.MockTransport(handler))
    try:
        token = SecretStr("fixture")
        assert client.repository(token, "fixture/repo")["id"] == 22
        assert client.tree(token, "fixture/repo", sha)["truncated"] is False
        assert client.history_page(token, "fixture/repo", sha, 2) == []
        assert client.commit_page(token, "fixture/repo", sha, 3)["files"] == []
        before = len(calls)
        for bad in ("main", "../file", "a" * 39):
            with pytest.raises(ApplicationError):
                client.tree(token, "fixture/repo", bad)
        for bad in (0, 4, True):
            with pytest.raises(ApplicationError):
                client.history_page(token, "fixture/repo", sha, bad)
        with pytest.raises(ApplicationError):
            client.repository(token, "../repo")
        assert len(calls) == before
    finally:
        client.close()


@pytest.mark.parametrize(
    "status,headers",
    [
        (429, {}),
        (403, {"X-RateLimit-Remaining": "0"}),
        (403, {"Retry-After": "60"}),
    ],
)
def test_github_rate_limit_has_honest_sanitized_error_without_retry(status, headers):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers=headers, text="private-provider-detail")

    client = GitHubAppClient(config(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ApplicationError) as failure:
            client.repository(SecretStr("fixture"), "fixture/repo")
        assert failure.value.status_code == 429
        assert failure.value.code == "github_rate_limited"
        assert "private-provider-detail" not in str(failure.value)
        assert len(calls) == 1
    finally:
        client.close()


def installation_transport(token):
    def handler(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 11,
                    "app_id": 123,
                    "repository_selection": "selected",
                    "suspended_at": None,
                    "permissions": {
                        "contents": "read",
                        "metadata": "read",
                        "pull_requests": "read",
                    },
                },
            )
        assert request.url.path == "/app/installations/11/access_tokens"
        body = json.loads(request.content)
        assert body["repository_ids"] == [22]
        assert body["permissions"] == {
            "contents": "read",
            "metadata": "read",
            "pull_requests": "read",
        }
        assert "X-GitHub-Stateless-S2S-Token" not in request.headers
        return httpx.Response(201, json={"token": token})

    return httpx.MockTransport(handler)


@pytest.mark.parametrize(
    "token",
    [
        "fixture-install-token",
        "ghs_" + "a" * 170 + "." + "b" * 170 + "." + "c" * 174,
        "ghs_" + "a" * 678 + "." + "b" * 678 + "." + "c" * 686,
        "a" * 4096,
    ],
)
def test_installation_tokens_accept_legacy_and_current_opaque_stateless_formats(
    signed_settings, token
):
    settings, _ = signed_settings
    client = GitHubAppClient(settings, transport=installation_transport(token))
    try:
        result = client.repository_token(11, 22)
        assert result.get_secret_value() == token
        assert token not in repr(result)
        if token.startswith("ghs_"):
            assert token.count(".") == 2
            assert len(token) in {520, 2048}
    finally:
        client.close()


@pytest.mark.parametrize(
    "token",
    [
        "a" * 4097,
        "with space",
        "with\nnewline",
        "with\rreturn",
        "with\ttab",
        "with\x00null",
        "with\x7fdelete",
        "nonascii-é",
        "",
    ],
)
def test_installation_token_header_bounds_reject_controls_whitespace_and_non_ascii(
    signed_settings, token
):
    settings, _ = signed_settings
    client = GitHubAppClient(settings, transport=installation_transport(token))
    try:
        with pytest.raises(ApplicationError) as failure:
            client.repository_token(11, 22)
        assert failure.value.code == "github_unavailable"
        assert not token or token not in str(failure.value)
    finally:
        client.close()


@pytest.mark.parametrize(
    "full_name",
    [
        "fixture/ghp_" + "a" * 30,
        "fixture/AIza" + "a" * 30,
        "github_pat_" + "a" * 30 + "/repository",
    ],
)
def test_repository_choices_do_not_expose_credentials_in_metadata(full_name):
    client = GitHubAppClient(
        config(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "total_count": 1,
                    "repositories": [{"id": 22, "full_name": full_name, "private": True}],
                },
            )
        ),
    )
    try:
        with pytest.raises(ApplicationError) as failure:
            client.accessible_repositories(SecretStr("fixture"), 11)
        assert failure.value.code == "github_unavailable"
        assert full_name not in str(failure.value)
    finally:
        client.close()
    client = GitHubAppClient(
        config(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "repositories": [{"id": 22, "full_name": "../arbitrary-host", "private": True}]
                },
            )
        ),
    )
    try:
        with pytest.raises(ApplicationError):
            client.accessible_repositories(SecretStr("fixture-token"), 11)
    finally:
        client.close()
