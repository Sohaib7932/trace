"""Pinned provider contract; synthetic credentials and HTTPX transports only."""

import base64
import gzip
import json

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
        body = json.loads(request.content)
        assert body["redirect_uri"] == settings.callback_url
        assert body["code"] == "fixture-code"
        return httpx.Response(200, json={"access_token": "fixture-user-token"})

    client = GitHubAppClient(settings, transport=httpx.MockTransport(handler))
    try:
        assert "fixture-user-token" not in repr(client.exchange("fixture-code"))
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
