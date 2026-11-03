"""Bounded synchronous AI boundary with explicit mock or approved free-tier transport.

No credentials, retries to another model or raw-content logging in this layer.
Limits and accounting are per client/process, not a distributed billing guarantee.
"""

import json
import math
import time
from collections.abc import Callable
from contextlib import suppress
from hashlib import sha256
from threading import Condition, RLock
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from app.ai.accounting import (
    AIAccountingError,
    AIUsageLedger,
    AllowancePolicy,
    ProviderAttempt,
    ProviderUsage,
)
from app.ai.diagnostics import ProviderDiagnostics, ProviderOutcome
from app.core.ai_settings import GEMINI_PROFILE, AIClientSettings
from app.schemas.ai_client import (
    Capability,
    ClientCompletion,
    ClientErrorCode,
    TransportCompletion,
    TransportRequest,
    UsageRecord,
)
from app.schemas.generation import CompletionStatus


class AITransportError(Exception):
    def __init__(
        self, code: ClientErrorCode, completion: TransportCompletion | None = None
    ) -> None:
        try:
            self.code: ClientErrorCode = TypeAdapter[ClientErrorCode](
                # The PEP 695 alias object is not type[T] to mypy. Its value is
                # the same Literal schema, preserving strict runtime validation.
                ClientErrorCode.__value__
            ).validate_python(code)
        except ValidationError:
            self.code = "transport_error"
        # Failed content cannot escape through an exception. Supplied bounded
        # usage/model metadata still belongs in accounting even on rejection.
        self.completion = (
            completion.model_copy(update={"text": None}) if completion is not None else None
        )
        super().__init__("AI request failed")


class AITransport(Protocol):
    @property
    def source(self) -> Literal["test_fixture", "ai"]: ...

    def complete(self, request: TransportRequest) -> TransportCompletion: ...


class BoundedAIClient:
    def __init__(
        self,
        settings: AIClientSettings,
        transport: AITransport | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        ledger: AIUsageLedger | None = None,
        allowance_policy: AllowancePolicy | None = None,
    ) -> None:
        self.settings = AIClientSettings.model_validate(settings.model_dump(warnings=False))
        self.transport, self.clock = transport, clock
        if (ledger is None) != (allowance_policy is None):
            raise ValueError("Durable AI accounting requires both a ledger and allowance policy")
        self.ledger = ledger
        self.allowance_policy = (
            AllowancePolicy.model_validate(allowance_policy.model_dump())
            if allowance_policy is not None
            else None
        )
        self._lock = RLock()
        self._idle = Condition(self._lock)
        self._windows: dict[tuple[str, Capability], tuple[int, int]] = {}
        self._usage: dict[tuple[Capability, str | None], list[int]] = {}
        self._spent = 0
        self._closed = False
        self._live_attempts = 0
        self._in_flight = 0
        self._transport_closed = False
        self._cleanup_failed = False
        self._outcomes: dict[tuple[Capability, str], int] = {}

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def close(self) -> None:
        """Stop admission; retain transport ownership until real work finishes."""
        with self._lock:
            self._closed = True
            if self._in_flight:
                return
        self._close_transport()

    def stop_admission(self) -> None:
        """Quiesce an application before draining its service-level work."""
        with self._lock:
            self._closed = True

    def _close_transport(self) -> None:
        with self._lock:
            if self._transport_closed:
                return
            self._transport_closed = True
        try:
            cleanup = getattr(self.transport, "close", None)
            if callable(cleanup):
                cleanup()
        except Exception:
            with self._lock:
                self._cleanup_failed = True
            raise RuntimeError("AI client cleanup failed.") from None

    def wait_for_idle(self, timeout: float | None = None) -> bool:
        """Wait for actual work, without claiming synchronous threads were killed."""
        with self._idle:
            return self._idle.wait_for(lambda: self._in_flight == 0, timeout=timeout)

    def diagnostics_snapshot(self) -> ProviderDiagnostics:
        with self._lock:
            expected = "ai" if self.settings.mode == "gemini_free" else "test_fixture"
            configured = self.transport is not None and self.transport.source == expected
            return ProviderDiagnostics(
                version="provider-diagnostics-v1",
                mode=self.settings.mode,
                availability=(
                    "closed"
                    if self._closed
                    else "disabled"
                    if self.settings.mode == "disabled"
                    else "configured"
                    if configured
                    else "unconfigured"
                ),
                capability_profile=GEMINI_PROFILE if self.settings.mode == "gemini_free" else None,
                capabilities=(
                    ("generation", "tutor", "support")
                    if self.settings.mode == "gemini_free"
                    else ("generation", "tutor", "support", "feedback")
                    if self.settings.mode == "mock"
                    else ()
                ),
                in_flight=self._in_flight,
                max_in_flight=self.settings.max_in_flight,
                attempts=sum(value[0] for value in self._usage.values()),
                outcomes=tuple(
                    ProviderOutcome(capability=k[0], outcome=k[1], count=v)
                    for k, v in sorted(self._outcomes.items())
                ),
                network_deadline_enforced=(
                    getattr(self.transport, "network_deadline_enforced", False) is True
                ),
                cleanup_failed=self._cleanup_failed,
            )

    def usage_snapshot(self) -> tuple[UsageRecord, ...]:
        with self._lock:
            return tuple(
                UsageRecord(
                    capability=key[0],
                    model_id=key[1],
                    attempts=value[0],
                    input_tokens=value[1],
                    output_tokens=value[2],
                    accounted_cost_microusd=value[3],
                    missing_usage_count=value[4],
                )
                for key, value in self._usage.items()
            )

    def complete(
        self,
        *,
        capability: Capability,
        instructions: str,
        data: dict[str, object],
        output_schema: dict[str, object] | None = None,
        subject: str = "internal",
        timeout_seconds: float | None = None,
        on_transport_attempt: Callable[[], None] | None = None,
    ) -> ClientCompletion:
        model = (
            self.settings.generation_model_id
            if capability == "generation"
            else self.settings.conversational_model_id
        )

        def result(
            code: ClientErrorCode | None = None,
            response: TransportCompletion | None = None,
        ) -> ClientCompletion:
            statuses: dict[str, CompletionStatus] = {
                "timeout": "timeout",
                "rate_limited": "rate_limited",
            }
            status: CompletionStatus = (
                statuses.get(code, "unavailable")
                if code
                else response.status
                if response
                else "unavailable"
            )
            if code in {
                "transport_error",
                "authentication_error",
                "invalid_request",
                "invalid_response",
                "response_too_large",
                "token_limit",
                "transient_error",
            }:
                status = "transport_error"
            if capability in ("generation", "tutor", "support", "feedback"):
                with self._lock:
                    outcome_key = (capability, code or status)
                    self._outcomes[outcome_key] = self._outcomes.get(outcome_key, 0) + 1
            return ClientCompletion(
                status=status,
                text=response.text if response and code is None else None,
                provider_id=(
                    "gemini"
                    if self.settings.mode == "gemini_free"
                    else "mock"
                    if self.settings.mode == "mock"
                    else "unconfigured"
                ),
                requested_model_id=model,
                returned_model_id=response.returned_model_id if response else None,
                request_id=response.request_id if response else None,
                source="ai" if self.settings.mode == "gemini_free" else "test_fixture",
                error_code=code,
            )

        if self.closed or self.settings.mode == "disabled":
            return result("disabled")
        expected_source = "ai" if self.settings.mode == "gemini_free" else "test_fixture"
        if self.transport is None or getattr(self.transport, "source", None) != expected_source:
            return result("configuration_missing")
        if self.settings.mode == "gemini_free" and capability not in {
            "tutor",
            "generation",
            "support",
        }:
            return result("disabled")
        if timeout_seconds is not None and (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            return result("invalid_request")
        call_timeout = min(
            self.settings.total_timeout_seconds,
            timeout_seconds if timeout_seconds is not None else self.settings.total_timeout_seconds,
        )
        try:
            if capability not in {"generation", "tutor", "support", "feedback"}:
                return result("invalid_request")
            if not isinstance(subject, str) or not subject or len(subject) > 128:
                return result("invalid_request")
            if not isinstance(data, dict) or (
                output_schema is not None and not isinstance(output_schema, dict)
            ):
                return result("invalid_request")
            # Data/schema are serialized separately; neither can become system instructions.
            raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            schema = (
                json.dumps(
                    output_schema, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                )
                if output_schema is not None
                else None
            )
            size = len((instructions + raw + (schema or "")).encode("utf-8"))
            if size > self.settings.max_request_bytes:
                return result("request_too_large")
            # Conservative UTF-8 byte budget until an approved tokenizer is available.
            if size > self.settings.max_input_tokens:
                return result("token_limit")
            request = TransportRequest(
                capability=capability,
                instructions=instructions,
                data_json=raw,
                output_schema_json=schema,
                requested_model_id=model,
                max_input_tokens=self.settings.max_input_tokens,
                max_output_tokens=self.settings.max_output_tokens,
                max_response_bytes=self.settings.max_response_bytes,
                connect_timeout_seconds=self.settings.connect_timeout_seconds,
                response_timeout_seconds=self.settings.response_timeout_seconds,
            )
        except (ValueError, TypeError, UnicodeError, RecursionError):
            return result("invalid_request")

        started = self.clock()
        with self._lock:
            minute = int(started // 60)
            self._windows = {k: v for k, v in self._windows.items() if v[0] == minute}
            key = (subject, capability)
            count = self._windows.get(key, (minute, 0))[1]
            if count >= self.settings.requests_per_minute:
                return result("rate_limited")
            if key not in self._windows and len(self._windows) >= self.settings.max_subjects:
                return result("rate_limited")
            self._windows[key] = (minute, count + 1)

        for attempt in range(self.settings.max_retries + 1):
            with self._lock:
                if self._closed:
                    return result("disabled")
                if self._in_flight >= self.settings.max_in_flight:
                    return result("rate_limited")
                if self.settings.mode == "gemini_free":
                    if self._live_attempts >= self.settings.max_live_requests_per_process:
                        return result("budget_exhausted")
                    self._live_attempts += 1
                reserve = self.settings.max_cost_per_attempt_microusd
                if self._spent + reserve > self.settings.spend_limit_microusd:
                    return result("budget_exhausted")
                self._spent += reserve
                usage = self._usage.setdefault((capability, model), [0, 0, 0, 0, 0])
                usage[0] += 1
                self._in_flight += 1
            error: ClientErrorCode | None = None
            response: TransportCompletion | None = None
            accounted = reserve
            ledger_attempt = None
            provider_duration_ms = None
            try:
                remaining = call_timeout - (self.clock() - started)
                if remaining <= 0:
                    raise AITransportError("timeout")
                if self.closed:
                    raise AITransportError("disabled")
                if (
                    self.settings.mode == "gemini_free"
                    and self.ledger is not None
                    and self.allowance_policy is not None
                ):
                    identifier = uuid4()  # Never reuse a caller's HTTP request/correlation ID.
                    try:
                        reservation = self.ledger.reserve(
                            self.allowance_policy,
                            ProviderAttempt.model_validate(
                                dict(
                                    id=identifier,
                                    capability=capability,
                                    model_id=model,
                                    subject_hash=sha256(subject.encode("utf-8")).hexdigest(),
                                    estimated_input_bytes=size,
                                    item_count=1,
                                )
                            ),
                        )
                    except AIAccountingError:
                        raise
                    except Exception:
                        raise AIAccountingError("unavailable") from None
                    if reservation.attempt_id != identifier:
                        raise AIAccountingError("conflict")
                    if not reservation.newly_reserved:
                        raise AIAccountingError("duplicate")
                    ledger_attempt = identifier
                    remaining = call_timeout - (self.clock() - started)
                    if remaining <= 0:
                        raise AITransportError("timeout")
                bounded = request.model_copy(
                    update={
                        "response_timeout_seconds": min(
                            request.response_timeout_seconds, remaining
                        ),
                        "connect_timeout_seconds": min(request.connect_timeout_seconds, remaining),
                    }
                )
                if self.closed:
                    raise AITransportError("disabled")
                provider_started = self.clock() if ledger_attempt is not None else None
                try:
                    if on_transport_attempt is not None:
                        with suppress(Exception):
                            on_transport_attempt()
                    received = self.transport.complete(bounded)
                finally:
                    if provider_started is not None:
                        elapsed = self.clock() - provider_started
                        if math.isfinite(elapsed) and 0 <= elapsed <= 1_000_000:
                            provider_duration_ms = int(elapsed * 1000)
                response = TransportCompletion.model_validate(received.model_dump(warnings=False))
                text = response.text
                if response.cost_microusd is not None:
                    accounted = response.cost_microusd
                if self.clock() - started >= call_timeout:
                    error = "timeout"
                elif (
                    text is not None
                    and len(text.encode("utf-8")) > self.settings.max_response_bytes
                ):
                    error = "response_too_large"
                elif (response.input_tokens or 0) > self.settings.max_input_tokens or (
                    response.output_tokens
                    if response.output_tokens is not None
                    else len((text or "").encode("utf-8"))
                ) > self.settings.max_output_tokens:
                    error = "token_limit"
                elif accounted > reserve:
                    error = "budget_exhausted"
                elif (
                    response.returned_model_id != model
                    and (
                        response.returned_model_id is not None
                        or self.settings.mode == "gemini_free"
                    )
                    or response.status == "success"
                    and (text is None or not text.strip())
                ):
                    error = "invalid_response"
            except AITransportError as exc:
                error = exc.code
                response = exc.completion
                if response is not None and response.cost_microusd is not None:
                    accounted = response.cost_microusd
            except AIAccountingError as exc:
                error = (
                    "budget_exhausted"
                    if exc.code == "depleted"
                    else "rate_limited"
                    if exc.code == "saturated"
                    else "accounting_unavailable"
                )
            except (ValidationError, ValueError, TypeError, UnicodeError, AttributeError):
                error = "invalid_response"
            except Exception:
                error = "transport_error"
            finally:
                if ledger_attempt is not None and self.ledger is not None:
                    try:
                        self.ledger.finish(
                            ledger_attempt,
                            ProviderUsage(
                                status=(
                                    response.status
                                    if response is not None and error is None
                                    else "timeout"
                                    if error == "timeout"
                                    else "error"
                                ),
                                error_code=error,
                                input_tokens=response.input_tokens
                                if response is not None
                                else None,
                                output_tokens=response.output_tokens
                                if response is not None
                                else None,
                                provider_duration_ms=provider_duration_ms,
                                accounted_cost_microusd=response.cost_microusd
                                if response is not None
                                else None,
                            ),
                        )
                    except Exception:
                        # Keep reservation/lease consumed, discard even valid AI
                        # output and never retry a provider after accounting loss.
                        error = "accounting_unavailable"
                with self._lock:
                    self._spent += accounted - reserve
                    usage[3] += accounted
                    if response is not None:
                        usage[1] += response.input_tokens or 0
                        usage[2] += response.output_tokens or 0
                    if response is None or any(
                        v is None
                        for v in (
                            response.input_tokens,
                            response.output_tokens,
                            response.cost_microusd,
                        )
                    ):
                        usage[4] += 1
                    self._in_flight -= 1
                    self._idle.notify_all()
                    cleanup = self._closed and self._in_flight == 0
                if cleanup:
                    # The safe failure is observable internally. Never leak
                    # cleanup errors through a canceled request or late output.
                    with suppress(RuntimeError):
                        self._close_transport()
            # Work reserved before shutdown may finish, but its text cannot escape
            # a closed application resource and no further retry may start.
            if (
                ledger_attempt is not None
                and error is None
                and self.clock() - started >= call_timeout
            ):
                error = "timeout"
            if self.closed:
                return result("disabled")
            if error is None:
                return result(response=response)
            # Same provider/model only. No authentication, invalid input or unknown retries.
            if error not in {"transient_error", "rate_limited", "timeout"} or (
                attempt == self.settings.max_retries
                or self.clock() - started >= self.settings.total_timeout_seconds
            ):
                return result(error, response)
        return result("transport_error")
