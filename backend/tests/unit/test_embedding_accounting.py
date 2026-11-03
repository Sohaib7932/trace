"""Embedding admission/usage integration with an artificial transport, never live calls."""

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Event
from uuid import uuid4

import pytest

from app.ai.accounting import AIAccountingError, AllowancePolicy, AttemptReservation
from app.ai.embeddings import BoundedEmbeddingClient, EmbeddingTransportError
from app.core.embedding_settings import EmbeddingSettings
from tests.unit.test_embeddings import ControlledEmbeddings
from tests.unit.test_embeddings import (
    isolate_embedding_environment as isolate_embedding_environment,  # noqa: F401
)


class ArtificialLiveTransport(ControlledEmbeddings):
    """The ai source contract is injected only to exercise free-mode accounting."""

    source = "ai"


class LedgerFixture:
    def __init__(self, reserve_error=None, finish_error=None, reservation=None, on_finish=None):
        self.reserve_error, self.finish_error = reserve_error, finish_error
        self.reservation, self.on_finish = reservation, on_finish
        self.attempts, self.usages, self.pending = [], [], set()

    def reserve(self, policy, attempt):
        self.attempts.append(attempt)
        if self.reserve_error:
            raise self.reserve_error
        if self.reservation:
            return self.reservation(attempt)
        self.pending.add(attempt.id)
        return AttemptReservation(attempt_id=attempt.id, newly_reserved=True, finalized=False)

    def finish(self, attempt_id, usage):
        self.usages.append((attempt_id, usage))
        if self.on_finish:
            self.on_finish()
        if self.finish_error:
            raise self.finish_error
        self.pending.remove(attempt_id)


def live_client(ledger, provider=None):
    return BoundedEmbeddingClient(
        EmbeddingSettings(
            _env_file=None,
            mode="gemini_free",
            free_tier_unbilled_project_confirmed=True,
        ),
        provider or ArtificialLiveTransport(),
        ledger=ledger,
        allowance_policy=AllowancePolicy(scope="embedding-unit-fixture"),
    )


def test_optional_ledger_and_policy_are_required_as_a_pair():
    settings = EmbeddingSettings(_env_file=None)
    with pytest.raises(ValueError):
        BoundedEmbeddingClient(settings, ledger=LedgerFixture())
    with pytest.raises(ValueError):
        BoundedEmbeddingClient(settings, allowance_policy=AllowancePolicy(scope="fixture"))


def test_each_rpc_reserves_server_identity_and_batch_size_without_raw_subject_or_inputs():
    ledger, provider = LedgerFixture(), ArtificialLiveTransport()
    client = live_client(ledger, provider)
    try:
        for _ in range(2):
            response = client.embed(
                ("public-question-canary", "another-public-passage"),
                "document",
                subject="trusted-subject-canary",
            )
            assert response.status == "success"
        assert len(ledger.attempts) == len(provider.calls) == len(ledger.usages) == 2
        first, second = ledger.attempts
        assert first.id != second.id and first.item_count == 2
        assert first.capability == "embedding" and first.model_id == "gemini-embedding-001"
        assert first.subject_hash == sha256(b"trusted-subject-canary").hexdigest()
        assert "canary" not in first.model_dump_json()
        assert first.estimated_input_bytes == len(b"public-question-canaryanother-public-passage")
        usage = ledger.usages[0][1]
        assert usage.status == "success" and usage.input_tokens is None
        assert usage.output_tokens is None and usage.accounted_cost_microusd == 0
        assert usage.provider_duration_ms is not None and usage.provider_duration_ms >= 0
        assert not ledger.pending
    finally:
        client.close()


@pytest.mark.parametrize(
    "code,expected",
    [
        ("duplicate", "accounting_unavailable"),
        ("saturated", "rate_limited"),
        ("depleted", "budget_exhausted"),
        ("unavailable", "accounting_unavailable"),
        ("conflict", "accounting_unavailable"),
        ("policy_mismatch", "accounting_unavailable"),
    ],
)
def test_rejected_durable_admission_never_calls_provider(code, expected):
    ledger, provider = (
        LedgerFixture(reserve_error=AIAccountingError(code)),
        ArtificialLiveTransport(),
    )
    client = live_client(ledger, provider)
    try:
        response = client.embed(("Public query",), "query")
        assert response.error_code == expected and not response.vectors
        assert not provider.calls and not ledger.usages
    finally:
        client.close()


@pytest.mark.parametrize("kind", ["wrong_id", "replay", "finalized"])
def test_inconsistent_or_replayed_reservation_is_not_used(kind):
    def reservation(attempt):
        return AttemptReservation(
            attempt_id=uuid4() if kind == "wrong_id" else attempt.id,
            newly_reserved=kind != "replay",
            finalized=kind == "finalized",
        )

    ledger, provider = LedgerFixture(reservation=reservation), ArtificialLiveTransport()
    client = live_client(ledger, provider)
    try:
        assert client.embed(("Public query",), "query").error_code == "accounting_unavailable"
        assert not provider.calls and not ledger.usages
    finally:
        client.close()


def test_finish_failure_withholds_valid_vectors_and_keeps_pending_lease_without_retry():
    ledger, provider = (
        LedgerFixture(finish_error=RuntimeError("private-ledger-canary")),
        ArtificialLiveTransport(),
    )
    client = live_client(ledger, provider)
    try:
        response = client.embed(("Public query",), "query")
        assert response.error_code == "accounting_unavailable" and response.vectors == ()
        assert "canary" not in response.model_dump_json()
        assert len(provider.calls) == 1 and ledger.pending == {ledger.attempts[0].id}
        assert client.usage_snapshot().successful_batches == 0
        assert client.wait_for_idle(0)
    finally:
        client.close()


def test_provider_timeout_is_finalized_only_after_transport_returns_and_never_refunded():
    ledger, provider = (
        LedgerFixture(),
        ArtificialLiveTransport(error=EmbeddingTransportError("timeout")),
    )
    client = live_client(ledger, provider)
    try:
        assert client.embed(("Public query",), "query").error_code == "timeout"
        assert len(provider.calls) == 1 and len(ledger.attempts) == 1
        usage = ledger.usages[0][1]
        assert usage.status == "timeout" and usage.error_code == "timeout"
        assert usage.input_tokens is None and usage.output_tokens is None
    finally:
        client.close()


def test_shutdown_waits_through_ledger_finalization_before_disposing_transport():
    entered, release = Event(), Event()
    provider = ArtificialLiveTransport()

    def on_finish():
        entered.set()
        assert release.wait(5)
        assert provider.closed == 0

    ledger = LedgerFixture(on_finish=on_finish)
    client = live_client(ledger, provider)
    with ThreadPoolExecutor(max_workers=1) as executor:
        work = executor.submit(client.embed, ("Public query",), "query")
        assert entered.wait(5)
        assert not client.wait_for_idle(0)
        client.stop_admission()
        assert client.embed(("Another query",), "query").error_code == "disabled"
        assert provider.closed == 0
        release.set()
        assert work.result(5).error_code == "disabled"
    assert client.wait_for_idle(0) and not ledger.pending
    client.close()
    assert provider.closed == 1
