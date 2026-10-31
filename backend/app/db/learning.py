from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, fields
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.session import Database
from app.domain import learning as d
from app.domain.retrieval import RetrievalAttempt, RetrievalCheckpoint
from app.domain.transfer import TaskSnapshot
from app.repositories.learning import LearningStore


def snapshot[T](kind: type[T], row: Any) -> T:
    # Domain snapshots are detached values, never ORM objects returned to services.
    return kind(**{field.name: getattr(row, field.name) for field in fields(kind)})  # type: ignore[arg-type]


class SqlLearningStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def credential(self, token_hash: str) -> d.Credential | None:
        row = self.session.scalar(
            select(m.LearnerCredential).where(m.LearnerCredential.token_hash == token_hash)
        )
        return snapshot(d.Credential, row) if row else None

    def create_identity(self, token_hash: str, expires_at: datetime) -> d.Credential:
        learner = m.Learner()
        self.session.add(learner)
        self.session.flush()
        credential = m.LearnerCredential(
            learner_id=learner.id, token_hash=token_hash, expires_at=expires_at
        )
        self.session.add(credential)
        self.session.flush()
        return snapshot(d.Credential, credential)

    def revoke(self, credential_id: UUID, at: datetime) -> None:
        self.session.execute(
            update(m.LearnerCredential)
            .where(m.LearnerCredential.id == credential_id)
            .values(revoked_at=at)
        )

    def version(self, lesson_id: str, version: str | None = None) -> d.LessonVersion | None:
        query = select(m.LessonVersion).where(m.LessonVersion.lesson_id == lesson_id)
        if version is not None:
            query = query.where(m.LessonVersion.version == version)
        row = self.session.scalar(query.order_by(m.LessonVersion.created_at.desc()))
        return snapshot(d.LessonVersion, row) if row else None

    def renew(self, credential_id: UUID, expires_at: datetime) -> None:
        self.session.execute(
            update(m.LearnerCredential)
            .where(m.LearnerCredential.id == credential_id)
            .values(expires_at=expires_at)
        )

    def version_by_id(self, version_id: UUID) -> d.LessonVersion:
        row = self.session.get(m.LessonVersion, version_id)
        if row is None:
            raise d.LearningError("not_found", "Lesson version not found.")
        return snapshot(d.LessonVersion, row)

    def publish(self, version: d.LessonVersion) -> None:
        if self.session.get(m.Lesson, version.lesson_id) is None:
            self.session.add(m.Lesson(id=version.lesson_id))
            self.session.flush()
        self.session.add(m.LessonVersion(**asdict(version)))
        self.session.flush()

    def owned_session(self, owner: UUID, session_id: UUID) -> d.LearningSession | None:
        row = self.session.scalar(
            select(m.LearningSession).where(
                m.LearningSession.id == session_id, m.LearningSession.learner_id == owner
            )
        )
        return snapshot(d.LearningSession, row) if row else None

    def session_by_key(self, owner: UUID, key: str) -> d.LearningSession | None:
        row = self.session.scalar(
            select(m.LearningSession).where(
                m.LearningSession.learner_id == owner, m.LearningSession.idempotency_key == key
            )
        )
        return snapshot(d.LearningSession, row) if row else None

    def add_session(self, session: d.LearningSession) -> None:
        self.session.add(m.LearningSession(**asdict(session)))
        self.session.flush()

    def set_state(self, session_id: UUID, state: str, completed_at: datetime | None = None) -> None:
        self.session.execute(
            update(m.LearningSession)
            .where(m.LearningSession.id == session_id)
            .values(state=state, completed_at=completed_at)
        )

    def prediction(self, session_id: UUID) -> d.Prediction | None:
        row = self.session.scalar(select(m.Prediction).where(m.Prediction.session_id == session_id))
        return snapshot(d.Prediction, row) if row else None

    def add_prediction(self, prediction: d.Prediction) -> None:
        self.session.add(m.Prediction(**asdict(prediction)))
        self.session.flush()

    def attempts(self, session_id: UUID) -> list[d.Attempt]:
        return [
            snapshot(d.Attempt, row)
            for row in self.session.scalars(
                select(m.Attempt)
                .where(m.Attempt.session_id == session_id)
                .order_by(m.Attempt.number)
            )
        ]

    def add_attempt(self, attempt: d.Attempt) -> None:
        self.session.add(m.Attempt(**asdict(attempt)))
        self.session.flush()

    def hints(self, session_id: UUID) -> list[d.TutorInteraction]:
        return [
            snapshot(d.TutorInteraction, row)
            for row in self.session.scalars(
                select(m.TutorInteraction)
                .where(m.TutorInteraction.session_id == session_id)
                .order_by(m.TutorInteraction.sequence)
            )
        ]

    def add_hint(self, hint: d.TutorInteraction) -> None:
        self.session.add(m.TutorInteraction(**asdict(hint)))
        self.session.flush()

    def runs(self, session_id: UUID) -> list[d.VerificationRun]:
        return [
            snapshot(d.VerificationRun, row)
            for row in self.session.scalars(
                select(m.VerificationRun)
                .where(m.VerificationRun.session_id == session_id)
                .order_by(m.VerificationRun.created_at)
            )
        ]

    def add_run(self, run: d.VerificationRun) -> None:
        self.session.add(m.VerificationRun(**asdict(run)))
        self.session.flush()

    def finish_run(self, run_id: UUID, status: str, feedback: str, at: datetime) -> None:
        self.session.execute(
            update(m.VerificationRun)
            .where(m.VerificationRun.id == run_id, m.VerificationRun.status == "pending")
            .values(status=status, feedback=feedback, completed_at=at)
        )

    def checks(self, run_id: UUID) -> list[d.VerificationCheck]:
        return [
            snapshot(d.VerificationCheck, row)
            for row in self.session.scalars(
                select(m.VerificationCheck)
                .where(m.VerificationCheck.run_id == run_id)
                .order_by(m.VerificationCheck.code)
            )
        ]

    def add_check(self, check: d.VerificationCheck) -> None:
        self.session.add(m.VerificationCheck(**asdict(check)))
        self.session.flush()

    def events(self, session_id: UUID) -> list[d.LearningEvent]:
        return [
            snapshot(d.LearningEvent, row)
            for row in self.session.scalars(
                select(m.LearningEvent)
                .where(m.LearningEvent.session_id == session_id)
                .order_by(m.LearningEvent.created_at)
            )
        ]

    def add_event(self, event: d.LearningEvent) -> None:
        self.session.add(m.LearningEvent(**asdict(event)))
        self.session.flush()

    def add_note(self, run_id: UUID, title: str, content: str) -> d.NoteSnapshot:
        row = m.RuntimeNote(run_id=run_id, title=title, content=content)
        self.session.add(row)
        self.session.flush()
        return d.NoteSnapshot(row.id, row.title, row.content)

    def notes(self, run_id: UUID) -> tuple[d.NoteSnapshot, ...]:
        return tuple(
            d.NoteSnapshot(row.id, row.title, row.content)
            for row in self.session.scalars(
                select(m.RuntimeNote).where(m.RuntimeNote.run_id == run_id)
            )
        )

    def add_task(self, run_id: UUID, title: str, priority: str) -> TaskSnapshot:
        row = m.RuntimeTask(run_id=run_id, title=title, priority=priority)
        self.session.add(row)
        self.session.flush()
        return TaskSnapshot(row.id, row.title, row.priority)

    def tasks(self, run_id: UUID) -> tuple[TaskSnapshot, ...]:
        return tuple(
            TaskSnapshot(row.id, row.title, row.priority)
            for row in self.session.scalars(
                select(m.RuntimeTask).where(m.RuntimeTask.run_id == run_id)
            )
        )

    def owned_sessions(self, owner: UUID) -> list[d.LearningSession]:
        return [
            snapshot(d.LearningSession, row)
            for row in self.session.scalars(
                select(m.LearningSession)
                .where(m.LearningSession.learner_id == owner)
                .order_by(m.LearningSession.created_at, m.LearningSession.id)
            )
        ]

    def checkpoints(self, owner: UUID) -> list[RetrievalCheckpoint]:
        return [
            snapshot(RetrievalCheckpoint, row)
            for row in self.session.scalars(
                select(m.RetrievalCheckpoint)
                .join(
                    m.LearningSession,
                    m.RetrievalCheckpoint.transfer_session_id == m.LearningSession.id,
                )
                .where(m.LearningSession.learner_id == owner)
                .order_by(m.RetrievalCheckpoint.due_at, m.RetrievalCheckpoint.id)
            )
        ]

    def add_checkpoint(self, checkpoint: RetrievalCheckpoint) -> None:
        self.session.add(m.RetrievalCheckpoint(**asdict(checkpoint)))
        self.session.flush()

    def retrieval_attempts(self, checkpoint_id: UUID) -> list[RetrievalAttempt]:
        return [
            snapshot(RetrievalAttempt, row)
            for row in self.session.scalars(
                select(m.RetrievalAttempt)
                .where(m.RetrievalAttempt.checkpoint_id == checkpoint_id)
                .order_by(m.RetrievalAttempt.number)
            )
        ]

    def add_retrieval_attempt(self, attempt: RetrievalAttempt) -> None:
        self.session.add(m.RetrievalAttempt(**asdict(attempt)))
        self.session.flush()

    def complete_checkpoint(self, checkpoint_id: UUID, at: datetime) -> None:
        self.session.execute(
            update(m.RetrievalCheckpoint)
            .where(m.RetrievalCheckpoint.id == checkpoint_id)
            .values(completed_at=at)
        )


class SqlLearningRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @contextmanager
    def read(self) -> Iterator[LearningStore]:
        try:
            with self.database.session() as session:
                yield SqlLearningStore(session)
        except SQLAlchemyError:
            raise d.LearningError(
                "dependency_unavailable", "The database is unavailable. Please retry."
            ) from None

    @contextmanager
    def write(self) -> Iterator[LearningStore]:
        try:
            with self.database.session() as session, session.begin():
                session.execute(update(m.WriteGate).where(m.WriteGate.id == 1).values(id=1))
                yield SqlLearningStore(session)
        except IntegrityError:
            raise d.LearningError(
                "conflict", "The write conflicts with preserved history."
            ) from None
        except SQLAlchemyError:
            raise d.LearningError(
                "dependency_unavailable", "The database is unavailable. Please retry."
            ) from None
