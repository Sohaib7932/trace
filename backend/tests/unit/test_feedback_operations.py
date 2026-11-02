"""Real worker cancellation/deadline behavior; all providers are local fixtures."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import uuid4

import anyio
import pytest
from pydantic import ValidationError

from app.core.errors import ApplicationError
from app.core.feedback_settings import FeedbackSettings
from app.domain.accounts import Account, Principal
from app.domain.learning import Credential
from app.schemas.evidence_feedback import FeedbackCompletion
from app.services.feedback_operations import FeedbackOperations
from tests.feedback_fixtures import feedback_request


def principal():
    now = datetime.now(UTC)
    return Principal(
        uuid4(), now + timedelta(hours=1), Account(uuid4(), now, "active", ("learner",))
    )


def settings(**changes):
    return FeedbackSettings(_env_file=None, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"requests_per_minute": 0},
        {"requests_per_minute": True},
        {"max_global_in_flight": 33},
        {"max_subject_in_flight": 2, "max_global_in_flight": 1},
        {"max_subjects": 0},
        {"ingress_requests_per_minute": 0},
        {"max_ingress_in_flight": 65},
        {"provider_timeout_seconds": 9},
        {"request_timeout_seconds": 31},
        {"max_request_bytes": 16385},
        {"max_response_bytes": 262145},
        {"provider_timeout_seconds": float("nan")},
        {"provider_timeout_seconds": float("inf")},
        {"api_key": "private-key-canary"},
    ],
)
def test_settings_reject_unbounded_or_credential_configuration(changes):
    with pytest.raises(ValidationError) as error:
        settings(**changes)
    assert "private-key-canary" not in str(error.value)


def test_process_environment_integers_supported_without_loading_credentials(monkeypatch):
    monkeypatch.setenv("TRACE_FEEDBACK_REQUESTS_PER_MINUTE", "3")
    monkeypatch.setenv("UNRELATED_PROVIDER_KEY", "not-read-canary")
    configured = settings()
    assert configured.requests_per_minute == 3
    assert "not-read-canary" not in configured.model_dump_json()


def test_rolling_rate_window_and_subject_bound_recover_without_eviction_of_live_work():
    now = [100.0]
    operations = FeedbackOperations(
        settings(requests_per_minute=2, max_subjects=1), clock=lambda: now[0]
    )
    first, second = principal(), principal()
    try:
        assert operations.run(first, lambda: "first") == "first"
        now[0] = 130
        assert operations.run(first, lambda: "second") == "second"
        with pytest.raises(ApplicationError) as limited:
            operations.run(first, lambda: pytest.fail("Rate limit must precede work"))
        assert limited.value.status_code == 429 and limited.value.code == "feedback_rate_limited"
        with pytest.raises(ApplicationError) as full:
            operations.run(second, lambda: pytest.fail("Subject bound must precede work"))
        assert full.value.code == "feedback_busy"
        now[0] = 160
        assert operations.run(first, lambda: "one old request expired")
        now[0] = 221
        assert operations.run(second, lambda: "old inactive subject removed")
    finally:
        operations.close()


def test_guest_quota_key_survives_credential_renewal_and_account_key_is_distinct():
    owner = uuid4()
    expiry = datetime.now(UTC) + timedelta(hours=1)
    operations = FeedbackOperations(settings(requests_per_minute=1))
    guest = Principal(owner, expiry, credential=Credential(uuid4(), owner, expiry, None))
    renewed = Principal(owner, expiry, credential=Credential(uuid4(), owner, expiry, None))
    try:
        assert operations.run(guest, lambda: True)
        with pytest.raises(ApplicationError) as error:
            operations.run(renewed, lambda: False)
        assert error.value.code == "feedback_rate_limited"
        assert operations.run(principal(), lambda: True)
    finally:
        operations.close()


def test_same_subject_and_global_concurrency_are_rejected_while_worker_really_runs():
    operations = FeedbackOperations(settings(max_global_in_flight=1))
    entered, release = Event(), Event()
    first, second = principal(), principal()

    def blocked():
        entered.set()
        assert release.wait(5)
        return "finished"

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(operations.run, first, blocked)
            assert entered.wait(5)
            for owner in (first, second):
                with pytest.raises(ApplicationError) as error:
                    operations.run(owner, lambda: pytest.fail("Concurrency cap must precede work"))
                assert error.value.code == "feedback_busy"
            release.set()
            assert future.result(5) == "finished"
        assert operations.run(second, lambda: "capacity restored") == "capacity restored"
    finally:
        release.set()
        operations.close()


def test_failure_and_late_result_release_worker_but_never_return_late_content():
    now = [0.0]
    operations = FeedbackOperations(settings(), clock=lambda: now[0])
    owner = principal()

    def late():
        now[0] = 20
        return "private-late-result"

    try:
        with pytest.raises(ApplicationError) as error:
            operations.run(owner, late)
        assert error.value.status_code == 504 and "private-late-result" not in str(error.value)
        assert operations.run(owner, lambda: "next") == "next"
        with pytest.raises(ValueError):
            operations.run(owner, lambda: (_ for _ in ()).throw(ValueError("fixture error")))
        assert operations.run(owner, lambda: True)
    finally:
        operations.close()


def test_expired_queued_work_never_invokes_service_and_close_is_idempotent():
    operations = FeedbackOperations(settings(), clock=lambda: 50.0)
    try:
        with pytest.raises(ApplicationError) as error:
            operations.run(principal(), lambda: pytest.fail("Expired request ran"), deadline=49)
        assert error.value.status_code == 504
        operations.close()
        operations.close()
        with pytest.raises(ApplicationError) as error:
            operations.run(principal(), lambda: pytest.fail("Closed resource ran"))
        assert error.value.status_code == 503
    finally:
        operations.close()


def test_async_cancellation_retains_actual_worker_lease():
    operations = FeedbackOperations(settings(max_global_in_flight=1))
    entered, release, finished = Event(), Event(), Event()
    owner = principal()

    def blocked():
        entered.set()
        try:
            assert release.wait(5)
        finally:
            finished.set()

    async def scenario():
        task = asyncio.create_task(operations.execute(owner, blocked))
        assert await anyio.to_thread.run_sync(entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ApplicationError) as error:
            await operations.execute(owner, lambda: pytest.fail("Cancelled worker still owns slot"))
        assert error.value.code == "feedback_busy"
        release.set()
        assert await anyio.to_thread.run_sync(finished.wait, 5)

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        operations.close()


def test_provider_wait_is_bounded_and_timed_out_provider_keeps_subject_lease():
    operations = FeedbackOperations(settings(provider_timeout_seconds=0.03))
    entered, release = Event(), Event()
    owner = principal()

    class BlockedProvider:
        def explain(self, request):
            entered.set()
            assert release.wait(5)
            return FeedbackCompletion(
                status="unavailable", text=None, source="test_fixture", error_code="disabled"
            )

    bounded = operations.bounded_provider(BlockedProvider())
    try:
        with pytest.raises(TimeoutError, match="^Feedback provider deadline exceeded$"):
            operations.run(owner, lambda: bounded.explain(feedback_request()))
        assert entered.is_set()
        with pytest.raises(ApplicationError) as error:
            operations.run(owner, lambda: pytest.fail("Old provider still owns subject lease"))
        assert error.value.code == "feedback_busy"
        release.set()
        operations._executor.submit(lambda: None).result(5)
        assert operations.run(owner, lambda: "restored") == "restored"
    finally:
        release.set()
        operations.close()


def test_provider_result_after_its_budget_is_discarded_before_total_deadline():
    now = [10.0]
    operations = FeedbackOperations(settings(), clock=lambda: now[0])

    class LateProvider:
        def explain(self, request):
            now[0] = 13
            return FeedbackCompletion(
                status="unavailable", text=None, source="test_fixture", error_code="disabled"
            )

    try:
        provider = operations.bounded_provider(LateProvider())
        with pytest.raises(TimeoutError):
            operations.run(principal(), lambda: provider.explain(feedback_request()))
    finally:
        operations.close()


def test_provider_cannot_be_invoked_without_admitted_request_context():
    operations = FeedbackOperations(settings())

    class ForbiddenProvider:
        def explain(self, request):
            pytest.fail("Provider must require context")

    try:
        with pytest.raises(RuntimeError, match="admitted operation context"):
            operations.bounded_provider(ForbiddenProvider()).explain(feedback_request())
    finally:
        operations.close()
