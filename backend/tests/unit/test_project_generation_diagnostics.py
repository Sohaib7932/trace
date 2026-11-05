"""Safe request-local stage labels through the real SDK and fake HTTP only."""

import asyncio
import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import httpx
import pytest

from app.ai.client import AITransportError
from app.ai.project_generation_diagnostics import (
    ProjectGenerationDiagnostics,
    notify_project_provider_request,
    notify_project_provider_response,
    project_generation_fields,
    project_generation_logger_observer,
)
from app.core.logging import JsonFormatter
from app.schemas.github_projects import ProjectLearningContent
from tests.unit.test_gemini_transport import request, response, transport


def capture():
    events = []
    return ProjectGenerationDiagnostics(lambda *values: events.append(values)), events


def labels(events):
    return [(event[1], event[2], event[3], event[4]) for event in events]


def test_attempt_ids_are_new_server_uuid4_values_and_no_context_leaks_after_scope():
    first, events = capture()
    second, other = capture()
    first.record("generation", "started")
    second.record("generation", "started")
    assert events[0][0] != other[0][0]
    assert all(UUID(value[0]).version == 4 for value in events + other)
    notify_project_provider_request()
    notify_project_provider_response(200)
    assert len(events) == len(other) == 1
    with first.provider_scope():
        notify_project_provider_request()
        notify_project_provider_response(200)
    notify_project_provider_request()
    assert labels(events) == [
        ("generation", "started", False, False),
        ("provider_request", "initiated", True, False),
        ("provider_request", "response_received", True, True),
        ("provider_http", "success", True, True),
    ]


@pytest.mark.parametrize(
    "status,reason",
    [
        (200, "success"),
        (299, "success"),
        (401, "authentication"),
        (403, "authentication"),
        (429, "quota"),
        (408, "timeout"),
        (504, "timeout"),
        (500, "transport"),
        (503, "transport"),
        (400, "provider_rejection"),
        (404, "provider_rejection"),
        (302, "provider_rejection"),
    ],
)
def test_http_outcomes_are_categorical_and_never_contain_status_numbers(status, reason):
    diagnostic, events = capture()
    with diagnostic.provider_scope():
        notify_project_provider_request()
        notify_project_provider_response(status)
    assert events[-1][1:] == ("provider_http", reason, True, True)
    assert all(type(value) in {str, bool} for event in events for value in event)


@pytest.mark.parametrize(
    "changes",
    [
        {"attempt_id": "private-token"},
        {"attempt_id": str(uuid4()).upper()},
        {"attempt_id": "00000000-0000-1000-8000-000000000001"},
        {"attempt_id": UUID(int=0)},
        {"stage": "private-source"},
        {"reason": "private-provider-message"},
        {"stage": "schema_validation", "reason": "success"},
        {"initiated": 1},
        {"response_received": 0},
        {"response_received": True},
        {"stage": "provider_http", "reason": "success"},
        {"stage": "provider_request", "reason": "initiated"},
        {
            "stage": "provider_request",
            "reason": "initiated",
            "initiated": True,
            "response_received": True,
        },
        {"stage": "provider_request", "reason": "response_received", "initiated": True},
    ],
)
def test_metadata_is_strict_and_rejects_incoherent_or_sensitive_values(changes):
    values = (
        dict(
            attempt_id=str(uuid4()),
            stage="provider",
            reason="success",
            initiated=False,
            response_received=False,
        )
        | changes
    )
    with pytest.raises(ValueError, match="^Invalid project generation diagnostic$"):
        project_generation_fields(**values)


def test_observer_failures_and_invalid_labels_cannot_change_execution():
    def broken(*values):
        raise RuntimeError("private-observer-canary")

    diagnostic = ProjectGenerationDiagnostics(broken)
    diagnostic.record("generation", "started")
    diagnostic.record("private-stage", "private-reason")
    with diagnostic.provider_scope():
        notify_project_provider_request()
        notify_project_provider_response(200)
    diagnostic.record("release", "passed")


def test_logger_has_only_fresh_attempt_correlation_and_categorical_fields():
    stream = io.StringIO()
    logger = logging.Logger("synthetic-project-diagnostics", level=logging.DEBUG)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    diagnostic = ProjectGenerationDiagnostics(project_generation_logger_observer(logger))
    diagnostic.record("generation", "started")
    diagnostic.record("schema_validation", "rejected")
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    expected = {
        "timestamp",
        "level",
        "event",
        "generation_attempt_id",
        "generation_stage",
        "generation_reason",
        "generation_provider_request_initiated",
        "generation_provider_response_received",
    }
    assert all(set(event) == expected for event in events)
    assert {event["event"] for event in events} == {"project_generation_pipeline"}
    assert {event["generation_stage"] for event in events} == {
        "generation",
        "schema_validation",
    }
    assert len({event["generation_attempt_id"] for event in events}) == 1
    assert "request_id" not in stream.getvalue()


@pytest.mark.parametrize("corrupt", [False, True])
def test_private_formatter_drops_injected_metadata_and_raw_exceptions(corrupt):
    stream = io.StringIO()
    logger = logging.Logger("synthetic-private-generation", level=logging.DEBUG)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    fields = project_generation_fields(str(uuid4()), "schema_validation", "rejected", True, True)
    if corrupt:
        fields["generation_reason"] = "private-response-canary"
    fields.update(
        request_id="private-client-request-canary",
        token="private-token-canary",
        question="private-prompt-canary",
        account_id="private-account-canary",
        support_provenance="private-source-canary",
    )
    try:
        raise ValueError("private-exception-canary")
    except ValueError:
        logger.exception("project_generation_pipeline", extra=fields)
    value = json.loads(stream.getvalue())
    assert "private" not in stream.getvalue()
    if corrupt:
        assert set(value) == {"timestamp", "level", "event"}
    else:
        assert set(value) == {
            "timestamp",
            "level",
            "event",
            "generation_attempt_id",
            "generation_stage",
            "generation_reason",
            "generation_provider_request_initiated",
            "generation_provider_response_received",
        }


def test_nested_scope_exception_restores_outer_then_clears_request_context():
    outer, outer_events = capture()
    inner, inner_events = capture()
    with outer.provider_scope():
        with pytest.raises(RuntimeError), inner.provider_scope():
            notify_project_provider_request()
            raise RuntimeError("private-exception")
        notify_project_provider_request()
        notify_project_provider_response(200)
    notify_project_provider_request()
    assert len(inner_events) == 1 and len(outer_events) == 3
    assert inner_events[0][0] != outer_events[0][0]


def test_unscoped_sdk_call_does_not_reuse_a_previous_attempt_on_shared_loop():
    diagnostic, events = capture()
    adapter = transport(lambda wire: httpx.Response(200, json=response()))
    try:
        with diagnostic.provider_scope():
            assert adapter.complete(request()).status == "success"
        before = list(events)
        assert adapter.complete(request()).status == "success"
        assert events == before
    finally:
        adapter.close()


def test_actual_schema_sdk_and_http_hooks_propagate_context_without_retaining_content():
    diagnostic, events = capture()
    calls = []

    def handle(wire):
        calls.append(wire)
        sent = json.loads(wire.content)["generationConfig"]["responseJsonSchema"]
        assert sent["properties"]["schema_version"]["enum"] == ["project-learning-v1"]
        return httpx.Response(200, json=response())

    adapter = transport(handle)
    try:
        with diagnostic.provider_scope():
            result = adapter.complete(
                request(
                    capability="generation",
                    output_schema_json=json.dumps(ProjectLearningContent.model_json_schema()),
                )
            )
        assert result.status == "success" and len(calls) == 1
        assert labels(events) == [
            ("provider_request", "initiated", True, False),
            ("provider_request", "response_received", True, True),
            ("provider_http", "success", True, True),
        ]
        assert result.text not in repr(events)
    finally:
        adapter.close()


def test_pre_wire_schema_rejection_has_no_http_initiation_observation():
    diagnostic, events = capture()
    calls = []
    adapter = transport(lambda wire: calls.append(wire))
    try:
        with diagnostic.provider_scope(), pytest.raises(AITransportError):
            adapter.complete(request(output_schema_json='{"const":true}'))
        diagnostic.record("provider", "request_rejected")
        assert not calls
        assert labels(events) == [("provider", "request_rejected", False, False)]
    finally:
        adapter.close()


@pytest.mark.parametrize("kind", ["quota", "invalid_body", "connection_error"])
def test_wire_response_is_distinct_from_transport_and_sdk_parsing_failure(kind):
    diagnostic, events = capture()

    def handle(wire):
        if kind == "connection_error":
            raise httpx.ConnectError("private-network-message", request=wire)
        if kind == "quota":
            return httpx.Response(429, json={"error": {"code": 429, "message": "private"}})
        return httpx.Response(200, content="private-malformed-body")

    adapter = transport(handle)
    try:
        with diagnostic.provider_scope(), pytest.raises(AITransportError):
            adapter.complete(request())
        assert events[0][1:] == ("provider_request", "initiated", True, False)
        if kind == "connection_error":
            assert len(events) == 1
        else:
            assert events[-1][1:] == (
                "provider_http",
                "quota" if kind == "quota" else "success",
                True,
                True,
            )
        assert "private" not in repr(events)
    finally:
        adapter.close()


def test_parallel_sdk_requests_keep_distinct_contexts_on_shared_provider_loop():
    ready = asyncio.Event()
    count = 0

    async def handle(wire):
        nonlocal count
        count += 1
        if count == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), timeout=2)
        return httpx.Response(200, json=response())

    first, first_events = capture()
    second, second_events = capture()
    adapter = transport(handle)

    def invoke(diagnostic):
        with diagnostic.provider_scope():
            return adapter.complete(request()).status

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(invoke, value) for value in (first, second)]
            assert [future.result(timeout=8) for future in futures] == ["success", "success"]
        assert count == 2
        for events in (first_events, second_events):
            assert labels(events) == [
                ("provider_request", "initiated", True, False),
                ("provider_request", "response_received", True, True),
                ("provider_http", "success", True, True),
            ]
            assert len({event[0] for event in events}) == 1
        assert first_events[0][0] != second_events[0][0]
    finally:
        adapter.close()
