"""Bounded application-owned embedding port; no generative correctness authority."""

import math
import time
from contextlib import suppress
from hashlib import sha256
from threading import Condition, RLock
from typing import Literal, Protocol
from uuid import UUID, uuid4

from app.ai.accounting import (
    AIAccountingError,
    AIUsageLedger,
    AllowancePolicy,
    AttemptReservation,
    ProviderAttempt,
    ProviderUsage,
)
from app.core.embedding_settings import EmbeddingSettings
from app.schemas.ai_client import ClientErrorCode
from app.schemas.embeddings import (
    EmbeddingBatchResult,
    EmbeddingErrorCode,
    EmbeddingPurpose,
    EmbeddingRequest,
    EmbeddingTransportResult,
    EmbeddingUsage,
    UnitEmbedding,
    text_digest,
)


class EmbeddingTransportError(Exception):
    def __init__(self, code: EmbeddingErrorCode) -> None:
        super().__init__("Embedding provider unavailable")
        self.code = code


class EmbeddingTransport(Protocol):
    @property
    def source(self) -> Literal["ai", "test_fixture"]: ...
    def embed(self, request: EmbeddingRequest) -> EmbeddingTransportResult: ...
    def close(self) -> None: ...


class BoundedEmbeddingClient:
    def __init__(
        self,
        settings: EmbeddingSettings,
        transport: EmbeddingTransport | None = None,
        *,
        ledger: AIUsageLedger | None = None,
        allowance_policy: AllowancePolicy | None = None,
    ) -> None:
        self.settings = EmbeddingSettings.model_validate(settings.model_dump(warnings=False))
        self.transport = transport
        if (ledger is None) != (allowance_policy is None):
            raise ValueError("Embedding accounting requires both a ledger and allowance policy")
        self.ledger = ledger
        self.allowance_policy = (
            AllowancePolicy.model_validate(allowance_policy.model_dump(warnings=False))
            if allowance_policy
            else None
        )
        if settings.mode != "disabled" and (
            transport is None
            or transport.source != ("ai" if settings.mode == "gemini_free" else "test_fixture")
        ):
            raise ValueError("Embedding transport does not match its explicit operation mode")
        self._lock = RLock()
        self._idle = Condition(self._lock)
        self._closed = self._transport_closed = False
        self._attempts = self._items = self._reserved = self._observed = 0
        self._missing = self._successes = self._active = 0

    def usage_snapshot(self) -> EmbeddingUsage:
        with self._lock:
            return EmbeddingUsage(
                attempts=self._attempts,
                input_items=self._items,
                reserved_input_token_estimate=self._reserved,
                observed_input_tokens=self._observed,
                missing_usage_count=self._missing,
                successful_batches=self._successes,
                in_flight=self._active,
                closed=self._closed,
            )

    def _close_idle(self) -> None:
        with self._lock:
            should_close = self._closed and not self._active and not self._transport_closed
            if should_close:
                self._transport_closed = True
        if should_close and self.transport is not None:
            # Cleanup never exposes a raw SDK exception or credential.
            with suppress(Exception):
                self.transport.close()

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self._close_idle()

    def stop_admission(self) -> None:
        with self._lock:
            self._closed = True

    def wait_for_idle(self, timeout: float | None = None) -> bool:
        with self._idle:
            return self._idle.wait_for(lambda: self._active == 0, timeout=timeout)

    def embed(
        self,
        texts: tuple[str, ...],
        purpose: EmbeddingPurpose,
        *,
        timeout_seconds: float | None = None,
        subject: str | None = None,
    ) -> EmbeddingBatchResult:
        def unavailable(code: EmbeddingErrorCode) -> EmbeddingBatchResult:
            return EmbeddingBatchResult(
                status="unavailable",
                purpose=purpose,
                input_sha256=(),
                source="unavailable",
                error_code=code,
            )

        try:
            trusted_subject = subject if subject is not None else f"internal-embedding:{purpose}"
            if type(trusted_subject) is not str or not 1 <= len(trusted_subject) <= 256:
                raise ValueError("Embedding accounting requires a bounded trusted subject")
            if timeout_seconds is not None and (
                type(timeout_seconds) not in {int, float}
                or not math.isfinite(timeout_seconds)
                or timeout_seconds <= 0
            ):
                raise ValueError("Invalid embedding deadline")
            timeout = min(
                self.settings.response_timeout_seconds,
                timeout_seconds
                if timeout_seconds is not None
                else self.settings.response_timeout_seconds,
            )
            request = EmbeddingRequest(
                purpose=purpose,
                texts=texts,
                connect_timeout_seconds=min(self.settings.connect_timeout_seconds, timeout),
                response_timeout_seconds=timeout,
                max_response_bytes=self.settings.max_response_bytes,
            )
        except Exception:
            return unavailable("invalid_request")
        # Admission estimate, explicitly not measured/provider-billed token usage.
        reservation = sum(len(text.encode("utf-8")) + 16 for text in request.texts)
        with self._lock:
            if self._closed or self.settings.mode == "disabled":
                return unavailable("disabled")
            if self._active >= self.settings.max_concurrent_requests:
                return unavailable("concurrency_limit")
            if (
                self._attempts >= self.settings.max_requests_per_process
                or self._items + len(request.texts) > self.settings.max_items_per_process
                or max(self._reserved, self._observed) + reservation
                > self.settings.max_reserved_input_tokens_per_process
            ):
                return unavailable("budget_exhausted")
            self._active += 1
            self._attempts += 1
            self._items += len(request.texts)
            self._reserved += reservation
        usage_recorded = False
        started = time.monotonic()
        checked: EmbeddingTransportResult | None = None
        result: EmbeddingBatchResult | None = None
        error: EmbeddingErrorCode | None = None
        ledger_attempt: UUID | None = None
        provider_duration_ms: int | None = None
        try:
            assert self.transport is not None
            if (
                self.settings.mode == "gemini_free"
                and self.ledger is not None
                and self.allowance_policy is not None
            ):
                identifier = uuid4()
                receipt = self.ledger.reserve(
                    self.allowance_policy,
                    ProviderAttempt(
                        id=identifier,
                        capability="embedding",
                        model_id=request.profile.model_id,
                        subject_hash=sha256(trusted_subject.encode("utf-8")).hexdigest(),
                        estimated_input_bytes=sum(
                            len(text.encode("utf-8")) for text in request.texts
                        ),
                        item_count=len(request.texts),
                    ),
                )
                receipt = AttemptReservation.model_validate(receipt.model_dump(warnings=False))
                if receipt.attempt_id != identifier:
                    raise AIAccountingError("conflict")
                if not receipt.newly_reserved or receipt.finalized:
                    raise AIAccountingError("duplicate")
                ledger_attempt = identifier
            remaining = request.response_timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise EmbeddingTransportError("timeout")
            with self._lock:
                if self._closed:
                    raise EmbeddingTransportError("disabled")
            bounded_request = request.model_copy(
                update={
                    "response_timeout_seconds": remaining,
                    "connect_timeout_seconds": min(request.connect_timeout_seconds, remaining),
                }
            )
            provider_started = time.monotonic()
            try:
                received = self.transport.embed(bounded_request)
            finally:
                provider_duration_ms = max(0, int((time.monotonic() - provider_started) * 1000))
            checked = EmbeddingTransportResult.model_validate(received.model_dump(warnings=False))
            with self._lock:
                if checked.input_tokens is None:
                    self._missing += 1
                else:
                    self._observed += checked.input_tokens
                usage_recorded = True
            if time.monotonic() - started >= request.response_timeout_seconds:
                raise EmbeddingTransportError("timeout")
            if len(checked.vectors) != len(request.texts):
                raise EmbeddingTransportError("invalid_response")
            vectors = tuple(UnitEmbedding.from_raw(vector) for vector in checked.vectors)
            with self._lock:
                if self._closed:
                    raise EmbeddingTransportError("disabled")
            result = EmbeddingBatchResult(
                status="success",
                profile=request.profile,
                purpose=purpose,
                input_sha256=tuple(text_digest(text) for text in request.texts),
                vectors=vectors,
                source=self.transport.source,
                input_tokens=checked.input_tokens,
                observed_provider_revision=checked.observed_provider_revision,
            )
        except EmbeddingTransportError as exc:
            error = exc.code
        except AIAccountingError as exc:
            error = (
                "budget_exhausted"
                if exc.code == "depleted"
                else "rate_limited"
                if exc.code == "saturated"
                else "accounting_unavailable"
            )
        except Exception:
            error = (
                "accounting_unavailable"
                if self.settings.mode == "gemini_free"
                and self.ledger is not None
                and ledger_attempt is None
                else "invalid_response"
            )
        finally:
            if ledger_attempt is not None and self.ledger is not None:
                try:
                    ledger_error: ClientErrorCode | None = (
                        "rate_limited" if error == "concurrency_limit" else error
                    )
                    self.ledger.finish(
                        ledger_attempt,
                        ProviderUsage(
                            status="success"
                            if error is None
                            else "timeout"
                            if error == "timeout"
                            else "error",
                            error_code=ledger_error,
                            input_tokens=checked.input_tokens if checked else None,
                            output_tokens=None,
                            accounted_cost_microusd=0,
                            provider_duration_ms=provider_duration_ms,
                        ),
                    )
                except Exception:
                    # Durable pending lease remains consumed; never refund or retry.
                    error = "accounting_unavailable"
            with self._lock:
                self._missing += int(not usage_recorded)
                self._active -= 1
                self._idle.notify_all()
            self._close_idle()
        with self._lock:
            if self._closed:
                return unavailable("disabled")
            if error is None and time.monotonic() - started >= request.response_timeout_seconds:
                error = "timeout"
            if result is not None and error is None:
                self._successes += 1
        return (
            result
            if result is not None and error is None
            else unavailable(error or "invalid_response")
        )
