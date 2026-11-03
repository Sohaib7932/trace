"""Accounting failures never admit work, fabricate usage or authorize recovery."""

from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.ai.accounting import AIAccountingError
from app.db import accounting_models as m
from app.db import models as legacy
from app.db.accounting import SqlAIControls
from tests.integration.test_ai_controls import admission, attempt, policy, usage


@pytest.mark.parametrize(
    "operation", ["reserve", "finish", "acquire", "release", "reconcile", "summary"]
)
def test_database_errors_are_sanitized_and_commit_no_control_records(
    database, monkeypatch, operation, capsys, caplog
):
    @contextmanager
    def unavailable():
        raise OperationalError(
            "synthetic-private-statement", {}, RuntimeError("synthetic-private-driver-error")
        )
        yield

    controls = SqlAIControls(database)
    identifier = uuid4()
    arguments = {
        "reserve": (policy(), attempt()),
        "finish": (identifier, usage()),
        "acquire": (admission(), sha256(b"synthetic-subject").hexdigest()),
        "release": (identifier,),
        "reconcile": ("provider", identifier, uuid4()),
        "summary": (policy().scope,),
    }
    with monkeypatch.context() as patch:
        patch.setattr(
            database, "consistent_read" if operation == "summary" else "session", unavailable
        )
        with pytest.raises(AIAccountingError) as error:
            getattr(controls, operation)(*arguments[operation])
    assert error.value.code == "unavailable"
    output = capsys.readouterr()
    assert "synthetic-private" not in str(error.value) + output.out + output.err + caplog.text
    with database.session() as session:
        for model in (
            m.AIControlPolicy,
            m.AIProviderAttempt,
            m.AIProviderUsage,
            m.AIAdmissionLease,
            m.AIAdmissionRelease,
            m.AIControlReconciliation,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_a_scope_cannot_change_from_provider_allowance_to_route_admission(database):
    controls = SqlAIControls(database)
    controls.reserve(policy(), attempt())
    with pytest.raises(AIAccountingError) as error:
        controls.acquire(admission(scope=policy().scope), sha256(b"synthetic").hexdigest())
    assert error.value.code == "policy_mismatch"
    with database.session() as session:
        assert session.get(m.AIControlPolicy, policy().scope).kind == "allowance"
        assert session.scalar(select(func.count()).select_from(m.AIAdmissionLease)) == 0


@pytest.mark.parametrize("change", ["metadata", "scope"])
def test_duplicate_attempt_cannot_change_payload_metadata_or_scope(database, change):
    controls = SqlAIControls(database)
    item = attempt()
    controls.reserve(policy(), item)
    changed_item = (
        item.model_copy(update={"estimated_input_bytes": item.estimated_input_bytes + 1})
        if change == "metadata"
        else item
    )
    changed_policy = policy(scope="different-approved-scope") if change == "scope" else policy()
    with pytest.raises(AIAccountingError) as error:
        controls.reserve(changed_policy, changed_item)
    assert error.value.code == "conflict"
    with database.session() as session:
        saved = session.get(m.AIProviderAttempt, item.id)
        assert (
            saved.scope == policy().scope
            and saved.estimated_input_bytes == item.estimated_input_bytes
        )
        assert session.scalar(select(func.count()).select_from(m.AIProviderAttempt)) == 1
        assert session.scalar(select(func.count()).select_from(m.AIControlPolicy)) == 1


@pytest.mark.parametrize("operation", ["finish", "release"])
def test_unknown_attempt_or_lease_cannot_create_a_finalization(database, operation):
    controls = SqlAIControls(database)
    with pytest.raises(AIAccountingError) as error:
        if operation == "finish":
            controls.finish(uuid4(), usage())
        else:
            controls.release(uuid4())
    assert error.value.code == "conflict"
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(m.AIProviderUsage)) == 0
        assert session.scalar(select(func.count()).select_from(m.AIAdmissionRelease)) == 0


@pytest.mark.parametrize("role,status", [("learner", "active"), ("admin", "disabled")])
def test_reconciliation_rechecks_active_database_admin_and_preserves_unknown_work(
    database, role, status
):
    controls = SqlAIControls(database)
    lease = controls.acquire(admission(), sha256(b"synthetic").hexdigest())
    now = datetime.now(UTC)
    with database.session() as session, session.begin():
        actor = legacy.User(status=status, created_at=now, updated_at=now)
        session.add(actor)
        session.flush()
        actor_id = actor.id
        session.add(legacy.UserRole(user_id=actor_id, role=role))
    with pytest.raises(AIAccountingError) as error:
        controls.reconcile("admission", lease.id, actor_id)
    assert error.value.code == "conflict"
    with database.session() as session:
        assert session.get(m.AIAdmissionLease, lease.id) is not None
        assert session.get(m.AIAdmissionRelease, lease.id) is None
        assert session.scalar(select(func.count()).select_from(m.AIControlReconciliation)) == 0


def test_admin_reconciliation_refuses_missing_or_already_finished_targets(database):
    controls = SqlAIControls(database)
    now = datetime.now(UTC)
    with database.session() as session, session.begin():
        actor = legacy.User(status="active", created_at=now, updated_at=now)
        session.add(actor)
        session.flush()
        actor_id = actor.id
        session.add(legacy.UserRole(user_id=actor_id, role="admin"))
    item = attempt()
    controls.reserve(policy(), item)
    controls.finish(item.id, usage())
    lease = controls.acquire(admission(), sha256(b"synthetic").hexdigest())
    controls.release(lease.id)
    for kind, identifier in (
        ("provider", uuid4()),
        ("provider", item.id),
        ("admission", uuid4()),
        ("admission", lease.id),
        ("unsupported", uuid4()),
    ):
        with pytest.raises(AIAccountingError) as error:
            controls.reconcile(kind, identifier, actor_id)
        assert error.value.code == "conflict"
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(m.AIControlReconciliation)) == 0
        assert session.get(m.AIProviderUsage, item.id).status == "success"


def test_admin_can_reconcile_admission_idempotently_without_erasing_rate_history(database):
    controls = SqlAIControls(database)
    now = datetime.now(UTC)
    with database.session() as session, session.begin():
        actor = legacy.User(status="active", created_at=now, updated_at=now)
        session.add(actor)
        session.flush()
        actor_id = actor.id
        session.add(legacy.UserRole(user_id=actor_id, role="admin"))
    subject_hash = sha256(b"synthetic").hexdigest()
    limits = admission(global_requests_per_minute=1, subject_requests_per_minute=1)
    lease = controls.acquire(limits, subject_hash)
    assert controls.reconcile("admission", lease.id, actor_id)
    assert not controls.reconcile("admission", lease.id, actor_id)
    with pytest.raises(AIAccountingError) as limited:
        controls.acquire(limits, subject_hash)
    assert limited.value.code == "saturated"
    with database.session() as session:
        event = session.scalar(select(m.AIControlReconciliation))
        assert event.target_id == lease.id and event.operator_id == actor_id
        assert session.get(m.AIAdmissionRelease, lease.id) is not None
        assert session.scalar(select(func.count()).select_from(m.AIAdmissionLease)) == 1
        assert session.scalar(select(func.count()).select_from(m.AIControlReconciliation)) == 1
