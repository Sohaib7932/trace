import json
import logging
from datetime import UTC, datetime

from app.ai.observability import delivery_fields
from app.ai.support_diagnostics import support_diagnostic_fields, support_runtime_fields


class JsonFormatter(logging.Formatter):
    """Allowlist structured fields; never serialize exception text, bodies or headers."""

    def format(self, record: logging.LogRecord) -> str:
        result: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": record.msg,
        }
        for key in (
            "request_id",
            "method",
            "route",
            "status_code",
            "duration_ms",
            "error_type",
            "support_provenance",
        ):
            if hasattr(record, key):
                result[key] = getattr(record, key)
        # New AI metadata is an all-or-nothing, independently validated bundle.
        # Never allow a direct logger.extra injection to bypass the helper.
        try:
            fields = delivery_fields(
                getattr(record, "ai_family", None),
                getattr(record, "ai_status", None),
                getattr(record, "ai_source", None),
            )
            outcome = getattr(record, "ai_outcome", None)
            if type(outcome) is str and outcome == fields["ai_outcome"]:
                result.update(fields)
        except ValueError:
            pass
        try:
            fields_support = support_diagnostic_fields(
                getattr(record, "support_stage", None),
                getattr(record, "support_reason", None),
                getattr(record, "support_passage_count", None),
            )
            result.update(fields_support)
        except ValueError:
            pass
        try:
            runtime = support_runtime_fields(
                getattr(record, "support_ai_mode", None),
                getattr(record, "support_accounting_mode", None),
                getattr(record, "support_retrieval_mode", None),
                getattr(record, "support_knowledge_backend", None),
                getattr(record, "support_knowledge_available", None),
                getattr(record, "support_source_count", None),
            )
            result.update(runtime)
        except ValueError:
            pass
        return json.dumps(result)


def create_logger(level: str) -> logging.Logger:
    # A distinct logger/handler per app; do not mutate global logging configuration.
    logger = logging.Logger("trace", level=level)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    return logger
