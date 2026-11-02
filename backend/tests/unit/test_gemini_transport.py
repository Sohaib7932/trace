"""Real SDK wire contracts with an injected HTTP transport; no API credentials/network."""

import json

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.ai.client import AITransportError, BoundedAIClient
from app.ai.providers.gemini import MODEL, GeminiTransport, _PinnedTransport
from app.ai.resources import AIResourceError, AIResources
from app.core.ai_settings import AIClientSettings
from app.schemas.ai_client import TransportRequest


def config(**changes):
    return AIClientSettings(
        _env_file=None,
        **dict(
            mode="gemini_free",
            provider_id="gemini",
            generation_model_id=MODEL,
            conversational_model_id=MODEL,
            credential_env_var="GEMINI_API_KEY",
            free_tier_project_confirmed=True,
        )
        | changes,
    )


def request(**changes):
    return TransportRequest(
        **dict(
            capability="tutor",
            instructions="Trusted server instructions",
            data_json='{"question":"untrusted data"}',
            output_schema_json='{"type":"object","properties":{"text":{"type":"string"}},"required":["text"],"additionalProperties":false}',
            requested_model_id=MODEL,
            max_input_tokens=16384,
            max_output_tokens=512,
            max_response_bytes=4096,
            connect_timeout_seconds=1,
            response_timeout_seconds=3,
        )
        | changes
    )


def response(**changes):
    return (
        dict(
            candidates=[
                {
                    "content": {
                        "role": "model",
                        "parts": [{"text": '{"text":"Compare the schema."}'}],
                    },
                    "finishReason": "STOP",
                }
            ],
            modelVersion=MODEL,
            responseId="controlled-response-1",
            usageMetadata={
                "promptTokenCount": 30,
                "candidatesTokenCount": 12,
                "thoughtsTokenCount": 3,
            },
        )
        | changes
    )


def transport(handler):
    return GeminiTransport(
        SecretStr("controlled-sdk-fixture-not-a-real-key"),
        http_transport=httpx.MockTransport(handler),
    )


def test_sdk_wire_keeps_policy_data_and_schema_separate_and_closes():
    calls = []

    def handle(wire):
        calls.append(wire)
        assert (
            str(wire.url)
            == f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
        )
        body = json.loads(wire.content)
        assert body["systemInstruction"]["parts"][0]["text"] == "Trusted server instructions"
        assert json.loads(body["contents"][0]["parts"][0]["text"]) == {"question": "untrusted data"}
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert body["generationConfig"]["maxOutputTokens"] == 512
        assert not body.get("tools")
        assert wire.extensions["timeout"]["read"] == 3
        return httpx.Response(200, json=response())

    adapter = transport(handle)
    result = adapter.complete(request())
    assert result.text == '{"text":"Compare the schema."}'
    assert (result.input_tokens, result.output_tokens, result.cost_microusd) == (30, 15, 0)
    assert result.returned_model_id == MODEL
    assert len(calls) == 1
    adapter.close()
    adapter.close()
    with pytest.raises(AITransportError, match="^AI request failed$"):
        adapter.complete(request())


@pytest.mark.parametrize(
    "status,code",
    [
        (400, "invalid_request"),
        (401, "authentication_error"),
        (403, "authentication_error"),
        (404, "invalid_request"),
        (408, "timeout"),
        (429, "rate_limited"),
        (500, "transient_error"),
        (503, "transient_error"),
        (504, "timeout"),
    ],
)
def test_sdk_errors_are_sanitized_and_never_retried(status, code, capsys, caplog):
    calls = []

    def handle(wire):
        calls.append(wire)
        return httpx.Response(
            status,
            json={"error": {"code": status, "message": "private-provider-diagnostic-canary"}},
        )

    adapter = transport(handle)
    try:
        with pytest.raises(AITransportError) as exc:
            adapter.complete(request())
        assert exc.value.code == code
        assert len(calls) == 1
        assert (
            "private-provider-diagnostic"
            not in str(exc.value) + capsys.readouterr().err + caplog.text
        )
    finally:
        adapter.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"provider_id": "other"},
        {"generation_model_id": "other-model"},
        {"conversational_model_id": "other-model"},
        {"credential_env_var": "GOOGLE_API_KEY"},
        {"free_tier_project_confirmed": False},
        {"free_tier_project_confirmed": "yes"},
        {"free_tier_project_confirmed": 1},
        {"spend_limit_microusd": 1},
        {"max_cost_per_attempt_microusd": 1},
        {"max_retries": 1},
    ],
)
def test_free_mode_requires_exact_approved_configuration(changes):
    with pytest.raises(ValidationError):
        config(**changes)


def test_disabled_never_reads_key_and_live_missing_key_fails_safely(monkeypatch, tmp_path):
    monkeypatch.setattr("app.ai.providers.gemini._KEY_FILE", tmp_path / "missing.env")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "must-not-be-used")
    with pytest.raises(AIResourceError, match="^AI resources are unavailable\\.$"):
        AIResources.create(config())
    resources = AIResources.create(AIClientSettings(_env_file=None))
    resources.close()


def test_live_client_preserves_provenance_request_ceiling_and_disabled_capabilities():
    calls = []
    adapter = transport(lambda wire: calls.append(wire) or httpx.Response(200, json=response()))
    resources = AIResources.create(config(max_live_requests_per_process=1), lambda: adapter)

    def invoke(capability):
        return resources.client.complete(
            capability=capability, instructions="Policy", data={}, output_schema={"type": "object"}
        )

    try:
        for capability in ("feedback",):
            assert invoke(capability).error_code == "disabled"
        first = invoke("tutor")
        assert first.source == "ai" and first.provider_id == "gemini" and first.status == "success"
        assert invoke("tutor").error_code == "budget_exhausted"
        assert len(calls) == 1
    finally:
        resources.close()


def test_live_client_rejects_fixture_transport_without_calling_it():
    from app.ai.providers.mock_transport import MockAITransport

    fixture = MockAITransport([])
    result = BoundedAIClient(config(), fixture).complete(
        capability="tutor", instructions="Policy", data={}
    )
    assert result.error_code == "configuration_missing" and not fixture.calls


@pytest.mark.parametrize("finish,status", [("SAFETY", "refusal"), ("MAX_TOKENS", "truncated")])
def test_blocked_or_partial_output_is_not_a_success(finish, status):
    body = response(
        candidates=[{"content": {"parts": [{"text": "partial"}]}, "finishReason": finish}]
    )
    adapter = transport(lambda _: httpx.Response(200, json=body))
    try:
        result = adapter.complete(request())
        assert result.status == status and result.text is None
    finally:
        adapter.close()


def test_oversized_wire_response_is_rejected_before_sdk_parsing():
    adapter = transport(lambda _: httpx.Response(200, content=b"x" * 131073))
    try:
        with pytest.raises(AITransportError) as exc:
            adapter.complete(request())
        assert exc.value.code == "response_too_large"
    finally:
        adapter.close()


@pytest.mark.parametrize(
    "method,url",
    [
        ("GET", f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"),
        ("POST", f"http://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"),
        ("POST", f"https://unapproved.example.test/v1beta/models/{MODEL}:generateContent"),
        (
            "POST",
            f"https://generativelanguage.googleapis.com:444/v1beta/models/{MODEL}:generateContent",
        ),
        ("POST", "https://generativelanguage.googleapis.com/v1beta/models/other:generateContent"),
        (
            "POST",
            f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key=forbidden",
        ),
    ],
)
def test_wire_pin_rejects_unapproved_destinations_before_network(method, url):
    calls = []
    pinned = _PinnedTransport(httpx.MockTransport(lambda wire: calls.append(wire)))
    try:
        with pytest.raises(AITransportError) as exc:
            pinned.handle_request(httpx.Request(method, url))
        assert exc.value.code == "invalid_request"
        assert not calls
    finally:
        pinned.close()


def test_provider_redirect_is_never_followed():
    calls = []

    def redirect(wire):
        calls.append(wire)
        return httpx.Response(302, headers={"Location": "https://unapproved.example.test/private"})

    adapter = transport(redirect)
    try:
        with pytest.raises(AITransportError):
            adapter.complete(request())
        assert len(calls) == 1
    finally:
        adapter.close()


@pytest.mark.parametrize(
    "error,code", [(httpx.ReadTimeout, "timeout"), (httpx.ConnectError, "invalid_response")]
)
def test_network_failures_never_leak_diagnostics_or_retry(error, code, capsys, caplog):
    calls = []

    def fail(wire):
        calls.append(wire)
        raise error("private-network-diagnostic-canary")

    adapter = transport(fail)
    try:
        with pytest.raises(AITransportError) as exc:
            adapter.complete(request())
        assert exc.value.code == code
        assert len(calls) == 1
        assert (
            "private-network-diagnostic"
            not in str(exc.value) + capsys.readouterr().err + caplog.text
        )
    finally:
        adapter.close()


@pytest.mark.parametrize(
    "part",
    [
        {"functionCall": {"name": "read_private_file", "args": {}}},
        {"executableCode": {"language": "PYTHON", "code": "private-code-canary"}},
        {"codeExecutionResult": {"outcome": "OUTCOME_OK", "output": "private-output"}},
        {"inlineData": {"mimeType": "text/plain", "data": "Y2FuYXJ5"}},
        {"fileData": {"mimeType": "text/plain", "fileUri": "https://unapproved.example.test"}},
    ],
)
def test_non_text_provider_parts_cannot_enable_tools_or_executable_content(part):
    body = response(candidates=[{"content": {"parts": [part]}, "finishReason": "STOP"}])
    adapter = transport(lambda _: httpx.Response(200, json=body))
    try:
        with pytest.raises(AITransportError) as exc:
            adapter.complete(request())
        assert exc.value.code == "invalid_response"
    finally:
        adapter.close()


@pytest.mark.parametrize("candidates", [[], [{"content": {"parts": []}, "finishReason": "STOP"}]])
def test_missing_provider_content_is_never_a_success(candidates):
    adapter = transport(lambda _: httpx.Response(200, json=response(candidates=candidates)))
    try:
        if not candidates:
            assert adapter.complete(request()).status == "refusal"
        else:
            with pytest.raises(AITransportError) as exc:
                adapter.complete(request())
            assert exc.value.code == "invalid_response"
    finally:
        adapter.close()


def test_multiple_candidates_and_oversized_text_fail_closed():
    body = response()
    body["candidates"] *= 2
    adapter = transport(lambda _: httpx.Response(200, json=body))
    try:
        with pytest.raises(AITransportError) as exc:
            adapter.complete(request())
        assert exc.value.code == "invalid_response"
    finally:
        adapter.close()
    adapter = transport(lambda _: httpx.Response(200, json=response()))
    try:
        with pytest.raises(AITransportError) as exc:
            adapter.complete(request(max_response_bytes=8))
        assert exc.value.code == "response_too_large"
    finally:
        adapter.close()


def test_mismatched_returned_model_is_rejected_by_shared_client():
    adapter = transport(
        lambda _: httpx.Response(200, json=response(modelVersion="unapproved-model"))
    )
    client = BoundedAIClient(config(), adapter)
    try:
        result = client.complete(
            capability="tutor", instructions="Policy", data={}, output_schema={"type": "object"}
        )
        assert result.status == "transport_error" and result.error_code == "invalid_response"
        assert result.text is None
    finally:
        client.close()


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), True, "bad"])
def test_invalid_call_deadlines_never_reach_transport(timeout):
    calls = []
    adapter = transport(lambda wire: calls.append(wire) or httpx.Response(200, json=response()))
    client = BoundedAIClient(config(), adapter)
    try:
        result = client.complete(
            capability="tutor", instructions="Policy", data={}, timeout_seconds=timeout
        )
        assert result.error_code == "invalid_request"
        assert not calls
    finally:
        client.close()
