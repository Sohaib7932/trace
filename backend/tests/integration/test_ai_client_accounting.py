"""Actual SQL ledger with fake AI I/O; never a credential or paid/live request."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

from sqlalchemy import select

from app.ai.accounting import AIAccountingError, AllowancePolicy, AttemptReservation
from app.ai.client import BoundedAIClient
from app.db import accounting_models as m
from app.db.accounting import SqlAIControls
from app.db.learning import SqlLearningRepository
from app.schemas.ai_client import TransportCompletion
from tests.unit.test_gemini_transport import MODEL, config


class OfflineAI:
    source = "ai"

    def __init__(self, completion=None, during_call=None):
        self.calls = []
        self.closed = 0
        self.completion = completion or TransportCompletion(
            text="Public synthetic guidance",
            returned_model_id=MODEL,
            request_id="provider-fixture-correlation",
            input_tokens=7,
            output_tokens=2,
            cost_microusd=0,
        )
        self.during_call = during_call

    def complete(self, request):
        self.calls.append(request)
        if self.during_call:
            self.during_call()
        return self.completion

    def close(self):
        self.closed += 1


def call(client):
    return client.complete(
        capability="tutor",
        instructions="Trusted synthetic policy",
        data={"question": "public synthetic question"},
        subject="private-subject-canary",
    )


def client(controls, transport, **limits):
    return BoundedAIClient(
        config(),
        transport,
        ledger=controls,
        allowance_policy=AllowancePolicy(scope="client-controlled-test-v1", **limits),
    )


def test_client_reserves_and_finishes_without_holding_db_across_io(database):
    def independent_write():
        assert database.engine.pool.checkedout() == 0
        with SqlLearningRepository(database).write():
            pass

    transport = OfflineAI(during_call=independent_write)
    result = call(client(SqlAIControls(database), transport))
    assert result.status == "success" and len(transport.calls) == 1
    with database.session() as session:
        row = session.scalar(select(m.AIProviderAttempt))
        usage = session.get(m.AIProviderUsage, row.id)
        assert usage.input_tokens == 7 and usage.output_tokens == 2
        assert str(row.id) != result.request_id
        for table in (m.AIControlPolicy, m.AIProviderAttempt, m.AIProviderUsage):
            serialized = str(session.execute(select(table.__table__)).all())
            assert "private-subject-canary" not in serialized
            assert (
                "synthetic question" not in serialized
                and "Trusted synthetic policy" not in serialized
            )


def test_two_client_instances_cannot_reset_shared_allowance(database):
    controls = SqlAIControls(database)
    for _ in range(2):
        assert call(client(controls, OfflineAI(), max_attempts=2)).status == "success"
    transport = OfflineAI()
    result = call(client(SqlAIControls(database), transport, max_attempts=2))
    assert result.error_code == "budget_exhausted" and not transport.calls


def test_finalization_failure_withholds_output_and_retains_reservation(database):
    controls = SqlAIControls(database)

    class BrokenFinalization:
        reserve = controls.reserve

        def finish(self, *_):
            raise AIAccountingError("unavailable")

    transport = OfflineAI()
    result = call(client(BrokenFinalization(), transport, max_in_flight=1))
    assert result.status == "unavailable" and result.error_code == "accounting_unavailable"
    assert result.text is None and len(transport.calls) == 1
    with database.session() as session:
        attempt = session.scalar(select(m.AIProviderAttempt))
        assert session.get(m.AIProviderUsage, attempt.id) is None
    other = OfflineAI()
    assert call(client(controls, other, max_in_flight=1)).error_code == "rate_limited"
    assert not other.calls


def test_duplicate_attempt_never_authorizes_another_provider_call():
    class Duplicate:
        def reserve(self, policy, attempt):
            return AttemptReservation(attempt_id=attempt.id, newly_reserved=False, finalized=False)

        def finish(self, *_):
            raise AssertionError("A duplicate must not finalize somebody else's work")

    transport = OfflineAI()
    result = call(client(Duplicate(), transport))
    assert result.error_code == "accounting_unavailable" and not transport.calls


def test_unknown_accounting_exception_is_sanitized_and_prevents_provider(capsys, caplog):
    class Broken:
        def reserve(self, *_):
            raise RuntimeError("private-database-credential-canary")

        def finish(self, *_):
            raise AssertionError("No reservation exists")

    transport = OfflineAI()
    result = call(client(Broken(), transport))
    assert result.status == "unavailable" and result.error_code == "accounting_unavailable"
    assert not transport.calls
    assert (
        "private-database" not in result.model_dump_json() + capsys.readouterr().err + caplog.text
    )


def test_close_and_admission_lease_wait_for_real_ledger_finalization(database):
    controls = SqlAIControls(database)
    entered, release = Event(), Event()

    class Delayed:
        reserve = controls.reserve

        def finish(self, identifier, usage):
            entered.set()
            assert release.wait(5)
            controls.finish(identifier, usage)

    transport = OfflineAI()
    owned = client(Delayed(), transport)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(call, owned)
        try:
            assert entered.wait(5)
            owned.close()
            assert owned.diagnostics_snapshot().in_flight == 1
            assert transport.closed == 0 and not future.done()
        finally:
            release.set()
        assert future.result(timeout=5).error_code == "disabled"
    assert owned.wait_for_idle(0) and transport.closed == 1


def test_reported_cost_violation_is_preserved_and_blocks_later_clients(database):
    controls = SqlAIControls(database)
    transport = OfflineAI(
        TransportCompletion(
            text="Public fixture",
            returned_model_id=MODEL,
            input_tokens=1,
            output_tokens=1,
            cost_microusd=1,
        )
    )
    assert call(client(controls, transport)).error_code == "budget_exhausted"
    with database.session() as session:
        assert session.scalar(select(m.AIProviderUsage.accounted_cost_microusd)) == 1
    other = OfflineAI()
    assert call(client(controls, other)).error_code == "budget_exhausted"
    assert not other.calls


def test_provider_latency_excludes_reservation_and_finalization(database):
    now = [0.0]
    controls = SqlAIControls(database)

    class TimedLedger:
        def reserve(self, *args):
            now[0] += 5
            return controls.reserve(*args)

        def finish(self, *args):
            now[0] += 4
            controls.finish(*args)

    def provider():
        now[0] += 0.25

    owned = BoundedAIClient(
        config(),
        OfflineAI(during_call=provider),
        clock=lambda: now[0],
        ledger=TimedLedger(),
        allowance_policy=AllowancePolicy(scope="timing-test"),
    )
    assert call(owned).status == "success"
    with database.session() as session:
        assert session.scalar(select(m.AIProviderUsage.provider_duration_ms)) == 250


def test_late_ledger_finalization_cannot_release_output_after_total_deadline(database):
    now = [0.0]
    controls = SqlAIControls(database)

    class DelayedLedger:
        reserve = controls.reserve

        def finish(self, *args):
            controls.finish(*args)
            now[0] = 21

    owned = BoundedAIClient(
        config(),
        OfflineAI(),
        clock=lambda: now[0],
        ledger=DelayedLedger(),
        allowance_policy=AllowancePolicy(scope="late-finalization-test"),
    )
    result = call(owned)
    assert result.error_code == "timeout" and result.text is None
    with database.session() as session:
        assert session.scalar(select(m.AIProviderUsage.status)) == "success"
