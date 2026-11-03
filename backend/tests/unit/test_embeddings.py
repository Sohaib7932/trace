"""Embedding mechanics with explicitly artificial vectors and injected SDK HTTP only."""

import asyncio
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.ai.embeddings import BoundedEmbeddingClient, EmbeddingTransportError
from app.ai.providers import gemini_embeddings
from app.ai.providers.gemini_embeddings import (
    EMBEDDING_PATH,
    GeminiEmbeddingTransport,
    _EmbeddingWire,
)
from app.core.embedding_settings import EmbeddingSettings
from app.schemas.embeddings import (
    EmbeddingBatchResult,
    EmbeddingProfile,
    EmbeddingRequest,
    EmbeddingTransportResult,
    UnitEmbedding,
    normalized_vector,
    text_digest,
    vector_digest,
)


def basis(index=0):
    return tuple(1.0 if position == index else 0.0 for position in range(768))


@pytest.fixture(autouse=True)
def isolate_embedding_environment(monkeypatch):
    for name in os.environ:
        if name.startswith("TRACE_EMBEDDING_"):
            monkeypatch.delenv(name)


class ControlledEmbeddings:
    source = "test_fixture"

    def __init__(self, callback=None, error=None):
        self.calls = []
        self.closed = 0
        self.callback = callback
        self.error = error

    def embed(self, request):
        self.calls.append(request)
        if self.callback:
            return self.callback(request)
        if self.error:
            raise self.error
        return EmbeddingTransportResult(
            vectors=tuple(basis(i) for i, _ in enumerate(request.texts))
        )

    def close(self):
        self.closed += 1


def client(transport=None, **changes):
    return BoundedEmbeddingClient(
        EmbeddingSettings(_env_file=None, **dict(mode="mock") | changes),
        transport or ControlledEmbeddings(),
    )


def request(**changes):
    return EmbeddingRequest(
        **dict(
            purpose="document",
            texts=("Public documentation",),
            connect_timeout_seconds=0.01,
            response_timeout_seconds=3.0,
            max_response_bytes=4194304,
        )
        | changes
    )


@pytest.mark.parametrize(
    "change",
    [
        {"mode": "gemini_free"},
        {"model_id": "other"},
        {"dimensions": 384},
        {"paid_budget_microusd": 1},
        {"max_retries": 1},
        {"max_requests_per_process": 0},
        {"max_concurrent_requests": 5},
        {"max_response_bytes": 4194305},
        {"connect_timeout_seconds": 3, "response_timeout_seconds": 1},
    ],
)
def test_invalid_or_paid_embedding_configuration_is_rejected(change):
    with pytest.raises(ValidationError):
        EmbeddingSettings(_env_file=None, **change)


def test_disabled_default_and_wrong_transport_never_call_provider():
    provider = ControlledEmbeddings()
    disabled = BoundedEmbeddingClient(EmbeddingSettings(_env_file=None), provider)
    assert disabled.embed(("Public text",), "query").error_code == "disabled"
    assert provider.calls == []
    disabled.close()
    disabled.close()
    assert provider.closed == 1
    with pytest.raises(ValueError):
        BoundedEmbeddingClient(EmbeddingSettings(_env_file=None, mode="mock"))
    with pytest.raises(ValueError):
        BoundedEmbeddingClient(
            EmbeddingSettings(
                _env_file=None, mode="gemini_free", free_tier_unbilled_project_confirmed=True
            ),
            provider,
        )


def test_mock_receipts_preserve_exact_input_identity_without_claiming_semantics():
    provider = ControlledEmbeddings()
    bounded = client(provider)
    result = bounded.embed(("Public text", "Another passage"), "document")
    assert result.status == "success" and result.source == "test_fixture"
    assert result.input_sha256 == (text_digest("Public text"), text_digest("Another passage"))
    assert result.vectors[0].values == basis()
    assert result.input_tokens is None and result.observed_provider_revision is None
    usage = bounded.usage_snapshot()
    assert usage.attempts == 1 and usage.input_items == 2 and usage.missing_usage_count == 1
    assert usage.reserved_input_token_estimate > 0 and usage.observed_input_tokens == 0
    assert "Public text" not in repr(provider.calls[0])
    bounded.close()


@pytest.mark.parametrize(
    "values",
    [
        (),
        (1.0,) * 767,
        (1.0,) * 769,
        (0.0,) * 768,
        (float("nan"),) + (0.0,) * 767,
        (float("inf"),) + (0.0,) * 767,
        (True,) + (0.0,) * 767,
    ],
)
def test_invalid_vectors_cannot_be_normalized(values):
    with pytest.raises(ValueError):
        normalized_vector(values)


@pytest.mark.parametrize("scale", [1e-300, 1e300, -100.0, 0.5])
def test_normalization_handles_extreme_magnitudes_and_pins_float32_digest(scale):
    vector = UnitEmbedding.from_raw(tuple(scale if i < 2 else 0.0 for i in range(768)))
    assert abs(sum(value * value for value in vector.values) - 1.0) < 1e-5
    assert vector.vector_sha256 == vector_digest(vector.values)
    assert UnitEmbedding.model_validate_json(vector.model_dump_json()) == vector
    with pytest.raises(ValidationError):
        UnitEmbedding(values=vector.values, vector_sha256="0" * 64)


@pytest.mark.parametrize(
    "texts", [(), (" ",), ("x" * 2001,), ("\ud800",), ("a\x00b",), ("x",) * 101]
)
def test_invalid_input_is_rejected_before_admission(texts):
    provider = ControlledEmbeddings()
    bounded = client(provider)
    assert bounded.embed(texts, "query").error_code == "invalid_request"
    assert not provider.calls and bounded.usage_snapshot().attempts == 0
    bounded.close()


@pytest.mark.parametrize(
    "settings",
    [
        {"max_requests_per_process": 1},
        {"max_items_per_process": 1},
        {"max_reserved_input_tokens_per_process": 18},
    ],
)
def test_rpc_item_and_reserved_token_caps_are_independent(settings):
    bounded = client(**settings)
    assert bounded.embed(("a",), "query").status == "success"
    assert bounded.embed(("b",), "query").error_code == "budget_exhausted"
    assert bounded.usage_snapshot().attempts == 1
    bounded.close()


@pytest.mark.parametrize(
    "error,expected",
    [
        (EmbeddingTransportError("rate_limited"), "rate_limited"),
        (RuntimeError("private diagnostic canary"), "invalid_response"),
    ],
)
def test_failure_consumes_attempt_and_stays_sanitized_without_retry(error, expected):
    provider = ControlledEmbeddings(error=error)
    bounded = client(provider)
    result = bounded.embed(("Public question",), "query")
    assert result.error_code == expected and result.status == "unavailable"
    assert len(provider.calls) == 1 and bounded.usage_snapshot().missing_usage_count == 1
    assert "canary" not in result.model_dump_json()
    bounded.close()


def test_invalid_response_does_not_double_count_missing_usage():
    provider = ControlledEmbeddings(
        callback=lambda request: EmbeddingTransportResult(vectors=((0.0,) * 768,))
    )
    bounded = client(provider)
    assert bounded.embed(("Public question",), "query").error_code == "invalid_response"
    assert bounded.usage_snapshot().missing_usage_count == 1
    bounded.close()


def test_exact_vector_count_and_observed_usage_are_validated():
    provider = ControlledEmbeddings(
        callback=lambda request: EmbeddingTransportResult(
            vectors=(basis(),),
            input_tokens=123,
        )
    )
    bounded = client(provider)
    assert bounded.embed(("One", "Two"), "document").error_code == "invalid_response"
    assert bounded.usage_snapshot().observed_input_tokens == 123
    assert bounded.usage_snapshot().missing_usage_count == 0
    bounded.close()


def test_concurrency_and_shutdown_retain_active_lease_until_work_finishes():
    entered, release = Event(), Event()

    def blocked(request):
        entered.set()
        assert release.wait(5)
        return EmbeddingTransportResult(vectors=(basis(),))

    provider = ControlledEmbeddings(callback=blocked)
    bounded = client(provider, max_concurrent_requests=1)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(bounded.embed, ("One",), "query")
        assert entered.wait(5)
        assert bounded.embed(("Two",), "query").error_code == "concurrency_limit"
        bounded.close()
        assert provider.closed == 0 and bounded.usage_snapshot().in_flight == 1
        release.set()
        assert future.result(5).error_code == "disabled"
    assert provider.closed == 1 and bounded.usage_snapshot().in_flight == 0


def test_sdk_standard_batch_wire_task_profile_and_unknown_usage():
    calls = []

    def handler(wire):
        calls.append(wire)
        body = json.loads(wire.content)
        assert wire.url.path == EMBEDDING_PATH and not wire.url.query
        assert all(entry["taskType"] == "RETRIEVAL_DOCUMENT" for entry in body["requests"])
        assert all(entry["outputDimensionality"] == 768 for entry in body["requests"])
        return httpx.Response(
            200,
            json={
                "embeddings": [{"values": list(basis(i))} for i, _ in enumerate(body["requests"])],
                "usageMetadata": {"promptTokenCount": 999},
            },
        )

    provider = GeminiEmbeddingTransport(
        SecretStr("controlled-embedding-fixture"), http_transport=httpx.MockTransport(handler)
    )
    bounded = BoundedEmbeddingClient(
        EmbeddingSettings(
            _env_file=None, mode="gemini_free", free_tier_unbilled_project_confirmed=True
        ),
        provider,
    )
    try:
        result = bounded.embed(("First public article", "Second public article"), "document")
        assert result.status == "success" and result.source == "ai"
        assert result.input_tokens is None  # Installed SDK drops this Developer API metadata.
        assert len(calls) == 1 and result.vectors[1].values == basis(1)
        assert "controlled-embedding-fixture" not in result.model_dump_json()
    finally:
        bounded.close()
    assert not provider._thread.is_alive()


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "authentication_error"),
        (403, "authentication_error"),
        (429, "rate_limited"),
        (500, "transport_error"),
    ],
)
def test_sdk_errors_are_sanitized_and_never_retried(status, code):
    calls = []

    def handler(wire):
        calls.append(wire)
        return httpx.Response(status, json={"error": {"code": status, "message": "private-canary"}})

    provider = GeminiEmbeddingTransport(
        SecretStr("controlled-embedding-fixture"), http_transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(EmbeddingTransportError) as caught:
            provider.embed(request())
        assert caught.value.code == code and "canary" not in str(caught.value)
        assert len(calls) == 1
    finally:
        provider.close()


def test_sdk_deadline_cancels_actual_async_work_and_releases_resources():
    cancelled = Event()

    async def handler(wire):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    provider = GeminiEmbeddingTransport(
        SecretStr("controlled-embedding-fixture"), http_transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(EmbeddingTransportError) as caught:
            provider.embed(request(response_timeout_seconds=0.02))
        assert caught.value.code == "timeout" and cancelled.is_set()
    finally:
        provider.close()


@pytest.mark.parametrize(
    "payload",
    [{"embeddings": []}, {"embeddings": [{"values": None}]}, {"embeddings": [{"values": [1.0]}]}],
)
def test_malformed_sdk_vectors_cannot_escape_validation(payload):
    provider = GeminiEmbeddingTransport(
        SecretStr("controlled-embedding-fixture"),
        http_transport=httpx.MockTransport(lambda wire: httpx.Response(200, json=payload)),
    )
    bounded = BoundedEmbeddingClient(
        EmbeddingSettings(
            _env_file=None, mode="gemini_free", free_tier_unbilled_project_confirmed=True
        ),
        provider,
    )
    try:
        assert bounded.embed(("Public question",), "query").status == "unavailable"
    finally:
        bounded.close()


@pytest.mark.parametrize(
    "url",
    [
        "https://example.test/v1beta/models/gemini-embedding-001:batchEmbedContents",
        "http://generativelanguage.googleapis.com" + EMBEDDING_PATH,
        "https://generativelanguage.googleapis.com" + EMBEDDING_PATH + "?key=blocked",
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:asyncBatchEmbedContent",
    ],
)
def test_wire_rejects_unapproved_hosts_paid_batch_and_query_credentials(url):
    async def probe():
        wire = _EmbeddingWire(
            httpx.MockTransport(lambda request: pytest.fail("No network allowed")), 4194304
        )
        with pytest.raises(EmbeddingTransportError):
            await wire.handle_async_request(httpx.Request("POST", url, content=b"{}"))
        await wire.aclose()

    asyncio.run(probe())


def test_output_byte_limit_rejects_oversized_or_compressed_bodies():
    for response in (
        httpx.Response(200, content=b"x" * 5000),
        httpx.Response(
            200, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(b"unused")
        ),
    ):
        provider = GeminiEmbeddingTransport(
            SecretStr("controlled-embedding-fixture"),
            http_transport=httpx.MockTransport(lambda wire, response=response: response),
            max_response_bytes=4096,
        )
        try:
            with pytest.raises(EmbeddingTransportError) as caught:
                provider.embed(request(max_response_bytes=4096))
            assert caught.value.code in {"response_too_large", "invalid_response"}
        finally:
            provider.close()


def test_profile_and_results_forbid_forged_model_or_success_without_vectors():
    with pytest.raises(ValidationError):
        EmbeddingProfile(model_id="gemini-embedding-2")
    with pytest.raises(ValidationError):
        EmbeddingBatchResult(status="success", purpose="query", input_sha256=(), source="ai")
    with pytest.raises(EmbeddingTransportError):
        GeminiEmbeddingTransport.from_environment(EmbeddingSettings(_env_file=None))


def test_caller_deadline_only_tightens_provider_budget():
    provider = ControlledEmbeddings()
    bounded = client(provider)
    assert bounded.embed(("Public question",), "query", timeout_seconds=0.5).status == "success"
    assert 0 < provider.calls[-1].response_timeout_seconds <= 0.5
    assert provider.calls[-1].connect_timeout_seconds <= 0.5
    assert bounded.embed(("Public question",), "query", timeout_seconds=100.0).status == "success"
    assert 0 < provider.calls[-1].response_timeout_seconds <= 10.0
    assert (
        bounded.embed(("Public question",), "query", timeout_seconds=0.0).error_code
        == "invalid_request"
    )
    assert (
        bounded.embed(("Public question",), "query", timeout_seconds=float("nan")).error_code
        == "invalid_request"
    )
    bounded.close()


def test_actual_environment_strings_activate_only_explicit_unbilled_profile(monkeypatch):
    values = {
        "MODE": "gemini_free",
        "DIMENSIONS": "768",
        "PAID_BUDGET_MICROUSD": "0",
        "MAX_RETRIES": "0",
        "FREE_TIER_UNBILLED_PROJECT_CONFIRMED": "true",
        "MAX_REQUESTS_PER_PROCESS": "2",
        "MAX_ITEMS_PER_PROCESS": "113",
        "MAX_RESERVED_INPUT_TOKENS_PER_PROCESS": "16000",
        "MAX_CONCURRENT_REQUESTS": "1",
        "MAX_RESPONSE_BYTES": "4194304",
    }
    for name, value in values.items():
        monkeypatch.setenv("TRACE_EMBEDDING_" + name, value)
    settings = EmbeddingSettings(_env_file=None)
    assert settings.mode == "gemini_free" and settings.dimensions == 768
    assert settings.paid_budget_microusd == settings.max_retries == 0
    assert settings.max_requests_per_process == 2 and settings.max_items_per_process == 113
    assert settings.free_tier_unbilled_project_confirmed is True


@pytest.mark.parametrize(
    "name,number",
    [
        ("dimensions", 768),
        ("paid_budget_microusd", 0),
        ("max_retries", 0),
        ("max_requests_per_process", 2),
        ("max_items_per_process", 113),
        ("max_reserved_input_tokens_per_process", 16000),
        ("max_concurrent_requests", 1),
        ("max_response_bytes", 4194304),
    ],
)
@pytest.mark.parametrize("kind", ["boolean", "float", "float-string"])
def test_every_integer_configuration_rejects_boolean_and_float_coercion(name, number, kind):
    value = True if kind == "boolean" else float(number) if kind == "float" else str(number) + ".0"
    with pytest.raises(ValidationError):
        EmbeddingSettings(_env_file=None, **{name: value})


@pytest.mark.parametrize("value", [1, 0, "yes", "1", "on", " true "])
def test_free_tier_attestation_rejects_implicit_truthy_configuration(value):
    with pytest.raises(ValidationError):
        EmbeddingSettings(_env_file=None, free_tier_unbilled_project_confirmed=value)


def test_queue_delay_counts_toward_the_same_absolute_provider_deadline(monkeypatch):
    provider = GeminiEmbeddingTransport(
        SecretStr("controlled-embedding-fixture"),
        http_transport=httpx.MockTransport(
            lambda wire: pytest.fail("Expired work must not reach HTTP")
        ),
    )
    entered, release, clock_read = Event(), Event(), Event()
    now = [time.monotonic()]

    def clock():
        value = now[0]
        clock_read.set()
        return value

    def block_loop():
        entered.set()
        assert release.wait(5)

    provider._loop.call_soon_threadsafe(block_loop)
    assert entered.wait(5)
    monkeypatch.setattr(gemini_embeddings, "time", SimpleNamespace(monotonic=clock))
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(provider.embed, request(response_timeout_seconds=0.1))
            assert clock_read.wait(5)
            now[0] += 1.0
            release.set()
            with pytest.raises(EmbeddingTransportError) as caught:
                result.result(5)
            assert caught.value.code == "timeout"
    finally:
        release.set()
        provider.close()


def test_stopped_loop_and_submission_failure_are_sanitized(monkeypatch):
    provider = GeminiEmbeddingTransport(
        SecretStr("controlled-embedding-fixture"),
        http_transport=httpx.MockTransport(lambda wire: pytest.fail("No HTTP expected")),
    )

    def broken(*args, **kwargs):
        raise RuntimeError("private-submission-canary")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(gemini_embeddings.asyncio, "run_coroutine_threadsafe", broken)
            with pytest.raises(EmbeddingTransportError) as caught:
                provider.embed(request())
            assert caught.value.code == "transport_error"
            assert "canary" not in str(caught.value)
        provider._loop.call_soon_threadsafe(provider._loop.stop)
        provider._thread.join(5)
        with pytest.raises(EmbeddingTransportError) as caught:
            provider.embed(request())
        assert caught.value.code == "transport_error"
    finally:
        provider.close()


def test_event_loop_allocation_failure_never_exposes_diagnostics(monkeypatch):
    def broken():
        raise RuntimeError("private-loop-canary")

    monkeypatch.setattr(gemini_embeddings.asyncio, "new_event_loop", broken)
    with pytest.raises(EmbeddingTransportError) as caught:
        GeminiEmbeddingTransport(SecretStr("controlled-embedding-fixture"))
    assert caught.value.code == "configuration_missing" and "canary" not in str(caught.value)


def test_sdk_initialization_failure_disposes_owned_loop_and_http(monkeypatch):
    def broken(**kwargs):
        raise RuntimeError("private-sdk-canary")

    monkeypatch.setattr(gemini_embeddings.genai, "Client", broken)
    with pytest.raises(EmbeddingTransportError) as caught:
        GeminiEmbeddingTransport(
            SecretStr("controlled-embedding-fixture"),
            http_transport=httpx.MockTransport(lambda wire: None),
        )
    assert caught.value.code == "configuration_missing" and "canary" not in str(caught.value)
