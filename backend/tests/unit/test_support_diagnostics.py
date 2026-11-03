"""Request-local pipeline observations identify failures without leaking payloads."""

import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest

from app.ai.client import AITransportError, BoundedAIClient
from app.ai.providers.bounded_support import BoundedSupportAssistant
from app.ai.providers.mock_transport import MockAITransport
from app.ai.support_diagnostics import (
    observe_support,
    record_support_runtime,
    support_diagnostic_fields,
    support_logger_observer,
    support_runtime_fields,
)
from app.core.ai_settings import AIClientSettings
from app.core.logging import JsonFormatter
from app.schemas.ai_client import TransportCompletion
from app.services.support import SupportService
from tests.unit.test_support import Client, document, knowledge, question


def capture(*, request_id=None):
    stream = io.StringIO()
    logger = logging.Logger("synthetic-support-diagnostics", level=logging.DEBUG)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    return support_logger_observer(logger, request_id=request_id), stream


def events(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def labels(stream):
    return [(event["support_stage"], event["support_reason"]) for event in events(stream)]


def test_unpublished_knowledge_identifies_pre_provider_failure_without_sensitive_metadata():
    observer, stream = capture()

    class Unpublished:
        available = False

        def snapshot(self):
            return SimpleNamespace(
                available=False,
                issues=(SimpleNamespace(code="missing_review", source_id="private-source"),),
            )

        def retrieve(self, checked):
            pytest.fail("Unavailable knowledge must not be retrieved")

    client = Client()
    result = SupportService(
        BoundedSupportAssistant(client, observer=observer), Unpublished(), observer=observer
    ).answer(question())
    assert result.status == "unavailable" and not client.calls
    assert labels(stream) == [("knowledge", "unavailable"), ("knowledge", "missing_review")]
    assert "private-source" not in stream.getvalue()
    assert all(event["support_passage_count"] is None for event in events(stream))


@pytest.mark.parametrize(
    "mode,transport,error_reason,invoked",
    [
        ("disabled", None, "disabled", False),
        ("mock", None, "configuration_missing", False),
        ("mock", MockAITransport([AITransportError("timeout")]), "timeout", True),
        ("mock", MockAITransport([AITransportError("rate_limited")]), "rate_limited", True),
    ],
)
def test_provider_invocation_is_distinct_from_disabled_configuration_or_provider_failure(
    mode, transport, error_reason, invoked
):
    observer, stream = capture()
    client = BoundedAIClient(AIClientSettings(_env_file=None, mode=mode), transport)
    try:
        result = SupportService(
            BoundedSupportAssistant(client, observer=observer), knowledge(), observer=observer
        ).answer(question())
        assert result.status == "unavailable" and not result.references
        assert ("provider", error_reason) in labels(stream)
        assert (("provider", "invoked") in labels(stream)) is invoked
        assert ("source_validation", "verified") not in labels(stream)
    finally:
        client.close()


def test_local_rate_limit_does_not_claim_another_transport_invocation():
    observer, stream = capture()
    transport = MockAITransport(
        [TransportCompletion(text='{"status":"answered","passage_ids":["fixture-email"]}')]
    )
    client = BoundedAIClient(
        AIClientSettings(_env_file=None, mode="mock", requests_per_minute=1), transport
    )
    service = SupportService(
        BoundedSupportAssistant(client, observer=observer), knowledge(), observer=observer
    )
    try:
        assert service.answer(question()).status == "answered"
        stream.seek(0)
        stream.truncate(0)
        assert service.answer(question()).status == "unavailable"
        assert len(transport.calls) == 1
        assert ("provider", "rate_limited") in labels(stream)
        assert ("provider", "invoked") not in labels(stream)
    finally:
        client.close()


@pytest.mark.parametrize(
    "text,reason",
    [
        ('{"status":"answered","passage_ids":["private-reference"]}', "invalid_citation"),
        ('{"answer":"private-answer-canary"}', "malformed_output"),
        ("private-invalid-json-canary", "malformed_output"),
    ],
)
def test_malformed_or_unretrieved_provider_selection_is_rejected_without_logging_output(
    text, reason
):
    observer, stream = capture()
    result = SupportService(
        BoundedSupportAssistant(Client(text), observer=observer), knowledge(), observer=observer
    ).answer(question())
    assert result.status == "unavailable" and not result.references
    assert ("provider", reason) in labels(stream)
    assert "private" not in stream.getvalue()


def test_changed_sources_after_provider_are_distinct_from_provider_failure():
    observer, stream = capture()
    corpus = knowledge()

    class MutableKnowledge:
        available = True

        def retrieve(self, checked):
            return corpus.retrieve(checked) if self.available else ()

    mutable = MutableKnowledge()

    class RevokingClient(Client):
        def complete(self, **kwargs):
            mutable.available = False
            return super().complete(**kwargs)

    result = SupportService(
        BoundedSupportAssistant(RevokingClient(), observer=observer), mutable, observer=observer
    ).answer(question())
    assert result.status == "unavailable" and not result.references
    assert ("provider", "success") in labels(stream)
    assert ("source_validation", "changed") in labels(stream)
    assert ("selection", "answered") not in labels(stream)


def test_success_and_unsupported_results_keep_public_contract_and_quote_out_of_diagnostics():
    for text, status in [
        ('{"status":"answered","passage_ids":["fixture-email"]}', "answered"),
        ('{"status":"unsupported","passage_ids":[]}', "unsupported"),
    ]:
        observer, stream = capture()
        result = SupportService(
            BoundedSupportAssistant(Client(text), observer=observer), knowledge(), observer=observer
        ).answer(question())
        assert result.status == status
        assert ("source_validation", "verified") in labels(stream)
        assert ("selection", status) in labels(stream)
        assert "fixture-email" not in stream.getvalue()
        assert question().question not in stream.getvalue()
        assert all(event["support_passage_count"] in {None, 0, 2} for event in events(stream))
        assert set(result.model_dump()) == {
            "status",
            "message",
            "references",
            "escalation",
            "source",
        }


@pytest.mark.parametrize(
    "stage,reason,count",
    [
        ("private-stage", "success", 1),
        ("provider", "private-reason", 1),
        ("knowledge", "success", 1),
        ("provider", "success", "private-count"),
        ("provider", "success", True),
        ("provider", "success", -1),
        ("provider", "success", 4),
        ({}, "success", 1),
    ],
)
def test_invalid_diagnostic_labels_are_rejected_and_cannot_be_injected_into_formatter(
    stage, reason, count
):
    with pytest.raises(ValueError, match="^Invalid support diagnostic$"):
        support_diagnostic_fields(stage, reason, count)
    stream = io.StringIO()
    logger = logging.Logger("synthetic-injection", level=logging.DEBUG)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.info(
        "support_pipeline",
        extra={
            "support_stage": stage,
            "support_reason": reason,
            "support_passage_count": count,
            "question": "private-question",
            "token": "private-token",
            "account_id": "private-id",
        },
    )
    assert set(json.loads(stream.getvalue())) == {"timestamp", "level", "event"}
    assert "private" not in stream.getvalue()


def test_observer_failures_never_change_delivery_and_do_not_affect_other_requests():
    def broken(*args):
        raise RuntimeError("private-observer-canary")

    transport = MockAITransport(
        [TransportCompletion(text='{"status":"answered","passage_ids":["fixture-email"]}')]
    )
    client = BoundedAIClient(AIClientSettings(_env_file=None, mode="mock"), transport)
    try:
        result = SupportService(
            BoundedSupportAssistant(client, observer=broken), knowledge(), observer=broken
        ).answer(question())
        assert result.status == "answered" and len(transport.calls) == 1
        observer, stream = capture()
        observe_support(observer, "knowledge", "available")
        assert labels(stream) == [("knowledge", "available")]
    finally:
        client.close()


def test_runtime_event_records_actual_injected_configuration_without_claiming_live_availability():
    stream = io.StringIO()
    logger = logging.Logger("synthetic-runtime", level=logging.DEBUG)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    record_support_runtime(
        logger,
        ai_mode="gemini_free",
        accounting_mode="durable",
        retrieval_mode="lexical",
        knowledge_backend="sql_archive",
        available=False,
        source_count=0,
    )
    event = json.loads(stream.getvalue())
    assert event["support_ai_mode"] == "gemini_free"
    assert event["support_accounting_mode"] == "durable"
    assert event["support_knowledge_backend"] == "sql_archive"
    assert event["support_knowledge_available"] is False
    assert event["support_source_count"] == 0
    assert not any("provider" in field or "secret" in field for field in event)


@pytest.mark.parametrize(
    "field,value",
    [
        ("ai_mode", "private"),
        ("accounting_mode", {}),
        ("retrieval_mode", "private"),
        ("knowledge_backend", "private"),
        ("available", "private"),
        ("source_count", True),
        ("source_count", 33),
    ],
)
def test_runtime_fields_reject_untrusted_metadata(field, value):
    values = dict(
        ai_mode="gemini_free",
        accounting_mode="memory",
        retrieval_mode="lexical",
        knowledge_backend="reviewed_file",
        available=True,
        source_count=9,
    )
    values[field] = value
    with pytest.raises(ValueError, match="^Invalid support runtime diagnostic$"):
        support_runtime_fields(**values)
    stream = io.StringIO()
    logger = logging.Logger("synthetic-runtime-injection", level=logging.DEBUG)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    names = {
        "ai_mode": "support_ai_mode",
        "accounting_mode": "support_accounting_mode",
        "retrieval_mode": "support_retrieval_mode",
        "knowledge_backend": "support_knowledge_backend",
        "available": "support_knowledge_available",
        "source_count": "support_source_count",
    }
    logger.info("support_runtime", extra={names[key]: val for key, val in values.items()})
    assert set(json.loads(stream.getvalue())) == {"timestamp", "level", "event"}


def test_concurrent_requests_share_client_without_sharing_diagnostic_state():
    barrier = Barrier(2)

    class ConcurrentTransport:
        source = "test_fixture"

        def complete(self, request):
            barrier.wait(timeout=5)
            return TransportCompletion(text='{"status":"answered","passage_ids":["fixture-email"]}')

    client = BoundedAIClient(AIClientSettings(_env_file=None, mode="mock"), ConcurrentTransport())
    first_id = "af7dac09-1892-40c7-9782-e3de55ae3419"
    second_id = "synthetic-request-2"
    first_observer, first_stream = capture(request_id=first_id)
    second_observer, second_stream = capture(request_id=second_id)
    one_passage = knowledge(
        document(
            passages=[
                {"passage_id": "fixture-email", "text": "Fixture: Open Sign in to use email login."}
            ]
        )
    )
    first = SupportService(
        BoundedSupportAssistant(client, observer=first_observer),
        knowledge(),
        observer=first_observer,
    )
    second = SupportService(
        BoundedSupportAssistant(client, observer=second_observer),
        one_passage,
        observer=second_observer,
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(service.answer, question()) for service in (first, second)]
            assert [future.result(timeout=10).status for future in futures] == [
                "answered",
                "answered",
            ]
        for stream, count in ((first_stream, 2), (second_stream, 1)):
            calls = [event for event in events(stream) if event["support_reason"] == "invoked"]
            assert len(calls) == 1 and calls[0]["support_passage_count"] == count
            assert all(event["support_passage_count"] in {None, count} for event in events(stream))
        assert all(event["request_id"] == first_id for event in events(first_stream))
        assert all(event["request_id"] == second_id for event in events(second_stream))
    finally:
        client.close()


def test_transport_callback_itself_cannot_interrupt_provider_execution():
    def broken():
        raise RuntimeError("private-observer-canary")

    transport = MockAITransport([TransportCompletion(text="Synthetic safe response")])
    client = BoundedAIClient(AIClientSettings(_env_file=None, mode="mock"), transport)
    try:
        completion = client.complete(
            capability="support",
            instructions="Use synthetic data.",
            data={},
            on_transport_attempt=broken,
        )
        assert completion.status == "success" and len(transport.calls) == 1
    finally:
        client.close()


@pytest.mark.parametrize("request_id", [None, "bad\nprivate-token", "x" * 65, {}, True])
def test_invalid_http_correlation_metadata_is_never_rendered(request_id):
    observer, stream = capture(request_id=request_id)
    observe_support(observer, "retrieval", "ready", 2)
    assert "request_id" not in events(stream)[0]
    assert "private-token" not in stream.getvalue()
