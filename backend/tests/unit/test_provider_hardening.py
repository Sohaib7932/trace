"""Real SDK, fake HTTP only: accounting, cancellation and shared admission."""

import asyncio
import gzip
import json
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import asdict
from threading import Event
from unittest.mock import patch

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.ai.client import AITransportError, BoundedAIClient
from app.ai.providers.gemini import GeminiTransport
from app.schemas.ai_client import TransportCompletion
from tests.unit.test_gemini_transport import MODEL, config, request, response, transport


def invoke(client, capability="tutor", **changes):
    return client.complete(
        capability=capability,
        instructions="Trusted policy",
        data={},
        output_schema={"type": "object"},
        **changes,
    )


@pytest.mark.parametrize("finish", ["MAX_TOKENS", "SAFETY", "STOP", None])
def test_supplied_usage_and_model_survive_all_finish_outcomes(finish):
    body = response(
        candidates=[
            {
                "content": {"parts": [{"text": "private-rejected-output"}]},
                "finishReason": finish,
            }
        ]
    )
    adapter = transport(lambda _: httpx.Response(200, json=body))
    client = BoundedAIClient(config(), adapter)
    try:
        result = invoke(client)
        (record,) = client.usage_snapshot()
        assert (record.input_tokens, record.output_tokens, record.missing_usage_count) == (
            30,
            15,
            0,
        )
        assert result.returned_model_id == MODEL
        assert result.request_id == "controlled-response-1"
        if finish != "STOP":
            assert result.text is None and result.status in {"refusal", "truncated"}
    finally:
        client.close()


def test_no_candidates_preserves_usage_without_claiming_success():
    adapter = transport(lambda _: httpx.Response(200, json=response(candidates=[])))
    try:
        result = adapter.complete(request())
        assert result.status == "refusal" and result.text is None
        assert (result.input_tokens, result.output_tokens, result.returned_model_id) == (
            30,
            15,
            MODEL,
        )
    finally:
        adapter.close()


@pytest.mark.parametrize("kind", ["tool", "multiple", "size"])
def test_content_rejection_preserves_accounting_but_never_releases_text(kind):
    body = response()
    if kind == "tool":
        body["candidates"][0]["content"]["parts"] = [{"functionCall": {"name": "forbidden"}}]
    elif kind == "multiple":
        body["candidates"] *= 2
    else:
        body["candidates"][0]["content"]["parts"] = [{"text": "private-canary" * 2000}]
    client = BoundedAIClient(config(), transport(lambda _: httpx.Response(200, json=body)))
    try:
        result = invoke(client)
        (record,) = client.usage_snapshot()
        assert result.error_code in {"invalid_response", "response_too_large"}
        assert result.text is None and result.returned_model_id == MODEL
        assert (record.input_tokens, record.output_tokens, record.missing_usage_count) == (
            30,
            15,
            0,
        )
        assert "private-canary" not in result.model_dump_json()
    finally:
        client.close()


@pytest.mark.parametrize("metadata", [None, {}, {"promptTokenCount": 30}])
def test_missing_token_values_remain_explicitly_unknown(metadata):
    adapter = transport(lambda _: httpx.Response(200, json=response(usageMetadata=metadata)))
    try:
        result = adapter.complete(request())
        assert result.output_tokens is None
        assert result.input_tokens == (30 if metadata else None)
    finally:
        adapter.close()


@pytest.mark.parametrize("metadata", [None, "unapproved-model"])
def test_live_missing_or_mismatched_model_fails_closed_with_accounted_usage(metadata):
    client = BoundedAIClient(
        config(), transport(lambda _: httpx.Response(200, json=response(modelVersion=metadata)))
    )
    try:
        result = invoke(client)
        assert result.error_code == "invalid_response" and result.text is None
        assert client.usage_snapshot()[0].input_tokens == 30
    finally:
        client.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"max_output_tokens": 4097},
        {"response_timeout_seconds": 21, "total_timeout_seconds": 22},
        {"max_in_flight": 5},
        {"max_in_flight": True},
    ],
)
def test_effective_free_profile_rejects_unimplemented_limits(changes):
    with pytest.raises(ValidationError):
        config(**changes)


def test_global_admission_covers_capabilities_and_retains_lease_on_close():
    entered, release = Event(), Event()

    class Blocking:
        source = "ai"
        closed_count = 0

        def complete(self, _):
            entered.set()
            assert release.wait(5)
            return TransportCompletion(
                text="private-late-output",
                returned_model_id=MODEL,
                input_tokens=1,
                output_tokens=1,
                cost_microusd=0,
            )

        def close(self):
            self.closed_count += 1

    adapter = Blocking()
    client = BoundedAIClient(config(max_in_flight=1), adapter)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(invoke, client)
        try:
            assert entered.wait(5)
            assert invoke(client, "support").error_code == "rate_limited"
            assert invoke(client, "generation").error_code == "rate_limited"
            assert client.diagnostics_snapshot().in_flight == 1
            assert not client.wait_for_idle(0)
            client.close()
            assert adapter.closed_count == 0
        finally:
            release.set()
        assert future.result(timeout=5).error_code == "disabled"
    assert client.wait_for_idle(0) and adapter.closed_count == 1
    assert len(client.usage_snapshot()) == 1


def test_internal_diagnostics_exclude_subjects_requests_and_raw_errors():
    class Broken:
        source = "ai"

        def complete(self, _):
            raise RuntimeError("private-provider-error-canary")

    client = BoundedAIClient(config(), Broken())
    result = invoke(client, subject="private-subject-canary")
    assert result.error_code == "transport_error"
    snapshot = client.diagnostics_snapshot()
    encoded = json.dumps(asdict(snapshot))
    assert snapshot.availability == "configured" and snapshot.attempts == 1
    assert snapshot.capability_profile == "gemini-free-text-v1"
    assert not snapshot.live_availability_verified and not snapshot.absolute_deadline_enforced
    assert "private-" not in encoded and "GEMINI_API_KEY" not in encoded
    assert [(o.capability, o.outcome, o.count) for o in snapshot.outcomes] == [
        ("tutor", "transport_error", 1)
    ]
    client.close()
    assert client.diagnostics_snapshot().availability == "closed"


def test_async_dripping_body_is_canceled_at_deadline_and_shared_loop_remains_usable():
    closed = Event()
    calls = []

    class Drip(httpx.AsyncByteStream):
        async def __aiter__(self):
            while True:
                await asyncio.sleep(0.01)
                yield b" "

        async def aclose(self):
            closed.set()

    async def handle(wire):
        calls.append(wire)
        if len(calls) == 1:
            return httpx.Response(200, stream=Drip())
        return httpx.Response(200, json=response())

    adapter = transport(handle)
    thread = adapter._thread
    try:
        started = time.monotonic()
        with pytest.raises(AITransportError) as error:
            adapter.complete(request(response_timeout_seconds=0.1))
        assert error.value.code == "timeout" and closed.is_set()
        assert time.monotonic() - started < 3
        assert adapter.complete(request()).status == "success"
        assert adapter._thread is thread and thread.is_alive()
        assert len(calls) == 2
    finally:
        adapter.close()
        adapter.close()
    assert not thread.is_alive() and adapter._loop.is_closed()


def test_cancelled_attempt_retains_shared_permit_through_actual_stream_cleanup():
    cancelled, release = Event(), Event()

    class Waiting(httpx.AsyncByteStream):
        async def __aiter__(self):
            try:
                await asyncio.Future()
                yield b"unreachable"
            finally:
                cancelled.set()
                assert await asyncio.to_thread(release.wait, 5)

    async def handle(_):
        return httpx.Response(200, stream=Waiting())

    client = BoundedAIClient(config(max_in_flight=1), transport(handle))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(invoke, client, timeout_seconds=0.1)
        try:
            assert cancelled.wait(5)
            assert not future.done()
            assert invoke(client, "support").error_code == "rate_limited"
            assert client.diagnostics_snapshot().in_flight == 1
        finally:
            release.set()
        assert future.result(timeout=5).error_code == "timeout"
    assert client.diagnostics_snapshot().in_flight == 0
    client.close()


@pytest.mark.parametrize("failure", ["sdk", "thread"])
def test_bridge_constructor_failures_are_safe_and_close_allocated_loop(failure, capsys, caplog):
    loops = []
    original = asyncio.new_event_loop

    def make_loop():
        loop = original()
        loops.append(loop)
        return loop

    target = "genai.Client" if failure == "sdk" else "Thread.start"
    with (
        patch("app.ai.providers.gemini.asyncio.new_event_loop", side_effect=make_loop),
        patch(f"app.ai.providers.gemini.{target}", side_effect=RuntimeError("private-key-canary")),
        pytest.raises(AITransportError) as error,
    ):
        GeminiTransport(
            SecretStr("controlled-offline-fixture"),
            http_transport=httpx.MockTransport(lambda _: pytest.fail("Unexpected HTTP")),
        )
    assert error.value.code == "configuration_missing"
    assert loops and all(loop.is_closed() for loop in loops)
    assert "private-key" not in str(error.value) + caplog.text + capsys.readouterr().err


def test_bridge_rejects_a_stopped_loop_instead_of_queueing_forever():
    adapter = transport(lambda _: pytest.fail("Unexpected HTTP"))
    adapter._loop.call_soon_threadsafe(adapter._loop.stop)
    adapter._thread.join(5)
    assert not adapter._thread.is_alive()
    try:
        with pytest.raises(AITransportError) as error:
            adapter.complete(request())
        assert error.value.code == "transport_error"
    finally:
        adapter.close()
    assert adapter._loop.is_closed()


def test_expired_queued_attempt_does_not_invoke_sdk_or_http():
    adapter = transport(lambda _: pytest.fail("Expired request reached HTTP"))
    try:
        future = asyncio.run_coroutine_threadsafe(
            adapter._complete_with_deadline(request(), time.monotonic() - 1), adapter._loop
        )
        with pytest.raises(AITransportError) as error:
            future.result(timeout=5)
        assert error.value.code == "timeout"
    finally:
        adapter.close()


def test_compressed_response_cannot_expand_past_wire_byte_budget():
    compressed = gzip.compress(b" " * 200000)
    adapter = transport(
        lambda _: httpx.Response(
            200,
            headers={"Content-Encoding": "gzip"},
            stream=httpx.ByteStream(compressed),
        )
    )
    try:
        with pytest.raises(AITransportError) as error:
            adapter.complete(request())
        assert error.value.code == "invalid_response"
    finally:
        adapter.close()


def test_event_loop_creation_failure_is_sanitized_before_http_allocation(capsys, caplog):
    with (
        patch(
            "app.ai.providers.gemini.asyncio.new_event_loop",
            side_effect=RuntimeError("private-key"),
        ),
        patch("app.ai.providers.gemini.httpx.AsyncClient") as http,
        pytest.raises(AITransportError) as error,
    ):
        GeminiTransport(SecretStr("controlled-offline-fixture"))
    http.assert_not_called()
    assert error.value.code == "configuration_missing"
    assert "private-key" not in str(error.value) + caplog.text + capsys.readouterr().err


def test_usage_already_received_survives_late_deadline_delivery(monkeypatch):
    adapter = transport(lambda _: pytest.fail("No HTTP required for this late-result scenario"))

    async def received_response(_):
        return TransportCompletion(
            text="private-late-result",
            returned_model_id=MODEL,
            input_tokens=30,
            output_tokens=15,
            cost_microusd=0,
        )

    @asynccontextmanager
    async def expiry_delivered_at_exit(_):
        yield
        # Deterministic deadline delivery after the completion became available.
        raise TimeoutError

    monkeypatch.setattr(adapter, "_complete", received_response)
    client = BoundedAIClient(config(), adapter)
    try:
        with patch("app.ai.providers.gemini.asyncio.timeout_at", expiry_delivered_at_exit):
            result = invoke(client)
        assert result.error_code == "timeout" and result.text is None
        assert result.returned_model_id == MODEL
        (record,) = client.usage_snapshot()
        assert (record.input_tokens, record.output_tokens, record.missing_usage_count) == (
            30,
            15,
            0,
        )
    finally:
        client.close()
