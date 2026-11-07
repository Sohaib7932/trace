import json
from collections import Counter

import httpx
import pytest

from scripts import check_deployed_transport as tool


def test_an_empty_probe_is_not_a_success():
    assert tool.Report(()).safe_summary()["passed"] is False


def healthy(request: httpx.Request) -> httpx.Response:
    headers = {
        "Access-Control-Allow-Origin": tool.FRONTEND_ORIGIN,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "GET, POST, DELETE",
        "Access-Control-Allow-Headers": "Authorization, Content-Type, X-Trace-Client",
    }
    if request.url.scheme == "http":
        return httpx.Response(307, headers={"Location": tool.BACKEND_ORIGIN + request.url.path})
    if request.headers.get("origin") != tool.FRONTEND_ORIGIN:
        return httpx.Response(400, text="Disallowed origin")
    if request.method == "OPTIONS":
        return httpx.Response(200, headers=headers, text="OK")
    if request.method == "HEAD":
        return httpx.Response(405, headers=headers)
    if request.url.path.endswith("/health/live"):
        return httpx.Response(200, headers=headers, json={"status": "alive"})
    if request.url.path.endswith("/health/ready"):
        return httpx.Response(200, headers=headers, json={"status": "ready"})
    return httpx.Response(401, headers=headers, json={"error": {"code": "unauthenticated"}})


def test_offline_plan_does_not_construct_client_or_load_credentials(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("No HTTP")

    monkeypatch.setattr(tool.httpx, "Client", forbidden)
    monkeypatch.setenv("GEMINI_API_KEY", "private-canary-not-a-key")
    assert tool.main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["network_requests"] == result["provider_calls"] == result["learner_writes"] == 0
    assert "private-canary" not in json.dumps(result)


def test_exact_read_only_probe_and_spoofed_header_controls():
    seen = []

    def handler(request):
        seen.append(request)
        return healthy(request)

    summary = tool.probe(transport=httpx.MockTransport(handler), clock=lambda: 0).safe_summary()
    assert summary["passed"] is True
    assert summary["attempted_requests"] == 68
    assert Counter(request.method for request in seen) == {"OPTIONS": 61, "GET": 6, "HEAD": 1}
    assert all(request.url.host == "trace-backend-1lio.onrender.com" for request in seen)
    assert all(
        "authorization" not in request.headers and "cookie" not in request.headers
        for request in seen
    )
    assert all(not request.content for request in seen)
    assert sum(request.url.scheme == "http" for request in seen) == 1
    assert summary["provider_calls"] == summary["learner_writes"] == 0


@pytest.mark.parametrize("mode,count", [("verify", 65), ("required", 67)])
def test_gateway_probe_requires_backend_workload_proof_and_rejects_direct_spoofs(mode, count):
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.scheme == "http":
            return httpx.Response(301, headers={"Location": tool.BACKEND_ORIGIN + request.url.path})
        if str(request.url).startswith(tool.BACKEND_ORIGIN):
            headers = {
                "Access-Control-Allow-Origin": tool.FRONTEND_ORIGIN,
                "Access-Control-Allow-Credentials": "true",
            }
            return httpx.Response(
                403, headers=headers, json={"error": {"code": "ingress_rejected"}}
            )
        headers = {"X-Trace-Ingress-Verified": "1", "Cache-Control": "no-store"}
        if request.url.path.endswith("/health/ready") and mode == "verify":
            return httpx.Response(
                503, headers=headers, json={"error": {"code": "dependency_unavailable"}}
            )
        response = healthy(request)
        response.headers.update(headers)
        return response

    summary = tool.probe(
        gateway=mode, transport=httpx.MockTransport(handler), clock=lambda: 0
    ).safe_summary()
    assert summary["passed"] is True
    assert summary["attempted_requests"] == len(seen) == count
    assert summary["workload_verified"] == 63
    assert all(
        "authorization" not in request.headers and "cookie" not in request.headers
        for request in seen
    )
    assert sum(request.method == "OPTIONS" for request in seen) == (mode == "required")

    def without_marker(request):
        response = handler(request)
        if request.url.path.endswith("/account/me"):
            response.headers.pop("x-trace-ingress-verified", None)
        return response

    rejected = tool.probe(
        gateway=mode, transport=httpx.MockTransport(without_marker), clock=lambda: 0
    ).safe_summary()
    assert rejected["passed"] is False
    assert rejected["workload_verified"] < 63


def test_one_https_failure_is_preserved_not_replaced_by_later_success():
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        if count == 3:
            return httpx.Response(400, json={"error": {"code": "https_required"}})
        return healthy(request)

    result = tool.probe(transport=httpx.MockTransport(handler), clock=lambda: 0).safe_summary()
    assert result["passed"] is False
    assert result["attempted_requests"] == 68
    assert result["error_categories"]["https_required"] == 1
    observations = result["observations"]
    assert observations[2]["http_status"] == 400 and not observations[2]["passed"]
    assert observations[3]["http_status"] == 200 and observations[3]["passed"]


@pytest.mark.parametrize(
    "failure", ["origin", "credentials", "method", "headers", "duplicate_origin", "error_200"]
)
def test_incomplete_or_ambiguous_preflight_cannot_pass(failure):
    def handler(request):
        response = healthy(request)
        if request.method == "OPTIONS" and request.headers["origin"] == tool.FRONTEND_ORIGIN:
            field = {
                "origin": "access-control-allow-origin",
                "credentials": "access-control-allow-credentials",
                "method": "access-control-allow-methods",
                "headers": "access-control-allow-headers",
            }.get(failure)
            if field:
                del response.headers[field]
            elif failure == "duplicate_origin":
                response.headers = httpx.Headers(
                    [
                        *response.headers.multi_items(),
                        ("access-control-allow-origin", tool.FRONTEND_ORIGIN),
                    ]
                )
            else:
                response = httpx.Response(
                    200,
                    headers=response.headers,
                    json={"error": {"code": "private-response-canary"}},
                )
        return response

    summary = tool.probe(transport=httpx.MockTransport(handler), clock=lambda: 0).safe_summary()
    assert not summary["passed"]
    assert not any(item["passed"] for item in summary["observations"][:60])
    assert "private-response-canary" not in json.dumps(summary)


@pytest.mark.parametrize("failure", ["timeout", "transport", "oversized", "redirect"])
def test_transport_failures_are_bounded_sanitized_and_not_retried(failure):
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        if failure == "timeout":
            raise httpx.ReadTimeout("private-key-canary", request=request)
        if failure == "transport":
            raise RuntimeError("private-cookie-canary")
        if failure == "oversized":
            return httpx.Response(200, content=b"private-body-canary" * 1000)
        return httpx.Response(302, headers={"Location": "https://untrusted.example/private-canary"})

    result = tool.probe(transport=httpx.MockTransport(handler), clock=lambda: 0).safe_summary()
    assert count == 68
    assert result["attempted_requests"] == 68 and not result["passed"]
    assert "private-" not in json.dumps(result)


def test_total_deadline_does_not_claim_unattempted_requests_passed():
    ticks = iter([0, *([121] * 68)])

    def forbidden(request):
        raise AssertionError("Deadline must stop network admission")

    summary = tool.probe(
        transport=httpx.MockTransport(forbidden), clock=lambda: next(ticks)
    ).safe_summary()
    assert not summary["passed"] and summary["attempted_requests"] == 0
    assert summary["error_categories"] == {"deadline": 68}


def test_cli_does_not_echo_accidentally_supplied_credentials(capsys):
    with pytest.raises(SystemExit) as stopped:
        tool.main(["--token", "private-token-canary"])
    assert stopped.value.code == 2
    captured = capsys.readouterr()
    assert "private-token-canary" not in captured.out + captured.err
    assert captured.err == "Invalid command arguments.\n"
