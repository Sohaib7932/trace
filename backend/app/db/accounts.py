from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.learning import SqlLearningStore
from app.db.session import Database
from app.domain.accounts import Account, LearnerOwnership, Role, VerifiedIdentity
from app.domain.learning import Credential, LearningError
from app.repositories.accounts import AccountStore


class SqlAccountStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def bootstrap(self, identity: VerifiedIdentity, now: datetime) -> Account:
        subject = self.session.scalar(
            select(m.AuthSubject).where(
                m.AuthSubject.issuer == identity.issuer, m.AuthSubject.subject == identity.subject
            )
        )
        if subject is None:
            user = m.User(status="active", created_at=now, updated_at=now)
            self.session.add(user)
            self.session.flush()
            subject = m.AuthSubject(
                issuer=identity.issuer,
                subject=identity.subject,
                user_id=user.id,
                created_at=now,
                last_seen_at=now,
            )
            self.session.add_all([subject, m.UserRole(user_id=user.id, role="learner")])
        else:
            existing_user = self.session.get(m.User, subject.user_id)
            assert existing_user is not None  # enforced by foreign key
            user = existing_user
            subject.last_seen_at = now
        self.session.flush()
        roles = tuple(
            self.session.scalars(
                select(m.UserRole.role)
                .where(m.UserRole.user_id == user.id)
                .order_by(m.UserRole.role)
            )
        )
        if user.status != "active":
            raise LearningError("forbidden", "This Trace account is unavailable.")
        return Account(user.id, user.created_at, user.status, roles)

    def ownership(self, user_id: UUID) -> LearnerOwnership | None:
        row = self.session.get(m.AccountLearner, user_id)
        return LearnerOwnership(row.learner_id, row.claim_key) if row else None

    def create_learner(self, user_id: UUID, now: datetime) -> UUID:
        learner = m.Learner(created_at=now)
        self.session.add(learner)
        self.session.flush()
        self.session.add(m.AccountLearner(user_id=user_id, learner_id=learner.id, created_at=now))
        self.session.flush()
        return learner.id

    def credential(self, token_hash: str) -> Credential | None:
        return SqlLearningStore(self.session).credential(token_hash)

    def claim(self, user_id: UUID, credential: Credential, key: str, now: datetime) -> None:
        self.session.execute(
            update(m.LearnerCredential)
            .where(
                m.LearnerCredential.learner_id == credential.learner_id,
                m.LearnerCredential.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        self.session.flush()
        self.session.add(
            m.AccountLearner(
                user_id=user_id,
                learner_id=credential.learner_id,
                claim_key=key,
                claimed_credential_id=credential.id,
                created_at=now,
            )
        )
        self.session.flush()

    def allow_action(self, user_id: UUID, action: str, now: datetime) -> bool:
        window = int(now.timestamp()) // 60
        row = self.session.get(m.AccountActionLimit, (user_id, action))
        if row is None:
            self.session.add(
                m.AccountActionLimit(user_id=user_id, action=action, window=window, count=1)
            )
            return True
        if row.window != window:
            row.window, row.count = window, 0
        if row.count >= 30:
            return False
        row.count += 1
        return True

    def grant(self, user_id: UUID, role: Role, operator: str, reason: str, now: datetime) -> bool:
        user = self.session.get(m.User, user_id)
        if user is None or user.status != "active":
            raise LearningError("not_found", "Active Trace account not found.")
        if self.session.get(m.UserRole, (user_id, role)):
            return False
        self.session.add_all(
            [
                m.UserRole(user_id=user_id, role=role),
                m.RoleGrantEvent(
                    user_id=user_id, role=role, operator=operator, reason=reason, created_at=now
                ),
            ]
        )
        self.session.flush()
        return True


class SqlAccountRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @contextmanager
    def _scope(self, write: bool) -> Iterator[AccountStore]:
        try:
            with self.database.session() as session, session.begin():
                if write:
                    session.execute(update(m.WriteGate).where(m.WriteGate.id == 1).values(id=1))
                yield SqlAccountStore(session)
        except IntegrityError:
            raise LearningError(
                "conflict", "The change conflicts with existing ownership."
            ) from None
        except SQLAlchemyError:
            raise LearningError(
                "dependency_unavailable", "The account database is unavailable."
            ) from None

    def read(self) -> AbstractContextManager[AccountStore]:
        return self._scope(False)

    def write(self) -> AbstractContextManager[AccountStore]:
        return self._scope(True)
