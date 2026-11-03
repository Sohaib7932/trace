"""Failed acquisition and repeated lifespans preserve actual resource ownership."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ai.accounting import AdmissionLease, AdmissionPolicy
from app.core.accounting_settings import AccountingSettings
from app.core.ai_settings import AIClientSettings
from app.core.embedding_settings import EmbeddingSettings
from app.core.errors import ApplicationError
from app.core.feedback_settings import FeedbackSettings
from app.main import create_app
from app.services.feedback_operations import FeedbackOperations, SharedIngressJobs


class TrackingVerifier:
    def __init__(self):
        self.closed = False
        self.close_count = 0

    def close(self):
        if not self.closed:
            self.closed = True
            self.close_count += 1

    def wait_for_idle(self, timeout=None):
        return True


@pytest.fixture
def owned_verifiers(monkeypatch):
    created = []

    def construct(*args, **kwargs):
        verifier = TrackingVerifier()
        created.append(verifier)
        return verifier

    monkeypatch.setattr("app.main.JwtVerifier", construct)
    return created


def disabled_app(settings, **kwargs):
    return create_app(
        settings,
        ai_settings=AIClientSettings(_env_file=None, mode="disabled"),
        embedding_settings=EmbeddingSettings(_env_file=None, mode="disabled"),
        **kwargs,
    )


def test_invalid_derived_scope_fails_before_verifier_or_database_allocation(settings):
    # The base scope is valid, but derived worker/ingress namespaces exceed 96.
    accounting = AccountingSettings(_env_file=None, mode="durable", scope="x" * 96)
    with (
        patch("app.main.JwtVerifier") as verifier,
        patch("app.main.Database") as database,
        pytest.raises(ValidationError),
    ):
        disabled_app(settings, accounting_settings=accounting)
    verifier.assert_not_called()
    database.assert_not_called()


def test_database_acquisition_failure_releases_owner_and_next_lifespan_is_fresh(
    settings, database, owned_verifiers
):
    app = disabled_app(settings)
    first = owned_verifiers[0]

    async def scenario():
        with pytest.raises(RuntimeError, match="Synthetic database acquisition failure"):
            async with app.router.lifespan_context(app):
                pytest.fail("A failed database acquisition cannot start the application")
        assert first.closed and first.close_count == 1
        async with app.router.lifespan_context(app):
            assert len(owned_verifiers) == 2
            assert app.state.jwt_verifier is owned_verifiers[1]
            assert not owned_verifiers[1].closed
        assert owned_verifiers[1].closed and owned_verifiers[1].close_count == 1

    with (
        patch(
            "app.main.Database",
            side_effect=[RuntimeError("Synthetic database acquisition failure"), database],
        ),
        patch.object(database, "dispose", wraps=database.dispose) as dispose,
    ):
        asyncio.run(scenario())
        dispose.assert_called_once()


def test_second_pool_failure_closes_first_pool_created_database_and_owned_verifier(
    settings, database, owned_verifiers
):
    app = disabled_app(settings)
    first_pool = FeedbackOperations(FeedbackSettings(_env_file=None))

    async def scenario():
        with pytest.raises(RuntimeError, match="Synthetic second pool failure"):
            async with app.router.lifespan_context(app):
                pytest.fail("A partial operation pool allocation cannot start the application")

    with (
        patch("app.main.Database", return_value=database),
        patch(
            "app.main.FeedbackOperations",
            side_effect=[first_pool, RuntimeError("Synthetic second pool failure")],
        ) as constructor,
        patch.object(first_pool, "close", wraps=first_pool.close) as close,
        patch.object(database, "dispose", wraps=database.dispose) as dispose,
    ):
        asyncio.run(scenario())
        assert constructor.call_count == 2
        close.assert_called_once()
        assert first_pool.closed and first_pool.wait_for_idle(0)
        dispose.assert_called_once()
    assert owned_verifiers[0].closed and owned_verifiers[0].close_count == 1


@pytest.mark.parametrize("shape", ["repeated", "nested"])
@pytest.mark.parametrize("state_override", [False, True])
def test_lifespans_close_only_actual_owned_verifiers_after_final_owner(
    settings, database, owned_verifiers, shape, state_override
):
    app = disabled_app(settings, database=database)
    owned = owned_verifiers[0]
    caller = TrackingVerifier()
    if state_override:
        app.state.jwt_verifier = caller

    async def scenario():
        async with app.router.lifespan_context(app):
            assert not owned.closed
            if shape == "nested":
                async with app.router.lifespan_context(app):
                    assert not owned.closed and len(owned_verifiers) == 1
                assert not owned.closed  # The outer owner still needs its verifier.
        assert owned.closed and owned.close_count == 1
        if shape == "repeated":
            async with app.router.lifespan_context(app):
                if state_override:
                    assert app.state.jwt_verifier is caller
                    assert len(owned_verifiers) == 1
                else:
                    assert len(owned_verifiers) == 2
                    assert app.state.jwt_verifier is owned_verifiers[1]
                    assert not owned_verifiers[1].closed
        assert all(item.closed and item.close_count == 1 for item in owned_verifiers)
        assert not caller.closed and caller.close_count == 0

    with patch.object(database, "dispose", wraps=database.dispose) as dispose:
        asyncio.run(scenario())
        dispose.assert_not_called()  # A caller-owned fixture DB is never disposed by the app.


def test_explicitly_injected_verifier_stays_caller_owned(settings, database, owned_verifiers):
    caller = TrackingVerifier()
    app = disabled_app(settings, database=database, jwt_verifier=caller)

    async def scenario():
        async with app.router.lifespan_context(app):
            assert app.state.jwt_verifier is caller
        async with app.router.lifespan_context(app):
            assert app.state.jwt_verifier is caller

    asyncio.run(scenario())
    assert not owned_verifiers and not caller.closed and caller.close_count == 0


def test_durable_ingress_tracker_is_closed_and_replaced_across_lifespans(
    settings, database, owned_verifiers
):
    app = disabled_app(
        settings,
        database=database,
        accounting_settings=AccountingSettings(
            _env_file=None, mode="durable", scope="startup-cleanup-fixture"
        ),
    )
    policy = AdmissionPolicy(
        scope="synthetic-ingress",
        global_requests_per_minute=4,
        subject_requests_per_minute=2,
        max_global_in_flight=2,
        max_subject_in_flight=1,
    )
    released, failures, trackers = [], [], []

    class SyntheticAdmission:
        def acquire(self, policy, subject_hash):
            return AdmissionLease(id=uuid4(), admitted_at=datetime.now(UTC))

        def release(self, lease_id):
            released.append(lease_id)

    admission = SyntheticAdmission()

    async def scenario():
        for _ in range(2):
            async with app.router.lifespan_context(app):
                jobs = app.state.shared_ingress_jobs
                assert isinstance(jobs, SharedIngressJobs)
                assert all(jobs is not previous for previous in trackers)
                trackers.append(jobs)
                lease = jobs.acquire(
                    admission, policy, "a" * 64, lambda: failures.append(True)
                ).result(timeout=5)
                jobs.release(lease, strict=True).result(timeout=5)
                assert jobs.wait_for_idle(0)
            with pytest.raises(ApplicationError) as error:
                jobs.acquire(admission, policy, "a" * 64, lambda: failures.append(True))
            assert error.value.status_code == 503

    asyncio.run(scenario())
    assert len(trackers) == len(released) == 2 and not failures
    assert all(item.closed and item.close_count == 1 for item in owned_verifiers)
