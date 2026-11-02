"""App-owned admission and bounded provider waits for the feedback HTTP boundary.

Limits are process-local, not distributed quotas. Timed-out synchronous work
retains its worker/provider lease until it really finishes; Python threads are
not killed. Future network adapters must also enforce real transport deadlines.
"""

import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import partial
from threading import RLock
from typing import TypeVar
from uuid import UUID

import anyio

from app.ai.evidence_feedback import EvidenceFeedbackProvider
from app.core.errors import ApplicationError
from app.core.feedback_settings import FeedbackSettings
from app.domain.accounts import Principal
from app.schemas.evidence_feedback import FeedbackCompletion, FeedbackRequest

T = TypeVar("T")
type Subject = tuple[str, UUID]


@dataclass
class _SubjectState:
    requests: deque[float] = field(default_factory=deque)
    workers: int = 0
    providers: int = 0


@dataclass(frozen=True)
class _Context:
    subject: Subject
    deadline: float


class _DeadlineProvider:
    def __init__(self, owner: "FeedbackOperations", provider: EvidenceFeedbackProvider) -> None:
        self.owner, self.provider = owner, provider

    def explain(self, request: FeedbackRequest) -> FeedbackCompletion:
        return self.owner._explain(self.provider, request)


class FeedbackOperations:
    def __init__(
        self, settings: FeedbackSettings, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.settings = FeedbackSettings.model_validate(settings.model_dump(warnings=False))
        self.clock = clock
        self._lock = RLock()
        self._subjects: dict[Subject, _SubjectState] = {}
        self._workers = self._providers = 0
        self._closed = False
        self._context: ContextVar[_Context | None] = ContextVar("feedback_operation", default=None)
        # Admission precedes submit, bounding outstanding futures and executor queue.
        self._executor = ThreadPoolExecutor(
            max_workers=self.settings.max_global_in_flight, thread_name_prefix="trace-feedback"
        )

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _subject(principal: Principal) -> Subject:
        # Authorization/ownership remain in existing dependencies and C1. This is
        # only a stable quota identity, never a caller-supplied key/header.
        if principal.account is not None and principal.credential is None:
            return "account", principal.account.id
        if principal.credential is not None and principal.account is None:
            return "guest", principal.learner_id
        raise ApplicationError("unauthenticated", "Learner authentication is required.", 401)

    @staticmethod
    def _busy() -> ApplicationError:
        return ApplicationError("feedback_busy", "Feedback is busy. Try again later.", 429)

    def _admit(self, subject: Subject, deadline: float) -> _SubjectState:
        with self._lock:
            now = self.clock()
            if now >= deadline:
                raise ApplicationError("request_timeout", "Feedback request timed out.", 504)
            if self._closed:
                raise ApplicationError("dependency_unavailable", "Feedback is unavailable.", 503)
            for key, old_state in tuple(self._subjects.items()):
                while old_state.requests and old_state.requests[0] <= now - 60:
                    old_state.requests.popleft()
                if not old_state.requests and not old_state.workers and not old_state.providers:
                    del self._subjects[key]
            state = self._subjects.get(subject)
            if state is None:
                if len(self._subjects) >= self.settings.max_subjects:
                    raise self._busy()
                state = self._subjects[subject] = _SubjectState()
            if len(state.requests) >= self.settings.requests_per_minute:
                raise ApplicationError(
                    "feedback_rate_limited", "Too many feedback requests. Try again later.", 429
                )
            state.requests.append(now)
            if (
                state.workers >= self.settings.max_subject_in_flight
                or state.providers
                or self._workers >= self.settings.max_global_in_flight
            ):
                raise self._busy()
            state.workers += 1
            self._workers += 1
            return state

    def run(
        self, principal: Principal, operation: Callable[[], T], *, deadline: float | None = None
    ) -> T:
        limit = self.clock() + self.settings.request_timeout_seconds
        if deadline is not None:
            limit = min(limit, deadline)
        subject = self._subject(principal)
        state = self._admit(subject, limit)
        token = self._context.set(_Context(subject, limit))
        try:
            result = operation()
            if self.clock() >= limit:
                raise ApplicationError("request_timeout", "Feedback request timed out.", 504)
            if self.closed:
                raise ApplicationError("dependency_unavailable", "Feedback is unavailable.", 503)
            return result
        finally:
            self._context.reset(token)
            with self._lock:
                state.workers -= 1
                self._workers -= 1

    async def execute(
        self, principal: Principal, operation: Callable[[], T], *, deadline: float | None = None
    ) -> T:
        limit = self.clock() + self.settings.request_timeout_seconds
        if deadline is not None:
            limit = min(limit, deadline)
        # Cancellation may stop waiting, never release the actual worker's lease.
        # A queued worker checks the original deadline before starting any work.
        return await anyio.to_thread.run_sync(
            partial(self.run, principal, operation, deadline=limit), abandon_on_cancel=True
        )

    def bounded_provider(self, provider: EvidenceFeedbackProvider) -> EvidenceFeedbackProvider:
        return _DeadlineProvider(self, provider)

    def _explain(
        self, provider: EvidenceFeedbackProvider, request: FeedbackRequest
    ) -> FeedbackCompletion:
        context = self._context.get()
        if context is None:
            raise RuntimeError("Feedback provider requires admitted operation context")
        with self._lock:
            provider_deadline = min(
                context.deadline, self.clock() + self.settings.provider_timeout_seconds
            )
            remaining = provider_deadline - self.clock()
            if remaining <= 0:
                raise TimeoutError("Feedback provider deadline exceeded")
            state = self._subjects[context.subject]
            if (
                self._closed
                or state.providers >= self.settings.max_subject_in_flight
                or self._providers >= self.settings.max_global_in_flight
            ):
                raise RuntimeError("Feedback provider is unavailable")
            state.providers += 1
            self._providers += 1
            try:
                future = self._executor.submit(
                    self._provider_call, provider, request, provider_deadline
                )
            except Exception:
                state.providers -= 1
                self._providers -= 1
                raise RuntimeError("Feedback provider is unavailable") from None

            def finished(_: Future[FeedbackCompletion]) -> None:
                with self._lock:
                    state.providers -= 1
                    self._providers -= 1

            future.add_done_callback(finished)
        try:
            result = future.result(timeout=max(0, provider_deadline - self.clock()))
        except TimeoutError:
            # Cancel only if it has not begun. Running work retains the callback's
            # lease and cannot be replaced with another provider call for this subject.
            future.cancel()
            raise TimeoutError("Feedback provider deadline exceeded") from None
        if self.clock() >= provider_deadline or self.closed:
            raise TimeoutError("Feedback provider deadline exceeded")
        return result

    def _provider_call(
        self, provider: EvidenceFeedbackProvider, request: FeedbackRequest, deadline: float
    ) -> FeedbackCompletion:
        if self.clock() >= deadline or self.closed:
            raise TimeoutError("Feedback provider deadline exceeded")
        return provider.explain(request)
