"""App-owned admission and bounded provider waits for the feedback HTTP boundary.

Process-local bounds may be paired with durable admission shared across workers.
Timed-out synchronous work retains both leases until it really finishes; Python
threads are not killed. Network adapters must also enforce transport deadlines.
"""

import asyncio
import hashlib
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import partial
from threading import Condition, Event, RLock
from typing import TypeVar
from uuid import UUID

import anyio

from app.ai.accounting import AdmissionPolicy, AIAccountingError, SharedAdmission
from app.ai.evidence_feedback import EvidenceFeedbackProvider
from app.core.errors import ApplicationError
from app.core.feedback_settings import FeedbackSettings
from app.domain.accounts import Principal
from app.schemas.evidence_feedback import FeedbackCompletion, FeedbackRequest

T = TypeVar("T")
type Subject = tuple[str, UUID]


def admission_failure(error: Exception) -> ApplicationError:
    if isinstance(error, AIAccountingError) and error.code in {"saturated", "depleted"}:
        return ApplicationError("feedback_busy", "AI services are busy. Try again later.", 429)
    return ApplicationError("dependency_unavailable", "AI admission is unavailable.", 503)


class SharedLeaseOwnership:
    """One durable lease, retained by every actual owner until cleanup completes."""

    def __init__(
        self,
        admission: SharedAdmission,
        lease_id: UUID,
        on_failure: Callable[[], None],
        on_finished: Callable[[], None] | None = None,
    ) -> None:
        self.admission, self.lease_id = admission, lease_id
        self._lock = RLock()
        self._references = 1
        self._failed = False
        self._callbacks: tuple[Callable[[], None], ...] = (on_failure,)
        self._on_finished = on_finished

    @property
    def failed(self) -> bool:
        with self._lock:
            return self._failed

    def retain(self, on_failure: Callable[[], None] | None = None) -> None:
        with self._lock:
            if self._references == 0 or self._failed:
                raise ApplicationError(
                    "dependency_unavailable", "AI admission is unavailable.", 503
                )
            self._references += 1
            if on_failure is not None:
                self._callbacks += (on_failure,)

    def release(self, *, strict: bool = True) -> None:
        with self._lock:
            if self._references == 0:
                return
            self._references -= 1
            if self._references:
                return
        try:
            self.admission.release(self.lease_id)
        except Exception:
            with self._lock:
                self._failed = True
                callbacks = self._callbacks
            for callback in callbacks:
                with suppress(Exception):
                    callback()
            if strict:
                raise ApplicationError(
                    "dependency_unavailable", "AI admission is unavailable.", 503
                ) from None
        finally:
            if self._on_finished is not None:
                self._on_finished()


class SharedIngressJobs:
    """Lifespan-owned ingress work, including canceled acquisition and final release.

    Reservations precede executor submission. A successful acquisition transfers
    that reservation to the durable lease's final owner, so neither a canceled
    HTTP coroutine nor a not-yet-started thread can evade application draining.
    """

    def __init__(self, *, max_workers: int = 4, max_pending: int = 128) -> None:
        if not 1 <= max_workers <= 32 or not 1 <= max_pending <= 512:
            raise ValueError("Ingress executor bounds must be explicit and bounded")
        self._lock = RLock()
        self._idle = Condition(self._lock)
        self._closed = False
        self._pending = 0
        self._max_pending = max_pending
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="trace-ingress"
        )

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if not self._pending:
                self._executor.shutdown(wait=False)

    def wait_for_idle(self, timeout: float | None = None) -> bool:
        with self._idle:
            return self._idle.wait_for(lambda: self._pending == 0, timeout=timeout)

    def acquire(
        self,
        admission: SharedAdmission,
        policy: AdmissionPolicy,
        subject_hash: str,
        on_failure: Callable[[], None],
    ) -> Future[SharedLeaseOwnership]:
        finished = False

        def finish() -> None:
            nonlocal finished
            with self._idle:
                if finished:
                    return
                finished = True
                self._pending -= 1
                self._idle.notify_all()
                if self._closed and not self._pending:
                    self._executor.shutdown(wait=False)

        def work() -> SharedLeaseOwnership:
            try:
                return acquire_shared_lease(
                    admission, policy, subject_hash, on_failure, on_finished=finish
                )
            except BaseException:
                finish()
                raise

        with self._lock:
            if self._closed:
                raise ApplicationError(
                    "dependency_unavailable", "AI admission is unavailable.", 503
                )
            if self._pending >= self._max_pending:
                raise ApplicationError(
                    "feedback_busy", "AI services are busy. Try again later.", 429
                )
            self._pending += 1
            try:
                return self._executor.submit(work)
            except BaseException:
                finish()
                raise

    def release(self, lease: SharedLeaseOwnership, *, strict: bool) -> Future[None]:
        # Existing leases retain their reservation across close. Their cleanup
        # must still run before the executor or its database can be disposed.
        with self._lock:
            return self._executor.submit(partial(lease.release, strict=strict))


INGRESS_SHARED_LEASE: ContextVar[SharedLeaseOwnership | None] = ContextVar(
    "trace_shared_ingress_lease", default=None
)
type SharedAdmissionFactory = Callable[[], tuple[SharedAdmission, AdmissionPolicy] | None]
type SharedIngressJobsFactory = Callable[[], SharedIngressJobs]


async def wait_for_shared_job[T](future: Future[T]) -> T:
    """Cancellation stops waiting, never cancels a lifespan-owned SQL future."""
    wrapped = asyncio.wrap_future(future)
    # A canceled HTTP waiter cannot consume a later failure. Retrieve it without
    # logging; an active waiter still receives the same sanitized exception.
    wrapped.add_done_callback(lambda result: None if result.cancelled() else result.exception())
    return await asyncio.shield(wrapped)


def acquire_shared_lease(
    admission: SharedAdmission,
    policy: AdmissionPolicy,
    subject_hash: str,
    on_failure: Callable[[], None],
    *,
    on_finished: Callable[[], None] | None = None,
) -> SharedLeaseOwnership:
    try:
        lease = admission.acquire(policy, subject_hash)
        return SharedLeaseOwnership(admission, lease.id, on_failure, on_finished)
    except Exception as error:
        raise admission_failure(error) from None


async def acquire_shared_lease_async(
    admission: SharedAdmission,
    policy: AdmissionPolicy,
    subject_hash: str,
    on_failure: Callable[[], None],
    *,
    tracker: SharedIngressJobs | None = None,
) -> SharedLeaseOwnership:
    # If cancellation races a committed acquire, cleanup owns the eventual result.
    # Never lose a lease merely because the HTTP coroutine stopped waiting.
    lock = RLock()
    abandoned = False
    pending: SharedLeaseOwnership | None = None

    def acquired(lease: SharedLeaseOwnership) -> SharedLeaseOwnership:
        nonlocal pending
        with lock:
            late = abandoned
            if not late:
                pending = lease
        if late:
            lease.release(strict=False)
        return lease

    def acquire() -> SharedLeaseOwnership:
        return acquired(acquire_shared_lease(admission, policy, subject_hash, on_failure))

    try:
        if tracker is None:
            lease = await anyio.to_thread.run_sync(acquire, abandon_on_cancel=True)
        else:
            future = tracker.acquire(admission, policy, subject_hash, on_failure)

            def finished(result: Future[SharedLeaseOwnership]) -> None:
                if not result.cancelled() and result.exception() is None:
                    acquired(result.result())

            future.add_done_callback(finished)
            lease = await wait_for_shared_job(future)
        with lock:
            pending = None
        return lease
    except BaseException:
        with lock:
            abandoned = True
            stranded, pending = pending, None
        if stranded is not None:
            if tracker is not None:
                await wait_for_shared_job(tracker.release(stranded, strict=False))
            else:
                with anyio.CancelScope(shield=True):
                    await anyio.to_thread.run_sync(partial(stranded.release, strict=False))
        raise


@dataclass
class _SubjectState:
    requests: deque[float] = field(default_factory=deque)
    workers: int = 0
    providers: int = 0


@dataclass
class _Context:
    subject: Subject
    deadline: float
    provider_deadline: float | None = None
    leases: tuple[SharedLeaseOwnership, ...] = ()


class _DeadlineProvider:
    def __init__(self, owner: "FeedbackOperations", provider: EvidenceFeedbackProvider) -> None:
        self.owner, self.provider = owner, provider

    def explain(self, request: FeedbackRequest) -> FeedbackCompletion:
        return self.owner._explain(self.provider, request)


class FeedbackOperations:
    def __init__(
        self,
        settings: FeedbackSettings,
        *,
        clock: Callable[[], float] = time.monotonic,
        shared_admission: SharedAdmission | None = None,
        admission_policy: AdmissionPolicy | None = None,
    ) -> None:
        self.settings = FeedbackSettings.model_validate(settings.model_dump(warnings=False))
        self.clock = clock
        if (shared_admission is None) != (admission_policy is None):
            raise ValueError("Shared admission requires both an adapter and an explicit policy")
        self.shared_admission = shared_admission
        self.admission_policy = (
            AdmissionPolicy.model_validate(admission_policy.model_dump())
            if admission_policy
            else None
        )
        self._accounting_unavailable = False
        self._lock = RLock()
        self._idle = Condition(self._lock)
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

    @property
    def accounting_available(self) -> bool:
        with self._lock:
            return not self._accounting_unavailable

    def _accounting_failed(self) -> None:
        with self._lock:
            self._accounting_unavailable = True

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)

    def wait_for_idle(self, timeout: float | None = None) -> bool:
        """Drain real leases, including work abandoned by an HTTP cancellation."""
        with self._idle:
            return self._idle.wait_for(
                lambda: self._workers == 0 and self._providers == 0, timeout=timeout
            )

    def remaining_seconds(self, *, provider: bool = True) -> float:
        """One admitted request budget; multiple provider calls never reset it."""
        context = self._context.get()
        if context is None or self.closed or not self.accounting_available:
            raise ApplicationError("dependency_unavailable", "AI operation is unavailable.", 503)
        with self._lock:
            now = self.clock()
            deadline = context.deadline
            if provider:
                if context.provider_deadline is None:
                    context.provider_deadline = min(
                        deadline, now + self.settings.provider_timeout_seconds
                    )
                deadline = min(deadline, context.provider_deadline)
            remaining = deadline - now
            if remaining <= 0:
                raise TimeoutError("AI operation deadline exceeded")
            return remaining

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
            if self._accounting_unavailable:
                raise ApplicationError(
                    "dependency_unavailable", "AI admission is unavailable.", 503
                )
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
        return self._run(self._subject(principal), operation, deadline=deadline)

    def _run(
        self, subject: Subject, operation: Callable[[], T], *, deadline: float | None = None
    ) -> T:
        limit = self.clock() + self.settings.request_timeout_seconds
        if deadline is not None:
            limit = min(limit, deadline)
        state = self._admit(subject, limit)
        context = _Context(subject, limit)
        token = None
        try:
            ingress = INGRESS_SHARED_LEASE.get()
            if ingress is not None:
                ingress.retain(self._accounting_failed)
                context.leases += (ingress,)
            if self.shared_admission is not None and self.admission_policy is not None:
                digest = hashlib.sha256(f"{subject[0]}:{subject[1]}".encode()).hexdigest()
                context.leases += (
                    acquire_shared_lease(
                        self.shared_admission,
                        self.admission_policy,
                        digest,
                        self._accounting_failed,
                    ),
                )
            if self.clock() >= limit:
                raise ApplicationError("request_timeout", "Feedback request timed out.", 504)
            if self.closed or not self.accounting_available:
                raise ApplicationError("dependency_unavailable", "Feedback is unavailable.", 503)
            token = self._context.set(context)
            result = operation()
            if self.clock() >= limit:
                raise ApplicationError("request_timeout", "Feedback request timed out.", 504)
            if self.closed or not self.accounting_available:
                raise ApplicationError("dependency_unavailable", "Feedback is unavailable.", 503)
            return result
        finally:
            if token is not None:
                self._context.reset(token)
            failed = False
            try:
                for lease in reversed(context.leases):
                    lease.release(strict=False)
                    failed = failed or lease.failed
            finally:
                with self._lock:
                    state.workers -= 1
                    self._workers -= 1
                    self._idle.notify_all()
            if failed:
                raise ApplicationError(
                    "dependency_unavailable", "AI admission is unavailable.", 503
                )

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

    async def execute_account(
        self, account_id: UUID, operation: Callable[[], T], *, deadline: float | None = None
    ) -> T:
        """Admit an authenticated account without creating a learner history."""
        if not isinstance(account_id, UUID):
            raise ApplicationError("unauthenticated", "Account authentication is required.", 401)
        limit = self.clock() + self.settings.request_timeout_seconds
        if deadline is not None:
            limit = min(limit, deadline)
        return await anyio.to_thread.run_sync(
            partial(self._run, ("account", account_id), operation, deadline=limit),
            abandon_on_cancel=True,
        )

    def _explain(
        self, provider: EvidenceFeedbackProvider, request: FeedbackRequest
    ) -> FeedbackCompletion:
        context = self._context.get()
        if context is None:
            raise RuntimeError("Feedback provider requires admitted operation context")
        self.remaining_seconds(provider=True)
        with self._lock:
            assert context.provider_deadline is not None
            provider_deadline = min(context.deadline, context.provider_deadline)
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
            retained: list[SharedLeaseOwnership] = []
            try:
                for lease in context.leases:
                    lease.retain()
                    retained.append(lease)
                future = self._executor.submit(
                    self._provider_call, provider, request, provider_deadline
                )
            except Exception:
                for lease in reversed(retained):
                    lease.release(strict=False)
                state.providers -= 1
                self._providers -= 1
                raise RuntimeError("Feedback provider is unavailable") from None

            cleaned = Event()

            def finished(_: Future[FeedbackCompletion]) -> None:
                try:
                    for lease in reversed(retained):
                        lease.release(strict=False)
                finally:
                    with self._lock:
                        state.providers -= 1
                        self._providers -= 1
                        self._idle.notify_all()
                    cleaned.set()

            future.add_done_callback(finished)
        try:
            result = future.result(timeout=max(0, provider_deadline - self.clock()))
            if not cleaned.wait(timeout=max(0, provider_deadline - self.clock())):
                raise TimeoutError("Feedback provider cleanup deadline exceeded")
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
