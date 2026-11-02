"""ASGI checks cover early errors, buffering and no-store independently of DBs."""

import asyncio
import json

import pytest

from app.core.feedback_middleware import FeedbackSecurityMiddleware
from app.core.feedback_settings import FeedbackSettings

PATH = "/api/v1/sessions/10000000-0000-4000-8000-000000000001/feedback"
ORIGIN = "http://localhost:3000"


async def invoke(middleware, *, body=b"{}", path=PATH, receive=None, send=None):
    captured = []
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": [(b"origin", ORIGIN.encode())],
        "state": {"request_id": "unit-request"},
    }

    async def default_receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def default_send(message):
        captured.append(message)

    await middleware(scope, receive or default_receive, send or default_send)
    if send is not None:
        return captured
    start = next(m for m in captured if m["type"] == "http.response.start")
    raw = b"".join(m.get("body", b"") for m in captured if m["type"] == "http.response.body")
    return start["status"], dict(start["headers"]), raw


def middleware(app, **changes):
    return FeedbackSecurityMiddleware(
        app, FeedbackSettings(_env_file=None, **changes), allowed_origins=(ORIGIN,)
    )


@pytest.mark.parametrize(
    "status", [200, 201, 401, 403, 404, 405, 409, 413, 422, 429, 500, 503, 504]
)
def test_all_feedback_statuses_are_no_store_and_errors_are_sanitized(status):
    async def downstream(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"cache-control", b"public")],
            }
        )
        await send(
            {"type": "http.response.body", "body": b'{"private":"secret-submission-canary"}'}
        )

    actual, headers, body = asyncio.run(invoke(middleware(downstream)))
    assert actual == status
    assert headers[b"cache-control"] == b"no-store"
    assert headers[b"access-control-allow-origin"] == ORIGIN.encode()
    assert headers[b"access-control-allow-credentials"] == b"true"
    assert headers[b"access-control-expose-headers"] == b"X-Request-ID"
    if status >= 400:
        assert b"secret-submission-canary" not in body
        assert json.loads(body)["error"]["details"] == []
        assert json.loads(body)["error"]["request_id"] == "unit-request"


def test_body_limit_precedes_downstream_work_and_sanitizes_output():
    async def forbidden(scope, receive, send):
        pytest.fail("Oversized input reached authentication/service")

    status, headers, body = asyncio.run(
        invoke(middleware(forbidden, max_request_bytes=2), body=b"large")
    )
    assert status == 413 and headers[b"cache-control"] == b"no-store"
    assert json.loads(body)["error"]["code"] == "request_too_large"


def test_read_deadline_and_service_deadline_return_sanitized_no_store_timeout():
    async def forever_receive():
        await asyncio.Event().wait()

    async def forever_service(scope, receive, send):
        await asyncio.Event().wait()

    for receive in (forever_receive, None):
        status, headers, body = asyncio.run(
            invoke(
                middleware(
                    forever_service, request_timeout_seconds=0.01, provider_timeout_seconds=0.005
                ),
                receive=receive,
            )
        )
        assert status == 504 and headers[b"cache-control"] == b"no-store"
        assert json.loads(body)["error"]["code"] == "request_timeout"


def test_ingress_rate_rejects_before_auth_and_has_cors_on_own_error():
    count = []

    async def downstream(scope, receive, send):
        count.append(True)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    protected = middleware(downstream, ingress_requests_per_minute=1)

    async def scenario():
        assert (await invoke(protected))[0] == 200
        return await invoke(protected)

    status, headers, body = asyncio.run(scenario())
    assert len(count) == 1 and status == 429
    assert headers[b"cache-control"] == b"no-store"
    assert headers[b"access-control-allow-origin"] == ORIGIN.encode()
    assert json.loads(body)["error"]["code"] == "feedback_rate_limited"


def test_ingress_concurrency_prevents_second_authentication_call():
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def downstream(scope, receive, send):
            entered.set()
            await release.wait()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        protected = middleware(downstream, max_ingress_in_flight=1)
        first = asyncio.create_task(invoke(protected))
        await asyncio.wait_for(entered.wait(), 2)
        try:
            assert (await invoke(protected))[0] == 429
        finally:
            release.set()
            assert (await first)[0] == 200
        assert (await invoke(protected))[0] == 200

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["exception", "oversized", "missing_start"])
def test_unexpected_or_invalid_output_cannot_leak_private_content(kind):
    async def downstream(scope, receive, send):
        if kind == "exception":
            raise RuntimeError("private-runtime-secret")
        if kind != "missing_start":
            await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"private-runtime-secret" * 10})

    status, headers, body = asyncio.run(invoke(middleware(downstream, max_response_bytes=2)))
    assert status == 500 and headers[b"cache-control"] == b"no-store"
    assert b"private-runtime-secret" not in body


def test_send_backpressure_never_emits_second_response_start():
    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    async def scenario():
        starts = []

        async def blocked_send(message):
            if message["type"] == "http.response.start":
                starts.append(message)
                await asyncio.Event().wait()

        with pytest.raises(TimeoutError):
            await invoke(
                middleware(
                    downstream, request_timeout_seconds=0.01, provider_timeout_seconds=0.005
                ),
                send=blocked_send,
            )
        assert len(starts) == 1

    asyncio.run(scenario())


def test_unrelated_api_is_not_buffered_or_rewritten():
    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"legacy response"})

    status, headers, body = asyncio.run(
        invoke(middleware(downstream), path="/api/v1/lessons/notes")
    )
    assert status == 200 and b"cache-control" not in headers and body == b"legacy response"
