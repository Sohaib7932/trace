"""Read current authorization and learner records without bootstrap or writes."""

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.learning import SqlLearningStore
from app.db.session import Database
from app.domain.accounts import Account, Principal
from app.domain.clock import as_utc
from app.domain.learning import Credential, LearningError
from app.repositories.feedback_release import FeedbackReleaseRead
from app.schemas.feedback_release import FreshAuthorization


def _unauthenticated() -> LearningError:
    return LearningError("unauthenticated", "The learner authorization is invalid or expired.")


def _fingerprint(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _principal_mode(principal: Principal, now: datetime) -> str:
    """The caller supplies an authenticated principal, never a request-body identity."""
    try:
        valid = (
            isinstance(principal, Principal)
            and isinstance(principal.learner_id, UUID)
            and as_utc(principal.expires_at) > now
        )
        if not valid or (principal.account is None) == (principal.credential is None):
            raise _unauthenticated()
        if principal.account is not None:
            account = principal.account
            if (
                not isinstance(account, Account)
                or not isinstance(account.id, UUID)
                or not isinstance(account.roles, tuple)
                or any(not isinstance(role, str) for role in account.roles)
            ):
                raise _unauthenticated()
            as_utc(account.created_at)
            if account.status != "active" or "learner" not in account.roles:
                raise LearningError("forbidden", "The learner account is unavailable.")
            return "account"
        credential = principal.credential
        if (
            not isinstance(credential, Credential)
            or not isinstance(credential.id, UUID)
            or credential.learner_id != principal.learner_id
            or credential.revoked_at is not None
            or as_utc(credential.expires_at) <= now
        ):
            raise _unauthenticated()
        return "guest"
    except (ValueError, TypeError, AttributeError):
        raise _unauthenticated() from None


def _authorize(session: Session, principal: Principal, now: datetime) -> FreshAuthorization:
    mode = _principal_mode(principal, now)
    if mode == "account":
        account = principal.account
        assert account is not None
        user = session.get(m.User, account.id)
        if user is None or as_utc(user.created_at) != as_utc(account.created_at):
            raise _unauthenticated()
        if user.status != "active" or session.get(m.UserRole, (user.id, "learner")) is None:
            raise LearningError("forbidden", "The learner account is unavailable.")
        owner = session.get(m.AccountLearner, user.id)
        if owner is None or owner.learner_id != principal.learner_id:
            raise _unauthenticated()
        subjects = list(
            session.scalars(
                select(m.AuthSubject)
                .where(m.AuthSubject.user_id == user.id)
                .order_by(m.AuthSubject.id)
            )
        )
        if not subjects or session.get(m.Learner, owner.learner_id) is None:
            raise _unauthenticated()
        identity: dict[str, object] = {
            "account_id": str(user.id),
            "created_at": as_utc(user.created_at).isoformat(),
            "learner_id": str(owner.learner_id),
            "ownership_created_at": as_utc(owner.created_at).isoformat(),
            "claim_key": owner.claim_key,
            "claimed_credential_id": (
                str(owner.claimed_credential_id) if owner.claimed_credential_id else None
            ),
            "subjects": [
                {
                    "id": str(subject.id),
                    "issuer": subject.issuer,
                    "subject": subject.subject,
                    "account_id": str(subject.user_id),
                    "created_at": as_utc(subject.created_at).isoformat(),
                }
                for subject in subjects
            ],
        }
        return FreshAuthorization(
            schema_version="feedback-authorization-v1",
            mode="account",
            learner_id=principal.learner_id,
            principal_expires_at=as_utc(principal.expires_at),
            valid_until=as_utc(principal.expires_at),
            observed_at=now,
            account_id=user.id,
            credential_id=None,
            identity_fingerprint=_fingerprint(identity),
        )
    snapshot = principal.credential
    assert snapshot is not None
    credential = session.get(m.LearnerCredential, snapshot.id)
    claimed = session.scalar(
        select(m.AccountLearner.user_id).where(m.AccountLearner.learner_id == principal.learner_id)
    )
    if (
        credential is None
        or credential.learner_id != principal.learner_id
        or credential.revoked_at is not None
        or as_utc(credential.expires_at) <= now
        or claimed is not None
        or session.get(m.Learner, principal.learner_id) is None
    ):
        raise _unauthenticated()
    return FreshAuthorization(
        schema_version="feedback-authorization-v1",
        mode="guest",
        learner_id=principal.learner_id,
        principal_expires_at=as_utc(principal.expires_at),
        valid_until=min(
            as_utc(principal.expires_at),
            as_utc(snapshot.expires_at),
            as_utc(credential.expires_at),
        ),
        observed_at=now,
        account_id=None,
        credential_id=credential.id,
        identity_fingerprint=_fingerprint(
            {
                "credential_id": str(credential.id),
                "learner_id": str(credential.learner_id),
                "token_hash": credential.token_hash,
                "created_at": as_utc(credential.created_at).isoformat(),
            }
        ),
    )


class SqlFeedbackReleaseRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @contextmanager
    def read(
        self, principal: Principal, session_id: UUID, now: datetime
    ) -> Iterator[FeedbackReleaseRead]:
        try:
            now = as_utc(now)
            _principal_mode(principal, now)
            if not isinstance(session_id, UUID):
                raise _unauthenticated()
        except (ValueError, TypeError, AttributeError):
            raise _unauthenticated() from None
        try:
            # Explicit repeatable-read snapshot on PostgreSQL; SQLite preserves
            # its existing autocommit=False snapshot. No write lock/provider I/O.
            with self.database.consistent_read() as session:
                auth = _authorize(session, principal, now)
                learning = SqlLearningStore(session)
                owned = learning.owned_session(principal.learner_id, session_id)
                if owned is None:
                    raise LearningError("not_found", "Session not found.")
                yield FeedbackReleaseRead(
                    auth=auth,
                    session=owned,
                    lesson=learning.version_by_id(owned.lesson_version_id),
                    learning=learning,
                )
        except SQLAlchemyError:
            raise LearningError(
                "dependency_unavailable", "The feedback authorization database is unavailable."
            ) from None
