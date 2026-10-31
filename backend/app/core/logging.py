import json
import logging
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    """Allowlist structured fields; never serialize exception text, bodies or headers."""

    def format(self, record: logging.LogRecord) -> str:
        result: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": record.msg,
        }
        for key in ("request_id", "method", "route", "status_code", "duration_ms", "error_type"):
            if hasattr(record, key):
                result[key] = getattr(record, key)
        return json.dumps(result)


def create_logger(level: str) -> logging.Logger:
    # A distinct logger/handler per app; do not mutate global logging configuration.
    logger = logging.Logger("trace", level=level)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    return logger
