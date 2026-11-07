"""Only synthetic credentials/content and injected transports; never production HTTP."""

import json
from uuid import UUID

import httpx2
import pytest
from pydantic import SecretStr

from scripts.operator_http import (
    BACKEND_ORIGIN,
    FRONTEND_ORIGIN,
    MAX_RESPONSE_BYTES,
    OperatorHTTP,
    OperatorHTTPError,
)

TOKEN = "synthetic.header.signature"


def test_fixed_target_auth_origin_and_idempotency_are_exact():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx2.Response(200, json={"accepted": True})

    key = UUID("00000000-0000-0000-0000-000000000001")
    with OperatorHTTP(SecretStr(TOKEN), transport=httpx2.MockTransport(handler)) as client:
        assert client.request("GET", "/api/v1/account/me") == {"accepted": True}
        client.request("POST", "/api/v1/custom-lessons/requests", body={}, idempotency_key=key)
    assert str(seen[0].url) == BACKEND_ORIGIN + "/api/v1/account/me"
    assert seen[0].headers["authorization"] == "Bearer " + TOKEN
    assert seen[0].headers["origin"] == FRONTEND_ORIGIN
    assert seen[0].headers["x-trace-client"] == "learning-web"
    assert "idempotency-key" not in seen[0].headers
    assert seen[1].headers["idempotency-key"] == str(key)


def test_only_reviewed_import_has_an_extended_read_timeout_within_the_deadline():
    seen = []
    now = [0.0]

    def handler(request):
        seen.append(request.extensions["timeout"])
        return httpx2.Response(200, json={})

    with OperatorHTTP(
        SecretStr(TOKEN), clock=lambda: now[0], transport=httpx2.MockTransport(handler)
    ) as client:
        client.request("POST", "/api/v1/admin/knowledge/import-reviewed-corpus", body={})
        client.request("POST", "/api/v1/admin/knowledge/publications", body={})
        now[0] = 65.0
        client.request("POST", "/api/v1/admin/knowledge/import-reviewed-corpus", body={})

    assert seen == [
        {"connect": 10.0, "read": 40.0, "write": 10.0, "pool": 10.0},
        {"connect": 10.0, "read": 10.0, "write": 10.0, "pool": 10.0},
        {"connect": 10.0, "read": 25.0, "write": 10.0, "pool": 10.0},
    ]


@pytest.mark.parametrize("token", ["", " ", "key", "a.b.c\r\nX: canary", "a.b.c "])
def test_private_credential_shape_errors_never_echo(token):
    with pytest.raises(OperatorHTTPError) as error:
        OperatorHTTP(SecretStr(token))
    assert str(error.value) == "credential_unavailable"


def test_environment_token_only_and_missing_fail_closed(monkeypatch):
    monkeypatch.delenv("TRACE_OPERATOR_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("TRACE_OPERATOR_USE_GATEWAY", raising=False)
    with pytest.raises(OperatorHTTPError, match="credential_unavailable"):
        OperatorHTTP.from_environment()
    monkeypatch.setenv("TRACE_OPERATOR_ACCESS_TOKEN", TOKEN)
    with OperatorHTTP.from_environment() as client:
        assert TOKEN not in repr(client)


def test_gateway_route_preserves_user_auth_on_fixed_frontend_origin(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx2.Response(200, json={"accepted": True})

    class OfflineOperator(OperatorHTTP):
        def __init__(self, token, *, use_gateway=False):
            super().__init__(
                token, use_gateway=use_gateway, transport=httpx2.MockTransport(handler)
            )

    monkeypatch.setenv("TRACE_OPERATOR_ACCESS_TOKEN", TOKEN)
    monkeypatch.setenv("TRACE_OPERATOR_USE_GATEWAY", "1")
    with OfflineOperator.from_environment() as client:
        assert client.request("GET", "/api/v1/account/me") == {"accepted": True}
    assert str(seen[0].url) == FRONTEND_ORIGIN + "/api/v1/account/me"
    assert seen[0].headers["authorization"] == "Bearer " + TOKEN
    assert "x-trace-ingress-authorization" not in seen[0].headers
    monkeypatch.setenv("TRACE_OPERATOR_USE_GATEWAY", "https://unapproved.invalid")
    with pytest.raises(OperatorHTTPError, match="invalid_operation"):
        OfflineOperator.from_environment()
    assert len(seen) == 1


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "https://unapproved.invalid/api/v1/account/me"),
        ("GET", "//unapproved.invalid/api/v1/account/me"),
        ("GET", "/api/v1/account/me?token=canary"),
        ("GET", "/api/v1/account/../account/me"),
        ("GET", "/api/v1/admin/knowledge/receipts/00000000-0000-0000-0000-000000000001"),
        ("DELETE", "/api/v1/custom-lessons/requests"),
        ("get", "/api/v1/account/me"),
        ("POST", "/api/v1/support/ask"),
    ],
)
def test_unknown_targets_and_methods_never_dispatch(method, path):
    def handler(request):
        pytest.fail("Unexpected dispatch")

    with (
        OperatorHTTP(SecretStr(TOKEN), transport=httpx2.MockTransport(handler)) as client,
        pytest.raises(OperatorHTTPError, match="invalid_operation"),
    ):
        client.request(method, path)


@pytest.mark.parametrize(
    "status,code,unknown",
    [
        (302, "redirect_rejected", True),
        (401, "unauthenticated", False),
        (403, "forbidden", False),
        (404, "not_found", False),
        (409, "conflict", False),
        (422, "request_rejected", False),
        (429, "rate_limited", False),
        (500, "upstream_unavailable", True),
        (504, "upstream_unavailable", True),
    ],
)
def test_status_is_sanitized_and_no_post_is_retried(status, code, unknown):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx2.Response(
            status,
            text="private-response-canary " + TOKEN,
            headers={"location": "https://unapproved.invalid/"},
        )

    with (
        OperatorHTTP(SecretStr(TOKEN), transport=httpx2.MockTransport(handler)) as client,
        pytest.raises(OperatorHTTPError) as error,
    ):
        client.request("POST", "/api/v1/admin/knowledge/import-reviewed-corpus", body={})
    assert len(calls) == 1
    assert str(error.value) == code
    assert error.value.outcome_unknown is unknown


@pytest.mark.parametrize(
    "content,content_type,code",
    [
        (b'"private-response-canary"', "application/json", "invalid_response"),
        (b'{"x":1,"x":2}', "application/json", "invalid_response"),
        (b'{"x":NaN}', "application/json", "invalid_response"),
        (b"{broken-private-response-canary", "application/json", "invalid_response"),
        (b'{"x":1}', "text/html", "invalid_response"),
        (b"x" * (MAX_RESPONSE_BYTES + 1), "application/json", "response_too_large"),
    ],
)
def test_untrusted_response_bounds_and_json_are_fail_closed(content, content_type, code):
    transport = httpx2.MockTransport(
        lambda _: httpx2.Response(
            200,
            content=content,
            headers={"content-type": content_type},
        )
    )
    with (
        OperatorHTTP(SecretStr(TOKEN), transport=transport) as client,
        pytest.raises(OperatorHTTPError) as error,
    ):
        client.request("POST", "/api/v1/admin/knowledge/publications", body={})
    assert str(error.value) == code and error.value.outcome_unknown


def test_post_timeout_is_unknown_once_and_get_timeout_is_not_a_write():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx2.ReadTimeout("private-transport-canary " + TOKEN)

    with OperatorHTTP(SecretStr(TOKEN), transport=httpx2.MockTransport(handler)) as client:
        for method, path, unknown in [
            ("POST", "/api/v1/admin/knowledge/publications", True),
            ("GET", "/api/v1/account/me", False),
        ]:
            with pytest.raises(OperatorHTTPError) as error:
                client.request(method, path)
            assert str(error.value) == "transport_unavailable"
            assert error.value.outcome_unknown is unknown
    assert len(calls) == 2


def test_exhausted_budget_or_oversized_request_never_dispatches():
    now = [0.0]
    calls = []
    with OperatorHTTP(
        SecretStr(TOKEN),
        clock=lambda: now[0],
        deadline_seconds=1,
        transport=httpx2.MockTransport(lambda request: calls.append(request)),
    ) as client:
        with pytest.raises(OperatorHTTPError, match="invalid_operation"):
            client.request("POST", "/api/v1/custom-lessons/requests", body={"x": "x" * 17000})
        now[0] = 1.0
        assert client.remaining_seconds() == 0
        with pytest.raises(OperatorHTTPError, match="deadline_exceeded"):
            client.request("GET", "/api/v1/account/me")
    assert calls == []


def test_client_flags_disable_proxies_redirects_retries_and_keep_tls(monkeypatch):
    original = httpx2.Client
    seen = []

    def construct(**kwargs):
        seen.append(kwargs)
        return original(
            transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json={})),
            **{key: value for key, value in kwargs.items() if key != "transport"},
        )

    monkeypatch.setattr(httpx2, "Client", construct)
    with OperatorHTTP(SecretStr(TOKEN)):
        pass
    assert seen[0]["trust_env"] is False
    assert seen[0]["follow_redirects"] is False
    assert seen[0]["verify"] is True
    assert "retry" not in json.dumps({k: v for k, v in seen[0].items() if k != "headers"})


def test_request_count_and_stream_budget_are_enforced_without_replay():
    now, calls = [0.0], []

    def handler(request):
        calls.append(request)
        return httpx2.Response(200, json={})

    with OperatorHTTP(SecretStr(TOKEN), transport=httpx2.MockTransport(handler)) as client:
        for _ in range(32):
            assert client.request("GET", "/api/v1/account/me") == {}
        with pytest.raises(OperatorHTTPError, match="invalid_operation"):
            client.request("GET", "/api/v1/account/me")
    assert len(calls) == 32

    def late(request):
        now[0] = 2.0
        return httpx2.Response(200, json={})

    with (
        OperatorHTTP(
            SecretStr(TOKEN),
            clock=lambda: now[0],
            deadline_seconds=1,
            transport=httpx2.MockTransport(late),
        ) as client,
        pytest.raises(OperatorHTTPError) as error,
    ):
        client.request("POST", "/api/v1/admin/knowledge/publications", body={})
    assert error.value.code == "deadline_exceeded" and error.value.outcome_unknown


def test_compressed_response_is_refused_before_decompression():
    seen = []

    def handler(request):
        seen.append(request.headers["accept-encoding"])
        return httpx2.Response(
            200,
            headers={
                "content-type": "application/json",
                "content-encoding": "gzip",
            },
            stream=httpx2.ByteStream(b"synthetic-invalid-compressed-canary"),
        )

    with (
        OperatorHTTP(SecretStr(TOKEN), transport=httpx2.MockTransport(handler)) as client,
        pytest.raises(OperatorHTTPError) as error,
    ):
        client.request("GET", "/api/v1/account/me")
    assert error.value.code == "invalid_response" and not error.value.outcome_unknown
    assert seen == ["identity"]
