"""Request-local categorical generation diagnostics; no prompts or provider bodies.

HTTP initiation records local dispatch only, never proof of remote receipt. Each
request gets a fresh server-generated identifier; callers cannot supply one.
"""

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from threading import RLock
from uuid import UUID, uuid4

type GenerationObserver = Callable[[str, str, str, bool, bool], None]

_REASONS: dict[str, frozenset[str]] = {
    "generation": frozenset({"started"}),
    "provider": frozenset(
        {
            "transport_entered",
            "authentication",
            "quota",
            "timeout",
            "transport",
            "provider_rejection",
            "success",
            "availability",
            "request_rejected",
            "bounds_rejected",
            "invalid_response",
            "accounting",
            "internal_error",
        }
    ),
    "provider_request": frozenset({"initiated", "response_received"}),
    "provider_http": frozenset(
        {"success", "authentication", "quota", "timeout", "transport", "provider_rejection"}
    ),
    "response_parsing": frozenset({"passed", "rejected"}),
    "schema_validation": frozenset({"passed", "rejected"}),
    "citation_validation": frozenset({"passed", "rejected"}),
    "provenance_validation": frozenset({"passed", "rejected"}),
    "snapshot_validation": frozenset({"passed", "rejected"}),
    "persistence": frozenset({"started", "committed", "failed"}),
    "release": frozenset({"passed", "failed"}),
}


def project_generation_fields(
    attempt_id: object,
    stage: object,
    reason: object,
    initiated: object,
    response_received: object,
) -> dict[str, str | bool]:
    """Validate the complete bundle independently at each logging boundary."""
    if (
        type(attempt_id) is not str
        or type(stage) is not str
        or type(reason) is not str
        or type(initiated) is not bool
        or type(response_received) is not bool
        or reason not in _REASONS.get(stage, ())
        or (response_received and not initiated)
        or (stage == "provider_http" and not (initiated and response_received))
        or (stage == "generation" and (initiated or response_received))
        or (
            stage == "provider_request"
            and (not initiated or response_received != (reason == "response_received"))
        )
    ):
        raise ValueError("Invalid project generation diagnostic")
    try:
        parsed = UUID(attempt_id)
    except ValueError:
        raise ValueError("Invalid project generation diagnostic") from None
    if parsed.version != 4 or str(parsed) != attempt_id:
        raise ValueError("Invalid project generation diagnostic")
    return {
        "generation_attempt_id": attempt_id,
        "generation_stage": stage,
        "generation_reason": reason,
        "generation_provider_request_initiated": initiated,
        "generation_provider_response_received": response_received,
    }


class ProjectGenerationDiagnostics:
    def __init__(self, observer: GenerationObserver | None = None) -> None:
        self._attempt_id = str(uuid4())
        self._observer = observer
        self._initiated = False
        self._response_received = False
        self._lock = RLock()

    def record(self, stage: str, reason: str) -> None:
        try:
            with self._lock:
                initiated, received = self._initiated, self._response_received
                project_generation_fields(self._attempt_id, stage, reason, initiated, received)
                if self._observer is not None:
                    self._observer(self._attempt_id, stage, reason, initiated, received)
        except Exception:
            pass  # Diagnostics cannot alter provider work or trusted release decisions.

    @contextmanager
    def provider_scope(self) -> Iterator[None]:
        token = _CURRENT.set(self)
        try:
            yield
        finally:
            _CURRENT.reset(token)

    def _request_started(self) -> None:
        with self._lock:
            self._initiated = True
            self.record("provider_request", "initiated")

    def _response_returned(self, status_code: int) -> None:
        with self._lock:
            # A received response without a preceding initiation is incoherent.
            if not self._initiated:
                return
            self._response_received = True
            self.record("provider_request", "response_received")
            if type(status_code) is not int or not 100 <= status_code <= 599:
                return
            reason = (
                "success"
                if 200 <= status_code < 300
                else "authentication"
                if status_code in {401, 403}
                else "quota"
                if status_code == 429
                else "timeout"
                if status_code in {408, 504}
                else "transport"
                if status_code >= 500
                else "provider_rejection"
            )
            self.record("provider_http", reason)


_CURRENT: ContextVar[ProjectGenerationDiagnostics | None] = ContextVar(
    "project_generation_diagnostics", default=None
)


def notify_project_provider_request() -> None:
    current = _CURRENT.get()
    if current is not None:
        current._request_started()


def notify_project_provider_response(status_code: int) -> None:
    current = _CURRENT.get()
    if current is not None:
        current._response_returned(status_code)


def project_generation_logger_observer(logger: logging.Logger) -> GenerationObserver:
    def observe(
        attempt_id: str, stage: str, reason: str, initiated: bool, response_received: bool
    ) -> None:
        fields = project_generation_fields(attempt_id, stage, reason, initiated, response_received)
        level = (
            logging.WARNING
            if reason
            in {
                "authentication",
                "quota",
                "timeout",
                "transport",
                "provider_rejection",
                "availability",
                "request_rejected",
                "bounds_rejected",
                "invalid_response",
                "accounting",
                "internal_error",
                "rejected",
                "failed",
            }
            else logging.INFO
        )
        logger.log(level, "project_generation_pipeline", extra=fields)

    return observe
