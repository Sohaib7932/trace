"""Low-cardinality delivery observations, never provider or learner payloads.

These labels describe the validated result at the release boundary, not HTTP
success, verified exercise correctness, generated-candidate approval or billing.
No identifier, exception, question, answer or additional metadata is accepted.
"""

import logging

_MODEL_SOURCES = frozenset({"ai", "test_fixture"})
_FAILED_TRANSPORT_SOURCES = frozenset({"ai", "test_fixture", "none", "unavailable"})
_DELIVERY: dict[tuple[str, str], tuple[str, frozenset[str]]] = {
    ("tutor", "answered"): ("delivered", _MODEL_SOURCES),
    ("tutor", "declined"): ("abstained", _MODEL_SOURCES),
    ("tutor", "unavailable"): ("unavailable", frozenset({"none"})),
    ("support", "answered"): ("delivered", _MODEL_SOURCES),
    ("support", "unsupported"): ("abstained", _MODEL_SOURCES),
    ("support", "no_sources"): ("abstained", frozenset({"unavailable"})),
    ("support", "unavailable"): ("unavailable", frozenset({"unavailable"})),
    ("generation", "success"): ("delivered", _MODEL_SOURCES),
    ("generation", "refusal"): ("abstained", _MODEL_SOURCES),
    ("generation", "truncated"): ("error", _MODEL_SOURCES),
    ("generation", "timeout"): ("error", _FAILED_TRANSPORT_SOURCES),
    ("generation", "transport_error"): ("error", _FAILED_TRANSPORT_SOURCES),
    ("generation", "rate_limited"): ("unavailable", _FAILED_TRANSPORT_SOURCES),
    ("generation", "unavailable"): ("unavailable", _FAILED_TRANSPORT_SOURCES),
    ("embedding", "success"): ("delivered", _MODEL_SOURCES),
    ("embedding", "unavailable"): ("unavailable", frozenset({"unavailable"})),
}


def delivery_fields(family: object, status: object, source: object) -> dict[str, str]:
    """Reject unknown/inconsistent labels without rendering their values."""
    if type(family) is not str or type(status) is not str or type(source) is not str:
        raise ValueError("Invalid AI delivery observation")
    permitted = _DELIVERY.get((family, status))
    if permitted is None or source not in permitted[1]:
        raise ValueError("Invalid AI delivery observation")
    return {
        "ai_family": family,
        "ai_status": status,
        "ai_outcome": permitted[0],
        "ai_source": source,
    }


def record_ai_delivery(logger: logging.Logger, *, family: str, status: str, source: str) -> None:
    """Record a final authorized result; unavailable HTTP-200 replies remain visible.

    Call only after final authorization and any required durable release receipt.
    A generation/embedding success here describes transport delivery, never
    content admission, production approval, learner grading or assignment.
    """
    fields = delivery_fields(family, status, source)
    level = logging.WARNING if fields["ai_outcome"] in {"unavailable", "error"} else logging.INFO
    logger.log(level, "ai_delivery", extra=fields)
