"""Durable lease ownership across real worker/provider cancellation boundaries."""

import asyncio
import hashlib
from datetime import UTC, datetime
from threading import Event, RLock
from uuid import uuid4

import anyio
import pytest

from app.ai.accounting import AdmissionLease, AdmissionPolicy, AIAccountingError
from app.core.errors import ApplicationError
from app.core.feedback_middleware import FeedbackSecurityMiddleware
from app.schemas.evidence_feedback import FeedbackCompletion
from app.services.feedback_operations import (
    FeedbackOperations,
    SharedIngressJobs,
    acquire_shared_lease_async,
    wait_for_shared_job,
)
from tests.feedback_fixtures import feedback_request
from tests.unit.test_feedback_operations import principal, settings


def policy(scope="synthetic-worker"):
    return AdmissionPolicy(
        scope=scope,
        global_requests_per_minute=100,
        subject_requests_per_minute=100,
        max_global_in_flight=1,
        max_subject_in_flight=1,
    )


class Admission:
    def __init__(self):
        self.lock = RLock()
        self.active = set()
        self.subjects = []
        self.releases = []
        self.acquire_error = self.release_error = None
        self.entered, self.release_entered = Event(), Event()
        self.block_acquire = None

    def acquire(self, configured, subject_hash):
        self.entered.set()
        if self.block_acquire is not None:
            assert self.block_acquire.wait(5)
        with self.lock:
            if self.acquire_error:
                raise self.acquire_error
            if self.active:
                raise AIAccountingError("saturated")
            lease = AdmissionLease(id=uuid4(), admitted_at=datetime.now(UTC))
            self.active.add(lease.id)
            self.subjects.append(subject_hash)
            return lease

    def release(self, lease_id):
        with self.lock:
            if self.release_error:
                raise self.release_error
            assert lease_id in self.active
            self.active.remove(lease_id)
            self.releases.append(lease_id)
            self.release_entered.set()


def test_optional_pair_is_explicit_and_subject_identity_is_hashed():
    admission = Admission()
    with pytest.raises(ValueError):
        FeedbackOperations(settings(), shared_admission=admission)
    with pytest.raises(ValueError):
        FeedbackOperations(settings(), admission_policy=policy())
    owner = principal()
    operations = FeedbackOperations(
        settings(), shared_admission=admission, admission_policy=policy()
    )
    try:
        assert operations.run(owner, lambda: "safe") == "safe"
        assert admission.subjects == [
            hashlib.sha256(f"account:{owner.account.id}".encode()).hexdigest()
        ]
        assert not admission.active and len(admission.releases) == 1
    finally:
        operations.close()


@pytest.mark.parametrize(
    "code,status",
    [("saturated", 429), ("depleted", 429), ("unavailable", 503), ("policy_mismatch", 503)],
)
def test_shared_rejection_precedes_work_and_is_sanitized(code, status):
    admission = Admission()
    admission.acquire_error = AIAccountingError(code)
    operations = FeedbackOperations(
        settings(), shared_admission=admission, admission_policy=policy()
    )
    try:
        with pytest.raises(ApplicationError) as error:
            operations.run(principal(), lambda: pytest.fail("Rejected shared admission ran work"))
        assert error.value.status_code == status
        assert operations.wait_for_idle(0)
    finally:
        operations.close()


def test_release_failure_keeps_unknown_lease_and_blocks_new_local_admission():
    admission = Admission()
    admission.release_error = RuntimeError("synthetic-private-accounting-canary")
    operations = FeedbackOperations(
        settings(), shared_admission=admission, admission_policy=policy()
    )
    try:
        with pytest.raises(ApplicationError) as error:
            operations.run(principal(), lambda: "must not escape cleanup failure")
        assert error.value.status_code == 503
        assert "synthetic-private" not in str(error.value)
        assert admission.active and not operations.accounting_available
        with pytest.raises(ApplicationError) as blocked:
            operations.run(principal(), lambda: pytest.fail("Unavailable accounting ran work"))
        assert blocked.value.status_code == 503
    finally:
        operations.close()


def test_accounting_degradation_during_operation_withholds_its_result():
    operations = FeedbackOperations(settings())

    def work():
        operations._accounting_failed()
        return "must not escape degraded admission"

    try:
        with pytest.raises(ApplicationError) as error:
            operations.run(principal(), work)
        assert error.value.status_code == 503
        assert operations.wait_for_idle(0)
    finally:
        operations.close()


def test_http_cancellation_does_not_release_actual_shared_worker_lease():
    admission = Admission()
    operations = FeedbackOperations(
        settings(), shared_admission=admission, admission_policy=policy()
    )
    entered, release = Event(), Event()

    def blocked():
        entered.set()
        assert release.wait(5)

    async def scenario():
        task = asyncio.create_task(operations.execute(principal(), blocked))
        assert await anyio.to_thread.run_sync(entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert admission.active and not admission.releases
        release.set()
        assert await anyio.to_thread.run_sync(operations.wait_for_idle, 5)
        assert not admission.active and len(admission.releases) == 1

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        operations.close()


def test_timed_out_background_provider_retains_shared_lease_across_two_instances():
    admission = Admission()
    first = FeedbackOperations(
        settings(provider_timeout_seconds=0.1),
        shared_admission=admission,
        admission_policy=policy(),
    )
    second = FeedbackOperations(settings(), shared_admission=admission, admission_policy=policy())
    entered, release = Event(), Event()

    class Provider:
        def explain(self, request):
            entered.set()
            assert release.wait(5)
            return FeedbackCompletion(
                status="unavailable", text=None, source="test_fixture", error_code="disabled"
            )

    try:
        provider = first.bounded_provider(Provider())
        with pytest.raises(TimeoutError):
            first.run(principal(), lambda: provider.explain(feedback_request()))
        assert entered.is_set() and admission.active and not admission.releases
        with pytest.raises(ApplicationError) as error:
            second.run(principal(), lambda: pytest.fail("Other worker bypassed provider lease"))
        assert error.value.status_code == 429
        release.set()
        assert first.wait_for_idle(5)
        assert second.run(principal(), lambda: "capacity restored") == "capacity restored"
    finally:
        release.set()
        first.close()
        second.close()


def request_scope():
    return {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/sessions/synthetic/feedback",
        "headers": [],
        "state": {},
        "query_string": b"",
    }


async def invoke(middleware):
    messages = []
    received = False

    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": b"{}", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    await middleware(request_scope(), receive, send)
    return messages


def test_ingress_factory_is_deferred_and_ingress_ownership_transfers_to_real_worker():
    admission = Admission()
    calls = []
    entered, release = Event(), Event()
    operations = FeedbackOperations(
        settings(request_timeout_seconds=1, provider_timeout_seconds=0.5)
    )

    def blocked():
        entered.set()
        assert release.wait(5)
        return "late"

    async def app(scope, receive, send):
        await operations.execute_account(
            uuid4(), blocked, deadline=scope["state"]["feedback_deadline"]
        )
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"private-late-result"})

    middleware = FeedbackSecurityMiddleware(
        app,
        settings(request_timeout_seconds=0.2, provider_timeout_seconds=0.1),
        shared_admission_factory=lambda: (
            calls.append(True) or (admission, policy("synthetic-ingress"))
        ),
    )
    assert not calls

    async def scenario():
        messages = await invoke(middleware)
        assert entered.is_set()
        assert messages[0]["status"] == 504
        assert b"private-late-result" not in b"".join(m.get("body", b"") for m in messages)
        assert admission.active and not admission.releases
        release.set()
        assert await anyio.to_thread.run_sync(operations.wait_for_idle, 5)
        assert not admission.active and len(admission.releases) == 1

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        operations.close()


def test_late_ingress_acquire_after_timeout_is_released_only_after_it_really_finishes():
    admission = Admission()
    gate = Event()
    admission.block_acquire = gate

    async def forbidden(scope, receive, send):
        pytest.fail("A timed-out admission must not invoke the application")

    middleware = FeedbackSecurityMiddleware(
        forbidden,
        settings(request_timeout_seconds=0.2, provider_timeout_seconds=0.1),
        shared_admission_factory=lambda: (admission, policy("late-acquire")),
    )

    async def scenario():
        messages = await invoke(middleware)
        assert admission.entered.is_set() and messages[0]["status"] == 504
        assert not admission.releases
        gate.set()
        assert await anyio.to_thread.run_sync(admission.release_entered.wait, 5)
        assert not admission.active and len(admission.releases) == 1

    try:
        asyncio.run(scenario())
    finally:
        gate.set()


def test_middleware_unavailable_factory_fails_closed_without_raw_diagnostics():
    async def forbidden(scope, receive, send):
        pytest.fail("Unavailable admission invoked application")

    def unavailable():
        raise RuntimeError("synthetic-private-database-canary")

    middleware = FeedbackSecurityMiddleware(
        forbidden, settings(), shared_admission_factory=unavailable
    )
    messages = asyncio.run(invoke(middleware))
    assert messages[0]["status"] == 503
    assert b"synthetic-private" not in b"".join(m.get("body", b"") for m in messages)


@pytest.mark.parametrize("blocked_stage", ["acquire", "release"])
def test_shutdown_waits_for_actual_ingress_sql_cleanup_after_http_timeout(blocked_stage):
    gate, entered, cleaned = Event(), Event(), Event()
    disposed, released_after_disposal = [], []
    tracker = SharedIngressJobs(max_workers=1)

    class BlockedAdmission(Admission):
        def acquire(self, configured, subject_hash):
            if blocked_stage == "acquire":
                entered.set()
                assert gate.wait(5)
            return super().acquire(configured, subject_hash)

        def release(self, lease_id):
            if blocked_stage == "release":
                entered.set()
                assert gate.wait(5)
            released_after_disposal.append(bool(disposed))
            super().release(lease_id)
            cleaned.set()

    admission = BlockedAdmission()

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"must not escape late cleanup"})

    middleware = FeedbackSecurityMiddleware(
        app,
        settings(request_timeout_seconds=0.1, provider_timeout_seconds=0.05),
        shared_admission_factory=lambda: (admission, policy("shutdown-ingress")),
        shared_admission_tracker_factory=lambda: tracker,
    )

    async def scenario():
        messages = await invoke(middleware)
        assert entered.is_set() and messages[0]["status"] == 504
        assert b"must not escape" not in b"".join(m.get("body", b"") for m in messages)
        tracker.close()
        assert not tracker.wait_for_idle(0)
        gate.set()
        assert await anyio.to_thread.run_sync(tracker.wait_for_idle, 5)
        disposed.append(True)
        assert cleaned.is_set() and released_after_disposal == [False]
        assert not admission.active

    try:
        asyncio.run(scenario())
    finally:
        gate.set()
        tracker.close()
        assert tracker.wait_for_idle(5)


def test_canceled_queued_ingress_job_stays_owned_before_its_thread_starts():
    gate = Event()
    tracker = SharedIngressJobs(max_workers=1, max_pending=2)
    first, queued = Admission(), Admission()
    first.block_acquire = gate

    async def scenario():
        initial = asyncio.create_task(
            acquire_shared_lease_async(
                first, policy("first"), "0" * 64, lambda: None, tracker=tracker
            )
        )
        assert await anyio.to_thread.run_sync(first.entered.wait, 5)
        waiting = asyncio.create_task(
            acquire_shared_lease_async(
                queued, policy("queued"), "1" * 64, lambda: None, tracker=tracker
            )
        )
        # The synchronous submit runs before the task first suspends.
        await asyncio.sleep(0)
        assert not queued.entered.is_set()
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        with pytest.raises(ApplicationError) as saturated:
            await acquire_shared_lease_async(
                Admission(), policy("third"), "2" * 64, lambda: None, tracker=tracker
            )
        assert saturated.value.status_code == 429
        tracker.close()
        assert not tracker.wait_for_idle(0)
        gate.set()
        lease = await initial
        lease.release()
        assert await anyio.to_thread.run_sync(tracker.wait_for_idle, 5)
        assert queued.entered.is_set() and len(queued.releases) == 1
        assert not first.active and not queued.active
        with pytest.raises(ApplicationError) as closed:
            await acquire_shared_lease_async(
                Admission(), policy("closed"), "3" * 64, lambda: None, tracker=tracker
            )
        assert closed.value.status_code == 503

    try:
        asyncio.run(scenario())
    finally:
        gate.set()
        tracker.close()
        assert tracker.wait_for_idle(5)


def test_tracked_release_failure_finishes_real_job_without_refunding_unknown_lease():
    tracker, admission, failures = SharedIngressJobs(), Admission(), []
    admission.release_error = RuntimeError("synthetic-private-release-canary")

    async def scenario():
        lease = await acquire_shared_lease_async(
            admission, policy(), "4" * 64, lambda: failures.append(True), tracker=tracker
        )
        tracker.close()
        assert not tracker.wait_for_idle(0)
        with pytest.raises(ApplicationError) as error:
            await wait_for_shared_job(tracker.release(lease, strict=True))
        assert error.value.status_code == 503 and "synthetic-private" not in str(error.value)
        assert tracker.wait_for_idle(0)
        assert admission.active and not admission.releases and failures == [True]

    try:
        asyncio.run(scenario())
    finally:
        tracker.close()
        assert tracker.wait_for_idle(5)
