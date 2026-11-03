"""Feedback-only ingress limits, response deadlines, no-store and safe errors."""

import asyncio
import hashlib
import json
import re
import time
from collections import deque
from collections.abc import Callable
from functools import partial
from threading import RLock
from uuid import uuid4

import anyio
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.ai.accounting import AdmissionPolicy
from app.core.errors import ApplicationError, error_response
from app.core.feedback_settings import FeedbackSettings
from app.services.feedback_operations import (
    INGRESS_SHARED_LEASE,
    SharedAdmissionFactory,
    SharedIngressJobs,
    SharedIngressJobsFactory,
    SharedLeaseOwnership,
    acquire_shared_lease_async,
    wait_for_shared_job,
)

_PATH = re.compile(r"/api/v1/sessions/[^/]+/feedback/?\Z")
_ERRORS: dict[int, tuple[str, str]] = {
    401: ("unauthenticated", "Learner authentication is required."),
    403: ("forbidden", "Feedback access is denied."),
    404: ("not_found", "Session not found."),
    405: ("method_not_allowed", "Method not allowed."),
    409: ("feedback_changed", "Saved work changed. Refresh progress and try again."),
    413: ("request_too_large", "Feedback request body is too large."),
    422: ("validation_error", "Feedback request validation failed."),
    429: ("feedback_rate_limited", "Too many feedback requests. Try again later."),
    500: ("internal_error", "Feedback could not be completed."),
    503: ("dependency_unavailable", "Feedback is unavailable. Try again later."),
    504: ("request_timeout", "Feedback request timed out."),
}


class FeedbackSecurityMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        settings: FeedbackSettings,
        allowed_origins: tuple[str, ...] = (),
        *,
        clock: Callable[[], float] = time.monotonic,
        path_pattern: str | None = None,
        deadline_key: str = "feedback_deadline",
        error_subject: str = "Feedback",
        error_code_prefix: str = "feedback",
        shared_admission_factory: SharedAdmissionFactory | None = None,
        shared_admission_tracker_factory: SharedIngressJobsFactory | None = None,
    ) -> None:
        self.app, self.settings, self.allowed_origins = app, settings, allowed_origins
        self.clock = clock
        self._path = re.compile(path_pattern) if path_pattern is not None else _PATH
        self._deadline_key = deadline_key
        self._error_subject = error_subject
        self._error_code_prefix = error_code_prefix
        self.shared_admission_factory = shared_admission_factory
        self.shared_admission_tracker_factory = shared_admission_tracker_factory
        self._accounting_unavailable = False
        self._lock = RLock()
        self._requests: deque[float] = deque()
        self._active = 0

    def _accounting_failed(self) -> None:
        with self._lock:
            self._accounting_unavailable = True

    def _admit(self) -> bool:
        with self._lock:
            now = self.clock()
            while self._requests and self._requests[0] <= now - 60:
                self._requests.popleft()
            if (
                len(self._requests) >= self.settings.ingress_requests_per_minute
                or self._active >= self.settings.max_ingress_in_flight
            ):
                return False
            self._requests.append(now)
            self._active += 1
            return True

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._path.fullmatch(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        state = scope.setdefault("state", {})
        request_id = state.setdefault("request_id", str(uuid4()))
        state[self._deadline_key] = self.clock() + self.settings.request_timeout_seconds
        origin = next(
            (v.decode("latin-1") for k, v in scope["headers"] if k.lower() == b"origin"), ""
        )
        response_started = False

        async def protected_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                headers = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() not in {b"cache-control", b"pragma", b"expires"}
                ]
                headers += [
                    (b"cache-control", b"no-store"),
                    (b"pragma", b"no-cache"),
                    (b"expires", b"0"),
                ]
                # This middleware wraps CORS so its own early errors need CORS too.
                if origin in self.allowed_origins and not any(
                    k.lower() == b"access-control-allow-origin" for k, _ in headers
                ):
                    headers += [
                        (b"access-control-allow-origin", origin.encode("latin-1")),
                        (b"access-control-allow-credentials", b"true"),
                        (b"vary", b"Origin"),
                    ]
                if origin in self.allowed_origins and not any(
                    k.lower() == b"access-control-expose-headers" for k, _ in headers
                ):
                    headers.append((b"access-control-expose-headers", b"X-Request-ID"))
                message = {**message, "headers": headers}
                response_started = True
            await send(message)

        async def failure(status: int, busy: bool = False) -> None:
            code, text = _ERRORS.get(status, _ERRORS[500])
            if busy and status == 429:
                code, text = "feedback_busy", "Feedback is busy. Try again later."
            if self._error_subject != "Feedback":
                code = code.replace("feedback", self._error_code_prefix)
                text = text.replace("Feedback", self._error_subject).replace(
                    "feedback", self._error_code_prefix
                )
            response = error_response(request_id, code, text, status)
            await response(scope, receive, protected_send)

        if self._accounting_unavailable:
            await failure(503)
            return
        if not self._admit():
            await failure(429)
            return
        shared_lease: SharedLeaseOwnership | None = None
        shared_tracker: SharedIngressJobs | None = None
        lease_released = False
        ingress_token = None

        async def release_ingress(*, strict: bool) -> None:
            nonlocal lease_released
            if shared_lease is not None and not lease_released:
                lease_released = True
                if shared_tracker is not None:
                    await wait_for_shared_job(shared_tracker.release(shared_lease, strict=strict))
                else:
                    with anyio.CancelScope(shield=True):
                        await anyio.to_thread.run_sync(partial(shared_lease.release, strict=strict))

        try:
            async with asyncio.timeout(self.settings.request_timeout_seconds):
                if self.shared_admission_factory is not None:
                    try:
                        configured = self.shared_admission_factory()
                        if configured is not None:
                            shared_admission, policy = configured
                            if self.shared_admission_tracker_factory is not None:
                                shared_tracker = self.shared_admission_tracker_factory()
                            policy = AdmissionPolicy.model_validate(policy.model_dump())
                            # Ingress has no authenticated principal yet. A constant
                            # nonpersonal identity gives a shared route-family cap.
                            subject_hash = hashlib.sha256(
                                b"trace-unidentified-ingress-v1"
                            ).hexdigest()
                            shared_lease = await acquire_shared_lease_async(
                                shared_admission,
                                policy,
                                subject_hash,
                                self._accounting_failed,
                                tracker=shared_tracker,
                            )
                            ingress_token = INGRESS_SHARED_LEASE.set(shared_lease)
                    except ApplicationError:
                        raise
                    except Exception:
                        raise ApplicationError(
                            "dependency_unavailable", "AI admission is unavailable.", 503
                        ) from None
                body = bytearray()
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    body.extend(message.get("body", b""))
                    if len(body) > self.settings.max_request_bytes:
                        await failure(413)
                        return
                    if not message.get("more_body", False):
                        break
                replayed = False

                async def replay() -> Message:
                    nonlocal replayed
                    if not replayed:
                        replayed = True
                        return {"type": "http.request", "body": bytes(body), "more_body": False}
                    return await receive()

                start: Message | None = None
                chunks = bytearray()

                async def collect(message: Message) -> None:
                    nonlocal start
                    if message["type"] == "http.response.start":
                        start = message
                    elif message["type"] == "http.response.body":
                        chunks.extend(message.get("body", b""))
                        if len(chunks) > self.settings.max_response_bytes:
                            raise ValueError("Feedback output exceeds its bound")

                await self.app(scope, replay, collect)
                if start is None:
                    raise ValueError("Feedback response was not completed")
                if self.clock() >= state[self._deadline_key]:
                    await failure(504)
                    return
                await release_ingress(strict=True)
                if self.clock() >= state[self._deadline_key]:
                    await failure(504)
                    return
                status = start["status"]
                if status >= 400:
                    busy = False
                    if status == 429:
                        try:
                            parsed = json.loads(chunks)
                            busy = parsed.get("error", {}).get("code") == "feedback_busy"
                        except (ValueError, AttributeError):
                            pass
                    await failure(status, busy)
                else:
                    await protected_send(start)
                    await protected_send(
                        {"type": "http.response.body", "body": bytes(chunks), "more_body": False}
                    )
        except ApplicationError as error:
            if response_started:
                raise
            await failure(error.status_code, error.status_code == 429)
        except TimeoutError:
            if response_started:
                raise
            await failure(504)
        except Exception:
            if response_started:
                raise
            await failure(500)
        finally:
            if ingress_token is not None:
                INGRESS_SHARED_LEASE.reset(ingress_token)
            try:
                await release_ingress(strict=False)
            finally:
                with self._lock:
                    self._active -= 1
