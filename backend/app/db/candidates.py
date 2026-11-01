"""Append-only candidate persistence; no joins or writes to learner history."""

import json
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.session import Database
from app.domain.learning import LearningError
from app.repositories.candidates import CandidateStore
from app.schemas.candidate_lifecycle import CandidateEvent, CandidateHistory, CandidateSnapshot


class SqlCandidateStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, candidate_id: str) -> CandidateHistory | None:
        row = self.session.get(m.GeneratedCandidate, UUID(candidate_id))
        if row is None:
            return None
        snapshot = CandidateSnapshot.model_validate_json(json.dumps(row.snapshot))
        if (
            snapshot.id,
            snapshot.generation_request_id,
            snapshot.creation_key,
            snapshot.created_at,
            snapshot.composition_sha256,
            snapshot.release_eligible,
        ) != (
            str(row.id),
            str(row.generation_request_id),
            str(row.creation_key),
            row.created_at,
            row.composition_sha256,
            row.release_eligible,
        ):
            raise LearningError("conflict", "Candidate snapshot integrity failed.")
        events = tuple(
            self._checked_event(item)
            for item in self.session.scalars(
                select(m.CandidateLifecycleEvent)
                .where(
                    m.CandidateLifecycleEvent.candidate_id == row.id,
                )
                .order_by(m.CandidateLifecycleEvent.revision)
            )
        )
        return CandidateHistory(snapshot=snapshot, events=events)

    @staticmethod
    def _checked_event(row: m.CandidateLifecycleEvent) -> CandidateEvent:
        value = CandidateEvent.model_validate_json(json.dumps(row.payload))
        if (
            value.id,
            value.candidate_id,
            value.revision,
            value.operation_key,
            value.action,
            value.previous_state,
            value.state,
            value.actor_id,
            value.created_at,
            value.release_eligible,
        ) != (
            str(row.id),
            str(row.candidate_id),
            row.revision,
            str(row.operation_key),
            row.action,
            row.previous_state,
            row.state,
            str(row.actor_id) if row.actor_id else None,
            row.created_at,
            row.release_eligible,
        ):
            raise LearningError("conflict", "Candidate event integrity failed.")
        return value

    def by_creation_key(self, key: str) -> CandidateHistory | None:
        row = self.session.scalar(
            select(m.GeneratedCandidate).where(
                m.GeneratedCandidate.creation_key == UUID(key),
            )
        )
        return self.get(str(row.id)) if row is not None else None

    def insert(self, snapshot: CandidateSnapshot, event: CandidateEvent) -> None:
        snapshot = CandidateSnapshot.model_validate_json(snapshot.model_dump_json(warnings=False))
        event = CandidateEvent.model_validate_json(event.model_dump_json(warnings=False))
        self.session.add(
            m.GeneratedCandidate(
                id=UUID(snapshot.id),
                generation_request_id=UUID(snapshot.generation_request_id),
                creation_key=UUID(snapshot.creation_key),
                created_at=snapshot.created_at,
                snapshot=snapshot.model_dump(mode="json"),
                composition_sha256=snapshot.composition_sha256,
                release_eligible=False,
            )
        )
        self.session.flush()
        self._event(event)

    def _event(self, event: CandidateEvent) -> None:
        self.session.add(
            m.CandidateLifecycleEvent(
                id=UUID(event.id),
                candidate_id=UUID(event.candidate_id),
                revision=event.revision,
                operation_key=UUID(event.operation_key),
                action=event.action,
                previous_state=event.previous_state,
                state=event.state,
                actor_id=UUID(event.actor_id) if event.actor_id else None,
                created_at=event.created_at,
                payload=event.model_dump(mode="json"),
                release_eligible=False,
            )
        )
        self.session.flush()

    def append(self, event: CandidateEvent, expected_revision: int) -> None:
        event = CandidateEvent.model_validate_json(event.model_dump_json(warnings=False))
        current = self.get(event.candidate_id)
        if (
            current is None
            or current.revision != expected_revision
            or (current.state != event.previous_state)
        ):
            raise LearningError("conflict", "Candidate revision changed before finalization.")
        if event.action in {"human_review", "production_approval", "reject"}:
            admin = self.session.scalar(
                select(m.User.id)
                .join(m.UserRole)
                .where(
                    m.User.id == UUID(event.actor_id or ""),
                    m.User.status == "active",
                    m.UserRole.role == "admin",
                )
            )
            if admin is None:
                raise LearningError(
                    "forbidden", "Candidate review requires an active administrator."
                )
        CandidateHistory(snapshot=current.snapshot, events=current.events + (event,))
        self._event(event)


class SqlCandidateRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @contextmanager
    def _scope(self, write: bool) -> Iterator[CandidateStore]:
        try:
            with self.database.session() as session, session.begin():
                if write:
                    session.execute(update(m.WriteGate).where(m.WriteGate.id == 1).values(id=1))
                yield SqlCandidateStore(session)
        except IntegrityError:
            raise LearningError(
                "conflict", "Candidate change conflicts with immutable history."
            ) from None
        except SQLAlchemyError:
            raise LearningError(
                "dependency_unavailable", "Candidate storage is unavailable."
            ) from None
        except ValueError:
            raise LearningError("conflict", "Candidate storage integrity failed.") from None

    def read(self) -> AbstractContextManager[CandidateStore]:
        return self._scope(False)

    def write(self) -> AbstractContextManager[CandidateStore]:
        return self._scope(True)
