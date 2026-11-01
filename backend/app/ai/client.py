"""Bounded synchronous AI boundary. This milestone permits only injected mock transport.

No SDK, credential loading, HTTP, retries to another model or raw-content logging.
Limits and accounting are per client/process, not a distributed billing guarantee.
"""

import json
import time
from collections.abc import Callable
from threading import RLock
from typing import Literal, Protocol

from pydantic import TypeAdapter, ValidationError

from app.core.ai_settings import AIClientSettings
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
    def __init__(self, code: ClientErrorCode) -> None:
        try:
            self.code: ClientErrorCode = TypeAdapter[ClientErrorCode](
                ClientErrorCode
            ).validate_python(code)
        except ValidationError:
            self.code = "transport_error"
        super().__init__("AI request failed")


class AITransport(Protocol):
    source: Literal["test_fixture"]

    def complete(self, request: TransportRequest) -> TransportCompletion: ...


class BoundedAIClient:
    def __init__(
        self,
        settings: AIClientSettings,
        transport: AITransport | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = AIClientSettings.model_validate(settings.model_dump(warnings=False))
        self.transport, self.clock = transport, clock
        self._lock = RLock()
        self._windows: dict[tuple[str, Capability], tuple[int, int]] = {}
        self._usage: dict[tuple[Capability, str | None], list[int]] = {}
        self._spent = 0
        self._closed = False

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def close(self) -> None:
        """End ownership once; optional transport cleanup does not change its protocol."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            cleanup = getattr(self.transport, "close", None)
            if callable(cleanup):
                cleanup()
        except Exception:
            raise RuntimeError("AI client cleanup failed.") from None

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
                response.status if response else statuses.get(code or "", "unavailable")
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
            return ClientCompletion(
                status=status,
                text=response.text if response else None,
                provider_id="mock" if self.settings.mode == "mock" else "unconfigured",
                requested_model_id=model,
                returned_model_id=response.returned_model_id if response else None,
                request_id=response.request_id if response else None,
                source="test_fixture",
                error_code=code,
            )

        if self.closed or self.settings.mode != "mock":
            return result("disabled")
        if self.transport is None or getattr(self.transport, "source", None) != "test_fixture":
            return result("configuration_missing")
        try:
            if capability not in {"generation", "tutor", "support"}:
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
                reserve = self.settings.max_cost_per_attempt_microusd
                if self._spent + reserve > self.settings.spend_limit_microusd:
                    return result("budget_exhausted")
                self._spent += reserve
                usage = self._usage.setdefault((capability, model), [0, 0, 0, 0, 0])
                usage[0] += 1
            error: ClientErrorCode | None = None
            response: TransportCompletion | None = None
            accounted = reserve
            try:
                remaining = self.settings.total_timeout_seconds - (self.clock() - started)
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
                received = self.transport.complete(bounded)
                response = TransportCompletion.model_validate(received.model_dump(warnings=False))
                text = response.text
                if response.cost_microusd is not None:
                    accounted = response.cost_microusd
                if self.clock() - started >= self.settings.total_timeout_seconds:
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
                    and response.returned_model_id is not None
                    or response.status == "success"
                    and (text is None or not text.strip())
                ):
                    error = "invalid_response"
            except AITransportError as exc:
                error = exc.code
            except (ValidationError, ValueError, TypeError, UnicodeError, AttributeError):
                error = "invalid_response"
            except Exception:
                error = "transport_error"
            finally:
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
            # Work reserved before shutdown may finish, but its text cannot escape
            # a closed application resource and no further retry may start.
            if self.closed:
                return result("disabled")
            if error is None:
                return result(response=response)
            # Same provider/model only. No authentication, invalid input or unknown retries.
            if error not in {"transient_error", "rate_limited", "timeout"} or (
                attempt == self.settings.max_retries
                or self.clock() - started >= self.settings.total_timeout_seconds
            ):
                return result(error)
        return result("transport_error")
