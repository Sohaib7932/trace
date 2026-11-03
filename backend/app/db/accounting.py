"""Shared, short transactional admission and append-only provider accounting.

The existing write-gate row serializes reservations across processes on both
supported databases. No transaction remains open during provider/HTTP work.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import CursorResult, func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.ai.accounting import (
    AdmissionLease,
    AdmissionPolicy,
    AIAccountingError,
    AllowancePolicy,
    AttemptReservation,
    Digest,
    ProviderAttempt,
    ProviderUsage,
)
from app.db import accounting_models as m
from app.db.models import User, UserRole, WriteGate
from app.db.session import Database


class SqlAIControls:
    def __init__(self, database: Database) -> None:
        self.database = database

    def summary(self, scope: str) -> dict[str, int]:
        """Safe operator aggregate. No prompts, subjects, attempt IDs or raw errors."""
        try:
            with self.database.consistent_read() as session:
                attempts = (
                    session.scalar(
                        select(func.count())
                        .select_from(m.AIProviderAttempt)
                        .where(m.AIProviderAttempt.scope == scope)
                    )
                    or 0
                )
                outcomes = list(
                    session.scalars(
                        select(m.AIProviderUsage)
                        .join(
                            m.AIProviderAttempt,
                            m.AIProviderAttempt.id == m.AIProviderUsage.attempt_id,
                        )
                        .where(m.AIProviderAttempt.scope == scope)
                    )
                )
                admission_scope = or_(
                    m.AIAdmissionLease.scope == scope,
                    m.AIAdmissionLease.scope.startswith(scope + ":", autoescape=True),
                )
                active_admission = (
                    session.scalar(
                        select(func.count())
                        .select_from(m.AIAdmissionLease)
                        .outerjoin(
                            m.AIAdmissionRelease,
                            m.AIAdmissionRelease.lease_id == m.AIAdmissionLease.id,
                        )
                        .where(admission_scope, m.AIAdmissionRelease.lease_id.is_(None))
                    )
                    or 0
                )
                known_duration = [
                    row.provider_duration_ms
                    for row in outcomes
                    if row.provider_duration_ms is not None
                ]
                result = {
                    "provider_attempts": attempts,
                    "active_provider_leases": attempts - len(outcomes),
                    "active_admission_leases": active_admission,
                    "known_input_tokens": sum(row.input_tokens or 0 for row in outcomes),
                    "known_output_tokens": sum(row.output_tokens or 0 for row in outcomes),
                    "known_accounted_cost_microusd": sum(
                        row.accounted_cost_microusd or 0 for row in outcomes
                    ),
                    "missing_usage_count": attempts
                    - len(outcomes)
                    + sum(
                        any(
                            value is None
                            for value in (
                                row.input_tokens,
                                row.output_tokens,
                                row.accounted_cost_microusd,
                            )
                        )
                        for row in outcomes
                    ),
                    "provider_duration_known_count": len(known_duration),
                    "provider_duration_ms_total": sum(known_duration),
                }
                for status in ("success", "refusal", "truncated", "timeout", "error", "unknown"):
                    result["outcome_" + status] = sum(row.status == status for row in outcomes)
                return result
        except SQLAlchemyError:
            raise AIAccountingError("unavailable") from None

    @contextmanager
    def _write(self) -> Iterator[Session]:
        try:
            with self.database.session() as session, session.begin():
                gate = session.execute(update(WriteGate).where(WriteGate.id == 1).values(id=1))
                if not isinstance(gate, CursorResult) or gate.rowcount != 1:
                    raise AIAccountingError("unavailable")
                yield session
        except SQLAlchemyError:
            raise AIAccountingError("unavailable") from None

    @staticmethod
    def _now(session: Session) -> datetime:
        clock = (
            func.statement_timestamp()
            if session.get_bind().dialect.name == "postgresql"
            else func.current_timestamp()
        )
        value = session.scalar(select(clock))
        assert isinstance(value, datetime)
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @staticmethod
    def _policy(
        session: Session, kind: str, value: AllowancePolicy | AdmissionPolicy, now: datetime
    ) -> None:
        configuration = value.model_dump(mode="json")
        row = session.get(m.AIControlPolicy, value.scope)
        if row is None:
            session.add(
                m.AIControlPolicy(
                    scope=value.scope, kind=kind, configuration=configuration, created_at=now
                )
            )
            session.flush()
        elif row.kind != kind or row.configuration != configuration:
            raise AIAccountingError("policy_mismatch")

    def reserve(self, policy: AllowancePolicy, attempt: ProviderAttempt) -> AttemptReservation:
        policy = AllowancePolicy.model_validate(policy.model_dump())
        attempt = ProviderAttempt.model_validate(attempt.model_dump())
        with self._write() as session:
            now = self._now(session)
            self._policy(session, "allowance", policy, now)
            existing = session.get(m.AIProviderAttempt, attempt.id)
            if existing is not None:
                if (
                    any(
                        getattr(existing, name) != value
                        for name, value in attempt.model_dump().items()
                    )
                    or existing.scope != policy.scope
                ):
                    raise AIAccountingError("conflict")
                return AttemptReservation(
                    attempt_id=attempt.id,
                    newly_reserved=False,
                    finalized=session.get(m.AIProviderUsage, attempt.id) is not None,
                )
            total = (
                session.scalar(
                    select(func.count())
                    .select_from(m.AIProviderAttempt)
                    .where(m.AIProviderAttempt.scope == policy.scope)
                )
                or 0
            )
            known_cost = (
                session.scalar(
                    select(func.sum(m.AIProviderUsage.accounted_cost_microusd))
                    .join(
                        m.AIProviderAttempt, m.AIProviderAttempt.id == m.AIProviderUsage.attempt_id
                    )
                    .where(m.AIProviderAttempt.scope == policy.scope)
                )
                or 0
            )
            if known_cost > policy.paid_budget_microusd:
                raise AIAccountingError("depleted")
            if total >= policy.max_attempts:
                raise AIAccountingError("depleted")
            active = (
                select(func.count())
                .select_from(m.AIProviderAttempt)
                .outerjoin(
                    m.AIProviderUsage, m.AIProviderUsage.attempt_id == m.AIProviderAttempt.id
                )
                .where(
                    m.AIProviderAttempt.scope == policy.scope,
                    m.AIProviderUsage.attempt_id.is_(None),
                )
            )
            if (session.scalar(active) or 0) >= policy.max_in_flight or (
                session.scalar(
                    active.where(m.AIProviderAttempt.subject_hash == attempt.subject_hash)
                )
                or 0
            ) >= policy.max_subject_in_flight:
                raise AIAccountingError("saturated")
            window = now.replace(second=0, microsecond=0)
            count = (
                session.scalar(
                    select(func.count())
                    .select_from(m.AIProviderAttempt)
                    .where(
                        m.AIProviderAttempt.scope == policy.scope,
                        m.AIProviderAttempt.window_start == window,
                    )
                )
                or 0
            )
            if count >= policy.requests_per_minute:
                raise AIAccountingError("saturated")
            session.add(
                m.AIProviderAttempt(
                    **attempt.model_dump(), scope=policy.scope, admitted_at=now, window_start=window
                )
            )
            session.flush()
            return AttemptReservation(attempt_id=attempt.id, newly_reserved=True, finalized=False)

    def finish(self, attempt_id: UUID, usage: ProviderUsage) -> None:
        usage = ProviderUsage.model_validate(usage.model_dump())
        with self._write() as session:
            if session.get(m.AIProviderAttempt, attempt_id) is None:
                raise AIAccountingError("conflict")
            existing = session.get(m.AIProviderUsage, attempt_id)
            if existing is not None:
                if any(
                    getattr(existing, name) != value for name, value in usage.model_dump().items()
                ):
                    raise AIAccountingError("conflict")
                return
            session.add(
                m.AIProviderUsage(
                    attempt_id=attempt_id, completed_at=self._now(session), **usage.model_dump()
                )
            )
            session.flush()

    def acquire(self, policy: AdmissionPolicy, subject_hash: str) -> AdmissionLease:
        policy = AdmissionPolicy.model_validate(policy.model_dump())
        # Reuse the port's strict digest validation, never retain a caller's raw identity.
        TypeAdapter[Digest](Digest.__value__).validate_python(subject_hash)
        with self._write() as session:
            now = self._now(session)
            self._policy(session, "admission", policy, now)
            window = now.replace(second=0, microsecond=0)
            requests = (
                select(func.count())
                .select_from(m.AIAdmissionLease)
                .where(
                    m.AIAdmissionLease.scope == policy.scope,
                    m.AIAdmissionLease.window_start == window,
                )
            )
            active = (
                select(func.count())
                .select_from(m.AIAdmissionLease)
                .outerjoin(
                    m.AIAdmissionRelease, m.AIAdmissionRelease.lease_id == m.AIAdmissionLease.id
                )
                .where(
                    m.AIAdmissionLease.scope == policy.scope,
                    m.AIAdmissionRelease.lease_id.is_(None),
                )
            )
            if (
                (session.scalar(requests) or 0) >= policy.global_requests_per_minute
                or (
                    session.scalar(requests.where(m.AIAdmissionLease.subject_hash == subject_hash))
                    or 0
                )
                >= policy.subject_requests_per_minute
                or (session.scalar(active) or 0) >= policy.max_global_in_flight
                or (
                    session.scalar(active.where(m.AIAdmissionLease.subject_hash == subject_hash))
                    or 0
                )
                >= policy.max_subject_in_flight
            ):
                raise AIAccountingError("saturated")
            lease = AdmissionLease(id=uuid4(), admitted_at=now)
            session.add(
                m.AIAdmissionLease(
                    id=lease.id,
                    scope=policy.scope,
                    subject_hash=subject_hash,
                    admitted_at=now,
                    window_start=window,
                )
            )
            session.flush()
            return lease

    def release(self, lease_id: UUID) -> None:
        with self._write() as session:
            if session.get(m.AIAdmissionLease, lease_id) is None:
                raise AIAccountingError("conflict")
            if session.get(m.AIAdmissionRelease, lease_id) is None:
                session.add(m.AIAdmissionRelease(lease_id=lease_id, released_at=self._now(session)))
                session.flush()

    def reconcile(
        self, target_kind: Literal["provider", "admission"], target_id: UUID, operator_id: UUID
    ) -> bool:
        """Explicit operator-confirmed stop; never refund cumulative attempt allowance."""
        with self._write() as session:
            admin = session.scalar(
                select(User.id)
                .join(UserRole)
                .where(User.id == operator_id, User.status == "active", UserRole.role == "admin")
            )
            if admin is None:
                raise AIAccountingError("conflict")
            existing = session.scalar(
                select(m.AIControlReconciliation).where(
                    m.AIControlReconciliation.target_kind == target_kind,
                    m.AIControlReconciliation.target_id == target_id,
                )
            )
            if existing is not None:
                return False
            now = self._now(session)
            if target_kind == "provider":
                if (
                    session.get(m.AIProviderAttempt, target_id) is None
                    or session.get(m.AIProviderUsage, target_id) is not None
                ):
                    raise AIAccountingError("conflict")
                session.add(
                    m.AIProviderUsage(
                        attempt_id=target_id,
                        status="unknown",
                        error_code=None,
                        input_tokens=None,
                        output_tokens=None,
                        accounted_cost_microusd=None,
                        completed_at=now,
                    )
                )
            elif target_kind == "admission":
                if (
                    session.get(m.AIAdmissionLease, target_id) is None
                    or session.get(m.AIAdmissionRelease, target_id) is not None
                ):
                    raise AIAccountingError("conflict")
                session.add(m.AIAdmissionRelease(lease_id=target_id, released_at=now))
            else:
                raise AIAccountingError("conflict")
            session.add(
                m.AIControlReconciliation(
                    id=uuid4(),
                    target_kind=target_kind,
                    target_id=target_id,
                    operator_id=operator_id,
                    created_at=now,
                )
            )
            session.flush()
            return True
