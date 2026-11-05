"""Durable controls contract, also reused against actual PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.ai.accounting import (
    AdmissionPolicy,
    AIAccountingError,
    AllowancePolicy,
    ProviderAttempt,
    ProviderUsage,
)
from app.core.ai_settings import GEMINI_MODEL
from app.db import accounting_models as m
from app.db import models as legacy
from app.db.accounting import SqlAIControls
from app.db.migrations import migration_config
from app.db.session import Database


def attempt(subject="synthetic-subject", **changes):
    return ProviderAttempt(
        **(
            dict(
                id=uuid4(),
                capability="tutor",
                model_id=GEMINI_MODEL,
                subject_hash=sha256(subject.encode()).hexdigest(),
                estimated_input_bytes=128,
                item_count=1,
            )
            | changes
        )
    )


def usage(**changes):
    return ProviderUsage(
        **(
            dict(status="success", input_tokens=10, output_tokens=3, accounted_cost_microusd=0)
            | changes
        )
    )


def policy(**changes):
    return AllowancePolicy(**(dict(scope="controlled-pilot-v1") | changes))


def admission(**changes):
    return AdmissionPolicy(
        **(
            dict(
                scope="controlled-pilot-v1:tutor:operation",
                global_requests_per_minute=10,
                subject_requests_per_minute=5,
                max_global_in_flight=2,
                max_subject_in_flight=1,
            )
            | changes
        )
    )


def test_provider_reservation_duplicate_and_finish_are_idempotent(database):
    controls = SqlAIControls(database)
    item = attempt()
    assert controls.reserve(policy(), item).newly_reserved
    repeated = controls.reserve(policy(), item)
    assert not repeated.newly_reserved and not repeated.finalized
    controls.finish(item.id, usage())
    controls.finish(item.id, usage())
    assert controls.reserve(policy(), item).finalized
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(m.AIProviderAttempt)) == 1
        assert session.scalar(select(func.count()).select_from(m.AIProviderUsage)) == 1
    with pytest.raises(AIAccountingError) as error:
        controls.finish(item.id, usage(input_tokens=11))
    assert error.value.code == "conflict"


def test_scope_configuration_cannot_silently_reset_or_increase_allowance(database):
    controls = SqlAIControls(database)
    item = attempt()
    controls.reserve(policy(max_attempts=1), item)
    controls.finish(item.id, usage())
    with pytest.raises(AIAccountingError) as changed:
        controls.reserve(policy(max_attempts=2), attempt())
    assert changed.value.code == "policy_mismatch"
    with pytest.raises(AIAccountingError) as depleted:
        controls.reserve(policy(max_attempts=1), attempt())
    assert depleted.value.code == "depleted"


def test_allowance_and_pending_lease_survive_new_client_instances(database, settings):
    item = attempt()
    controls = SqlAIControls(database)
    limits = policy(max_attempts=2)
    controls.reserve(limits, item)
    other = Database(settings)
    try:
        resumed = SqlAIControls(other)
        with pytest.raises(AIAccountingError) as busy:
            resumed.reserve(limits, attempt())
        assert busy.value.code == "saturated"
        resumed.finish(item.id, usage())
        second = attempt()
        resumed.reserve(limits, second)
        resumed.finish(second.id, usage())
        with pytest.raises(AIAccountingError) as depleted:
            SqlAIControls(database).reserve(limits, attempt())
        assert depleted.value.code == "depleted"
    finally:
        other.dispose()


def test_unknown_usage_is_not_fabricated_as_zero_and_embedding_counts_one_rpc(database):
    controls = SqlAIControls(database)
    item = attempt(capability="embedding", model_id="gemini-embedding-001", item_count=113)
    controls.reserve(policy(), item)
    controls.finish(item.id, ProviderUsage(status="refusal"))
    with database.session() as session:
        row = session.get(m.AIProviderUsage, item.id)
        assert row.input_tokens is None and row.output_tokens is None
        assert row.accounted_cost_microusd is None
        assert session.get(m.AIProviderAttempt, item.id).item_count == 113
        assert session.scalar(select(func.count()).select_from(m.AIProviderAttempt)) == 1


def test_cross_instance_provider_admission_is_atomic(database):
    limits = policy(max_attempts=100, max_in_flight=4, requests_per_minute=100)

    def reserve(number):
        try:
            SqlAIControls(database).reserve(limits, attempt(str(number)))
            return "admitted"
        except AIAccountingError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(reserve, range(12)))
    assert results.count("admitted") == 4
    assert results.count("saturated") == 8


def test_fixed_utc_rate_window_uses_database_time_and_does_not_refund_calls(database, monkeypatch):
    now = [datetime(2026, 11, 3, 23, 59, 59, tzinfo=UTC)]
    monkeypatch.setattr(SqlAIControls, "_now", staticmethod(lambda _: now[0]))
    controls = SqlAIControls(database)
    limits = policy(requests_per_minute=1)
    first = attempt()
    controls.reserve(limits, first)
    controls.finish(first.id, usage())
    with pytest.raises(AIAccountingError) as busy:
        controls.reserve(limits, attempt())
    assert busy.value.code == "saturated"
    now[0] += timedelta(seconds=1)
    assert controls.reserve(limits, attempt()).newly_reserved
    with database.session() as session:
        windows = session.scalars(
            select(m.AIProviderAttempt.window_start).order_by(m.AIProviderAttempt.admitted_at)
        ).all()
    assert windows == [datetime(2026, 11, 3, 23, 59, tzinfo=UTC), datetime(2026, 11, 4, tzinfo=UTC)]


def test_shared_route_global_subject_and_rate_limits_release_only_actual_work(
    database, monkeypatch
):
    # Limits are per clock minute: freeze the clock so a rollover mid-test cannot flake.
    frozen = datetime.now(UTC).replace(second=30, microsecond=0)
    monkeypatch.setattr(SqlAIControls, "_now", staticmethod(lambda _: frozen))
    controls = SqlAIControls(database)
    limits = admission(global_requests_per_minute=3, subject_requests_per_minute=3)
    a, b, c = [sha256(label.encode()).hexdigest() for label in ("a", "b", "c")]
    first = controls.acquire(limits, a)
    with pytest.raises(AIAccountingError) as subject_busy:
        SqlAIControls(database).acquire(limits, a)
    assert subject_busy.value.code == "saturated"
    second = controls.acquire(limits, b)
    with pytest.raises(AIAccountingError):
        controls.acquire(limits, c)
    controls.release(first.id)
    controls.release(first.id)
    third = controls.acquire(limits, c)
    controls.release(second.id)
    controls.release(third.id)
    with pytest.raises(AIAccountingError) as rate:
        controls.acquire(limits, a)
    assert rate.value.code == "saturated"
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(m.AIAdmissionRelease)) == 3


def test_control_records_are_immutable_at_database_boundary(database):
    controls = SqlAIControls(database)
    item = attempt()
    controls.reserve(policy(), item)
    with pytest.raises(IntegrityError), database.session() as session, session.begin():
        session.execute(update(m.AIProviderAttempt).values(estimated_input_bytes=0))
    with pytest.raises(IntegrityError), database.session() as session, session.begin():
        session.execute(update(m.AIControlPolicy).values(configuration={}))


def test_audited_admin_reconciliation_releases_unknown_work_without_refund(database):
    controls = SqlAIControls(database)
    limits = policy(max_attempts=1)
    item = attempt()
    controls.reserve(limits, item)
    with pytest.raises(AIAccountingError):
        controls.reconcile("provider", item.id, uuid4())
    now = datetime.now(UTC)
    with database.session() as session, session.begin():
        admin = legacy.User(status="active", created_at=now, updated_at=now)
        session.add(admin)
        session.flush()
        identity = admin.id
        session.add(legacy.UserRole(user_id=identity, role="admin"))
    assert controls.reconcile("provider", item.id, identity)
    assert not controls.reconcile("provider", item.id, identity)
    with database.session() as session:
        row = session.get(m.AIProviderUsage, item.id)
        assert row.status == "unknown" and row.input_tokens is None
        assert session.scalar(select(func.count()).select_from(m.AIControlReconciliation)) == 1
    with pytest.raises(AIAccountingError) as depleted:
        controls.reserve(limits, attempt())
    assert depleted.value.code == "depleted"


def test_control_migration_rejects_history_loss(database):
    controls = SqlAIControls(database)
    controls.reserve(policy(), attempt())
    config = migration_config(database.engine.dialect.name)
    with (
        pytest.raises(RuntimeError, match="AI control history"),
        database.engine.begin() as connection,
    ):
        config.attributes["connection"] = connection
        command.downgrade(config, "0008_knowledge_archive")


def test_missing_serialization_gate_fails_closed(database):
    with database.session() as session, session.begin():
        session.execute(delete(legacy.WriteGate))
    with pytest.raises(AIAccountingError) as failure:
        SqlAIControls(database).reserve(policy(), attempt())
    assert failure.value.code == "unavailable"
