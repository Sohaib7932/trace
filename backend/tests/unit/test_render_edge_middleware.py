"""Scheme-only Render boundary over an explicit trusted private perimeter, no network."""

import json
from unittest.mock import patch

import anyio
import pytest
from starlette.responses import JSONResponse
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.core.cors_errors import AllowedOriginErrorCORSMiddleware
from app.core.https_middleware import ProductionHTTPSMiddleware
from app.core.logging import create_logger
from app.core.render_edge_middleware import RawSocketCaptureMiddleware, RenderEdgeSchemeMiddleware
from scripts import run_production
from tests.unit.test_platform_resources import production_settings
from tests.unit.test_render_edge_settings import edge_settings

ORIGIN = "https://frontend.example.invalid"
HOST = b"fixture-trace.onrender.com"


def invoke(
    app,
    *,
    headers=None,
    scheme="http",
    peer="10.25.227.133",
    path="/api/v1/account/me",
    method="GET",
    query=b"",
    kind="http",
):
    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": kind,
        "method": method,
        "path": path,
        "query_string": query,
        "scheme": scheme,
        "client": (peer, 5000),
        "headers": headers
        if headers is not None
        else [(b"host", HOST), (b"x-forwarded-proto", b"https")],
        "state": {"request_id": "synthetic-render-probe"},
    }
    anyio.run(app, scope, receive, send)
    return messages


async def downstream(scope, receive, send):
    response = JSONResponse(
        {
            "scheme": scope["scheme"],
            "client": scope["client"],
            "authorization": [v.decode() for k, v in scope["headers"] if k == b"authorization"],
        }
    )
    await response(scope, receive, send)


def boundary(*, capture=False, logger=None):
    app = RenderEdgeSchemeMiddleware(
        ProductionHTTPSMiddleware(downstream), settings=edge_settings(), logger=logger
    )
    return RawSocketCaptureMiddleware(app) if capture else app


def test_scheme_only_accepts_managed_edge_proto_without_promoting_a_new_peer_to_client_trust():
    headers = [
        (b"host", HOST),
        (b"x-forwarded-proto", b"https"),
        (b"x-forwarded-for", b"127.0.0.1"),
        (b"forwarded", b"for=127.0.0.1;proto=https"),
        (b"authorization", b"Bearer synthetic-user-jwt"),
    ]
    messages = invoke(boundary(), headers=headers)
    assert messages[0]["status"] == 200
    assert json.loads(messages[1]["body"]) == {
        "scheme": "https",
        "client": ["10.25.227.133", 5000],
        "authorization": ["Bearer synthetic-user-jwt"],
    }


@pytest.mark.parametrize("scheme", ["http", "https"])
@pytest.mark.parametrize(
    "proto",
    [
        [],
        [b"http"],
        [b"HTTPS"],
        [b" https"],
        [b"https "],
        [b"https,http"],
        [b"https, https"],
        [b"https", b"https"],
        [b"http", b"https"],
        [b"https", b"http"],
        [b"wss"],
        [b""],
        [b"private-canary"],
    ],
)
def test_raw_proto_is_unambiguous_and_required_even_after_trusted_proxy_scheme_rewrite(
    scheme, proto
):
    headers = [(b"host", HOST)] + [(b"x-forwarded-proto", p) for p in proto]
    messages = invoke(boundary(), headers=headers, scheme=scheme)
    assert messages[0]["status"] == 400
    assert b"https_required" in messages[1]["body"] and b"private-canary" not in messages[1]["body"]
    assert (b"cache-control", b"no-store") in messages[0]["headers"]


@pytest.mark.parametrize(
    "hosts",
    [
        [],
        [b"evil.invalid"],
        [HOST + b":443"],
        [HOST, HOST],
        [b"fixture-trace.onrender.com.evil.invalid"],
        [b"Fixture-trace.onrender.com"],
    ],
)
def test_exact_singleton_host_pin_is_not_a_client_identity(hosts):
    messages = invoke(
        boundary(), headers=[(b"x-forwarded-proto", b"https")] + [(b"host", h) for h in hosts]
    )
    assert messages[0]["status"] == 400


def test_non_render_strict_guard_still_rejects_direct_forwarded_header_spoof():
    messages = invoke(ProductionHTTPSMiddleware(downstream), peer="198.51.100.20")
    assert messages[0]["status"] == 400


@pytest.mark.parametrize("peer", ["10.29.182.31", "10.25.227.133"])
def test_real_factory_captures_raw_socket_before_stock_unchanged_client_trust(monkeypatch, peer):
    monkeypatch.setenv("TRACE_TRUSTED_PROXY_IPS", "10.29.182.31/32")
    with (
        patch.object(run_production, "Settings", return_value=production_settings()),
        patch.object(run_production, "RenderEdgeSettings", return_value=edge_settings()),
        patch.object(run_production, "create_app", return_value=boundary()),
    ):
        app = run_production.create_render_production_app()
    messages = invoke(
        app,
        peer=peer,
        headers=[
            (b"host", HOST),
            (b"x-forwarded-proto", b"https"),
            (b"x-forwarded-for", b"203.0.113.7"),
        ],
    )
    data = json.loads(messages[1]["body"])
    assert messages[0]["status"] == 200 and data["scheme"] == "https"
    assert data["client"] == (["203.0.113.7", 0] if peer == "10.29.182.31" else [peer, 5000])


@pytest.mark.parametrize("peer", ["127.0.0.1", "::1"])
@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_genuine_captured_loopback_health_preserves_plain_http_exception(peer, method):
    messages = invoke(
        boundary(capture=True),
        peer=peer,
        path="/api/v1/health/live",
        method=method,
        headers=[(b"host", b"localhost")],
    )
    assert messages[0]["status"] == 200
    if method == "GET":
        data = json.loads(messages[1]["body"])
        assert data["scheme"] == "http" and data["client"] == [peer, 5000]


def test_missing_capture_cannot_turn_proxy_rewritten_loopback_into_health_proof():
    messages = invoke(boundary(), peer="127.0.0.1", path="/api/v1/health/live", headers=[])
    assert messages[0]["status"] == 400
    app = RawSocketCaptureMiddleware(
        ProxyHeadersMiddleware(boundary(), trusted_hosts="10.29.182.31/32")
    )
    messages = invoke(
        app,
        peer="10.29.182.31",
        path="/api/v1/health/live",
        headers=[(b"x-forwarded-for", b"127.0.0.1")],
    )
    assert messages[0]["status"] == 400


@pytest.mark.parametrize(
    "headers,query",
    [
        ([(b"authorization", b"Bearer canary")], b""),
        ([(b"cookie", b"canary")], b""),
        ([(b"content-length", b"1")], b""),
        ([(b"transfer-encoding", b"chunked")], b""),
        ([], b"probe=1"),
        ([(b"x-forwarded-proto", b"http")], b""),
    ],
)
def test_loopback_health_exception_stays_bare_and_does_not_override_bad_proto(headers, query):
    messages = invoke(
        boundary(capture=True),
        peer="127.0.0.1",
        path="/api/v1/health/live",
        headers=headers,
        query=query,
    )
    assert messages[0]["status"] == 400


@pytest.mark.parametrize(
    "reason,headers",
    [
        ("missing_proto", [(b"host", HOST)]),
        (
            "duplicate_proto",
            [(b"host", HOST), (b"x-forwarded-proto", b"https"), (b"x-forwarded-proto", b"https")],
        ),
        ("insecure_proto", [(b"host", HOST), (b"x-forwarded-proto", b"private-canary")]),
        ("invalid_host", [(b"host", b"private-canary"), (b"x-forwarded-proto", b"https")]),
    ],
)
def test_rejection_diagnostics_are_only_fixed_reason_codes(reason, headers, capsys):
    messages = invoke(boundary(logger=create_logger("WARNING")), headers=headers)
    logged = capsys.readouterr().err
    assert messages[0]["status"] == 400
    assert "render_transport_rejected" in logged and reason in logged
    assert "private-canary" not in logged and "10.25.227.133" not in logged


@pytest.mark.parametrize(
    "origin,allowed", [(ORIGIN, True), ("https://evil.invalid", False), (ORIGIN + "/", False)]
)
def test_cors_error_envelope_never_shortcircuits_failed_preflight(origin, allowed):
    app = AllowedOriginErrorCORSMiddleware(boundary(), allowed_origins=(ORIGIN,))
    messages = invoke(
        app,
        method="OPTIONS",
        headers=[
            (b"host", HOST),
            (b"origin", origin.encode()),
            (b"access-control-request-method", b"GET"),
        ],
    )
    assert messages[0]["status"] == 400
    headers = dict(messages[0]["headers"])
    assert (headers.get(b"access-control-allow-origin") == origin.encode()) is allowed
    assert b"access-control-allow-methods" not in headers
    if allowed:
        assert headers[b"access-control-allow-credentials"] == b"true"
        assert headers[b"access-control-expose-headers"] == b"X-Request-ID"
