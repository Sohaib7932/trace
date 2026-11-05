"""User-proven installation discovery with synthetic, socket-free transports."""

import httpx
import pytest
from pydantic import SecretStr

from app.ai.providers.github_app import GitHubAppClient
from app.core.errors import ApplicationError
from tests.integration.test_github_projects import config


def installation(identity, *, app_id=123, account_type="User"):
    return {
        "id": identity,
        "app_id": app_id,
        "account": {"id": 999, "type": account_type},
    }


@pytest.mark.parametrize("account_type", ["User", "Organization"])
def test_discovery_uses_user_proof_without_requiring_installation_account_ownership(account_type):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        assert str(request.url) == "https://api.github.com/user/installations?per_page=25&page=1"
        assert request.headers["Authorization"] == "Bearer fixture-user-token"
        assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"
        assert request.headers["Accept"] == "application/vnd.github+json"
        return httpx.Response(
            200,
            json={
                "total_count": 2,
                "installations": [
                    installation(11, account_type=account_type),
                    installation(12, app_id=456),
                ],
            },
        )

    client = GitHubAppClient(config(), transport=httpx.MockTransport(handler))
    try:
        assert client.accessible_installations(SecretStr("fixture-user-token")) == (11,)
        assert len(calls) == 1
    finally:
        client.close()


@pytest.mark.parametrize("count", [0, 1, 25, 26, 100])
def test_discovery_numeric_pagination_has_four_page_ceiling_and_ignores_link_urls(count):
    calls = []

    def handler(request):
        assert request.url.host == "api.github.com"
        assert request.url.path == "/user/installations"
        assert request.url.params["per_page"] == "25"
        page = int(request.url.params["page"])
        calls.append(page)
        rows = [
            installation(identity)
            for identity in range((page - 1) * 25 + 1, min(page * 25, count) + 1)
        ]
        return httpx.Response(
            200,
            json={"total_count": count, "installations": rows},
            headers={"Link": '<https://evil.test/private>; rel="next"'},
        )

    client = GitHubAppClient(config(), transport=httpx.MockTransport(handler))
    try:
        assert client.accessible_installations(SecretStr("fixture-user-token")) == tuple(
            range(1, count + 1)
        )
        assert calls == list(range(1, max(1, (count + 24) // 25) + 1))
        assert len(calls) <= 4
    finally:
        client.close()


def test_other_apps_cannot_become_matching_installations():
    client = GitHubAppClient(
        config(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"total_count": 1, "installations": [installation(11, app_id=456)]}
            )
        ),
    )
    try:
        assert client.accessible_installations(SecretStr("fixture-user-token")) == ()
    finally:
        client.close()


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"total_count": 0},
        {"total_count": 0, "installations": None},
        {"total_count": 0, "installations": {}},
        {"installations": []},
        {"total_count": True, "installations": []},
        {"total_count": -1, "installations": []},
        {"total_count": 101, "installations": []},
        {"total_count": "1", "installations": []},
        {"total_count": 1.5, "installations": []},
        {"total_count": 1, "installations": [None]},
        {"total_count": 0, "installations": [installation(11)]},
        {"total_count": 2, "installations": [installation(11)]},
        {"total_count": 26, "installations": [installation(i) for i in range(1, 27)]},
        {"total_count": 2, "installations": [installation(11), installation(11)]},
        {
            "total_count": 2,
            "installations": [installation(11), installation(11, app_id=456)],
        },
    ],
)
def test_malformed_incomplete_or_duplicate_discovery_fails_closed(payload):
    client = GitHubAppClient(
        config(), transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )
    try:
        with pytest.raises(ApplicationError) as denied:
            client.accessible_installations(SecretStr("fixture-user-token"))
        assert denied.value.code == "github_unavailable"
        assert denied.value.status_code == 503
    finally:
        client.close()


@pytest.mark.parametrize("field", ["id", "app_id"])
@pytest.mark.parametrize("value", [None, True, False, 0, -1, 2**63, "11", 1.5])
def test_discovery_identifiers_require_bounded_exact_integers(field, value):
    row = {**installation(11), field: value}
    client = GitHubAppClient(
        config(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"total_count": 1, "installations": [row]})
        ),
    )
    try:
        with pytest.raises(ApplicationError):
            client.accessible_installations(SecretStr("fixture-user-token"))
    finally:
        client.close()


@pytest.mark.parametrize(
    "second_page",
    [
        {"total_count": 27, "installations": [installation(26)]},
        {"total_count": 26, "installations": []},
        {"total_count": 26, "installations": [installation(1)]},
        {"total_count": 26, "installations": [installation(1, app_id=456)]},
        {"total_count": 26, "installations": [installation(26), installation(27)]},
    ],
)
def test_discovery_rejects_inconsistent_totals_and_duplicate_ids_across_pages(second_page):
    calls = []

    def handler(request):
        page = int(request.url.params["page"])
        calls.append(page)
        if page == 1:
            payload = {
                "total_count": 26,
                "installations": [installation(i) for i in range(1, 26)],
            }
        else:
            payload = second_page
        return httpx.Response(200, json=payload)

    client = GitHubAppClient(config(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ApplicationError):
            client.accessible_installations(SecretStr("fixture-user-token"))
        assert calls == [1, 2]
    finally:
        client.close()


@pytest.mark.parametrize(
    ("status", "headers", "expected_status"),
    [
        (302, {"Location": "https://evil.test/private"}, 503),
        (401, {}, 503),
        (403, {}, 503),
        (403, {"X-RateLimit-Remaining": "0"}, 429),
        (403, {"Retry-After": "10"}, 429),
        (429, {}, 429),
        (500, {}, 503),
    ],
)
def test_discovery_provider_failures_do_not_disclose_credentials_or_response_bodies(
    status, headers, expected_status
):
    private_body = "fixture-private-provider-canary"
    private_token = "fixture-private-user-token"
    client = GitHubAppClient(
        config(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(status, text=private_body, headers=headers)
        ),
    )
    try:
        with pytest.raises(ApplicationError) as failed:
            client.accessible_installations(SecretStr(private_token))
        assert failed.value.status_code == expected_status
        assert private_body not in str(failed.value)
        assert private_token not in str(failed.value)
    finally:
        client.close()


def test_discovery_transport_timeout_is_sanitized():
    def handler(request):
        raise httpx.ReadTimeout("fixture-private-provider-canary", request=request)

    client = GitHubAppClient(config(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ApplicationError) as failed:
            client.accessible_installations(SecretStr("fixture-private-user-token"))
        assert failed.value.code == "github_unavailable"
        assert "fixture-private" not in str(failed.value)
    finally:
        client.close()


@pytest.mark.parametrize("body", [b"not-json", b"x" * 262145])
def test_discovery_malformed_or_oversized_wire_response_is_rejected(body):
    client = GitHubAppClient(
        config(), transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))
    )
    try:
        with pytest.raises(ApplicationError) as failed:
            client.accessible_installations(SecretStr("fixture-user-token"))
        assert failed.value.code == "github_unavailable"
    finally:
        client.close()
