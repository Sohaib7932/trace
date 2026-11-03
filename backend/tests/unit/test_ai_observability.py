"""Delivery visibility uses exact categorical labels and never arbitrary data."""

import io
import json
import logging

import pytest

from app.ai.observability import delivery_fields, record_ai_delivery
from app.core.logging import JsonFormatter


def capture():
    stream = io.StringIO()
    logger = logging.Logger("synthetic-observability", level=logging.DEBUG)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    return logger, stream


@pytest.mark.parametrize(
    "family,status,source,outcome,level",
    [
        ("tutor", "answered", "ai", "delivered", "INFO"),
        ("tutor", "declined", "test_fixture", "abstained", "INFO"),
        ("tutor", "unavailable", "none", "unavailable", "WARNING"),
        ("support", "answered", "ai", "delivered", "INFO"),
        ("support", "unsupported", "ai", "abstained", "INFO"),
        ("support", "no_sources", "unavailable", "abstained", "INFO"),
        ("support", "unavailable", "unavailable", "unavailable", "WARNING"),
        ("generation", "success", "test_fixture", "delivered", "INFO"),
        ("generation", "refusal", "ai", "abstained", "INFO"),
        ("generation", "truncated", "ai", "error", "WARNING"),
        ("generation", "timeout", "ai", "error", "WARNING"),
        ("generation", "transport_error", "unavailable", "error", "WARNING"),
        ("generation", "rate_limited", "none", "unavailable", "WARNING"),
        ("generation", "unavailable", "unavailable", "unavailable", "WARNING"),
        ("embedding", "success", "ai", "delivered", "INFO"),
        ("embedding", "unavailable", "unavailable", "unavailable", "WARNING"),
    ],
)
def test_actual_statuses_preserve_honest_outcome_and_source(family, status, source, outcome, level):
    logger, stream = capture()
    record_ai_delivery(logger, family=family, status=status, source=source)
    result = json.loads(stream.getvalue())
    assert result == {
        "timestamp": result["timestamp"],
        "level": level,
        "event": "ai_delivery",
        "ai_family": family,
        "ai_status": status,
        "ai_outcome": outcome,
        "ai_source": source,
    }


@pytest.mark.parametrize("field", ["family", "status", "source"])
@pytest.mark.parametrize(
    "value", ["private-person@example.test", "unknown", "ai\ninjected", None, {}]
)
def test_unknown_or_nonstring_labels_are_rejected_without_logging(field, value):
    logger, stream = capture()
    labels = {"family": "tutor", "status": "answered", "source": "ai", field: value}
    with pytest.raises(ValueError, match="^Invalid AI delivery observation$"):
        record_ai_delivery(logger, **labels)
    assert stream.getvalue() == ""


@pytest.mark.parametrize(
    "family,status,source",
    [
        ("tutor", "answered", "none"),
        ("tutor", "unavailable", "ai"),
        ("support", "answered", "unavailable"),
        ("support", "no_sources", "ai"),
        ("embedding", "success", "unavailable"),
        ("embedding", "unavailable", "ai"),
        ("embedding", "answered", "ai"),
        ("generation", "success", "none"),
    ],
)
def test_inconsistent_provenance_or_family_status_is_rejected(family, status, source):
    with pytest.raises(ValueError, match="Invalid AI delivery observation"):
        delivery_fields(family, status, source)


@pytest.mark.parametrize(
    "field", ["question", "text", "answer", "account_id", "session_id", "token", "error"]
)
def test_helper_does_not_accept_sensitive_metadata(field):
    logger, stream = capture()
    with pytest.raises(TypeError):
        record_ai_delivery(
            logger, family="tutor", status="answered", source="ai", **{field: "private-canary"}
        )
    assert stream.getvalue() == ""


@pytest.mark.parametrize(
    "mutation",
    [
        {"ai_family": "private-family-canary"},
        {"ai_status": "private-status-canary"},
        {"ai_source": "private-source-canary"},
        {"ai_outcome": "private-outcome-canary"},
        {"ai_status": "unavailable", "ai_outcome": "delivered"},
    ],
)
def test_formatter_independently_rejects_injected_or_conflicting_labels(mutation):
    logger, stream = capture()
    fields = delivery_fields("tutor", "answered", "ai")
    fields.update(mutation)
    fields.update(
        question="private-question-canary",
        token="private-token-canary",
        account_id="private-account-canary",
    )
    logger.info("ai_delivery", extra=fields)
    result = json.loads(stream.getvalue())
    assert set(result) == {"timestamp", "level", "event"}
    assert "private" not in stream.getvalue()


def test_formatter_never_renders_untrusted_label_objects():
    class PrivateObject:
        def __str__(self):
            pytest.fail("Sensitive object was rendered")

        def __repr__(self):
            pytest.fail("Sensitive object was rendered")

    logger, stream = capture()
    fields = delivery_fields("support", "answered", "ai")
    fields["ai_source"] = PrivateObject()
    logger.info("ai_delivery", extra=fields)
    assert set(json.loads(stream.getvalue())) == {"timestamp", "level", "event"}


def test_existing_structured_events_are_unchanged_without_delivery_metadata():
    logger, stream = capture()
    logger.info("request_complete", extra={"request_id": "synthetic", "status_code": 200})
    result = json.loads(stream.getvalue())
    assert set(result) == {"timestamp", "level", "event", "request_id", "status_code"}
    assert result["event"] == "request_complete" and result["status_code"] == 200
