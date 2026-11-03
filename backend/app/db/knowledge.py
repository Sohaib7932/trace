"""Immutable knowledge persistence with short transactions and fresh role fences."""

import json
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import knowledge_models as k
from app.db import models as m
from app.db.session import Database
from app.domain.knowledge import (
    KnowledgeEvent,
    KnowledgeHistory,
    KnowledgeManifest,
    KnowledgePublication,
    KnowledgeReleaseReceipt,
    KnowledgeRevision,
)
from app.domain.learning import LearningError
from app.repositories.knowledge import KnowledgeStore
from app.support.embedding_index import EmbeddingIndex


def _integrity() -> LearningError:
    return LearningError("conflict", "Knowledge archive integrity failed.")


class SqlKnowledgeStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def require_role(self, user_id: UUID, role: str) -> None:
        if (
            role not in {"admin", "learner"}
            or self.session.scalar(
                select(m.User.id)
                .join(m.UserRole)
                .where(m.User.id == user_id, m.User.status == "active", m.UserRole.role == role)
            )
            is None
        ):
            raise LearningError("forbidden", "The required active account role is unavailable.")

    def history(self, revision_id: str) -> KnowledgeHistory | None:
        row = self.session.get(k.KnowledgeRevisionRow, UUID(revision_id))
        if row is None:
            return None
        value = KnowledgeRevision.model_validate_json(json.dumps(row.payload))
        if (
            value.id,
            value.source_id,
            value.revision,
            value.creation_key,
            value.actor_id,
            value.created_at,
            value.original_sha256,
            value.normalized_sha256,
            value.content_sha256,
        ) != (
            str(row.id),
            row.source_id,
            row.revision,
            str(row.creation_key),
            str(row.actor_id),
            row.created_at,
            row.original_sha256,
            row.normalized_sha256,
            row.content_sha256,
        ):
            raise _integrity()
        events = tuple(
            self._event_value(event)
            for event in self.session.scalars(
                select(k.KnowledgeEventRow)
                .where(k.KnowledgeEventRow.revision_id == row.id)
                .order_by(k.KnowledgeEventRow.sequence)
            )
        )
        return KnowledgeHistory(revision=value, events=events)

    def by_creation_key(self, key: str) -> KnowledgeHistory | None:
        row = self.session.scalar(
            select(k.KnowledgeRevisionRow).where(k.KnowledgeRevisionRow.creation_key == UUID(key))
        )
        return self.history(str(row.id)) if row is not None else None

    @staticmethod
    def _event_value(row: k.KnowledgeEventRow) -> KnowledgeEvent:
        value = KnowledgeEvent.model_validate_json(json.dumps(row.payload))
        if (
            value.id,
            value.revision_id,
            value.sequence,
            value.operation_key,
            value.previous_event_sha256,
            value.previous_state,
            value.state,
            value.action,
            value.actor_id,
            value.created_at,
            value.content_sha256,
        ) != (
            str(row.id),
            str(row.revision_id),
            row.sequence,
            str(row.operation_key),
            row.previous_event_sha256,
            row.previous_state,
            row.state,
            row.action,
            str(row.actor_id),
            row.created_at,
            row.content_sha256,
        ):
            raise _integrity()
        return value

    def insert(self, revision: KnowledgeRevision, event: KnowledgeEvent) -> None:
        revision = KnowledgeRevision.model_validate_json(revision.model_dump_json())
        self.require_role(UUID(revision.actor_id), "admin")
        KnowledgeHistory(revision=revision, events=(event,))
        if self.session.get(k.KnowledgeSourceRow, revision.source_id) is None:
            self.session.add(
                k.KnowledgeSourceRow(
                    source_id=revision.source_id,
                    actor_id=UUID(revision.actor_id),
                    created_at=revision.created_at,
                )
            )
            self.session.flush()
        self.session.add(
            k.KnowledgeRevisionRow(
                id=UUID(revision.id),
                source_id=revision.source_id,
                revision=revision.revision,
                creation_key=UUID(revision.creation_key),
                actor_id=UUID(revision.actor_id),
                created_at=revision.created_at,
                original_sha256=revision.original_sha256,
                normalized_sha256=revision.normalized_sha256,
                content_sha256=revision.content_sha256,
                payload=revision.model_dump(mode="json"),
            )
        )
        self.session.flush()
        self._append_row(event)

    def _append_row(self, event: KnowledgeEvent) -> None:
        self.session.add(
            k.KnowledgeEventRow(
                id=UUID(event.id),
                revision_id=UUID(event.revision_id),
                sequence=event.sequence,
                operation_key=UUID(event.operation_key),
                previous_event_sha256=event.previous_event_sha256,
                previous_state=event.previous_state,
                state=event.state,
                action=event.action,
                actor_id=UUID(event.actor_id),
                created_at=event.created_at,
                content_sha256=event.content_sha256,
                payload=event.model_dump(mode="json"),
            )
        )
        self.session.flush()

    def append(self, event: KnowledgeEvent, expected_sequence: int) -> None:
        event = KnowledgeEvent.model_validate_json(event.model_dump_json())
        self.require_role(UUID(event.actor_id), "admin")
        history = self.history(event.revision_id)
        if history is None or history.sequence != expected_sequence:
            raise LearningError("conflict", "Knowledge revision changed before finalization.")
        KnowledgeHistory(revision=history.revision, events=history.events + (event,))
        self._append_row(event)

    def manifest(self, digest: str) -> KnowledgeManifest | None:
        row = self.session.get(k.KnowledgeManifestRow, digest)
        if row is None:
            return None
        value = KnowledgeManifest.model_validate_json(json.dumps(row.payload))
        if value.content_sha256 != row.content_sha256:
            raise _integrity()
        return value

    def put_manifest(self, value: KnowledgeManifest, actor_id: str, now: datetime) -> None:
        self.require_role(UUID(actor_id), "admin")
        checked = KnowledgeManifest.model_validate_json(value.model_dump_json())
        existing = self.manifest(checked.content_sha256)
        if existing is not None:
            if existing != checked:
                raise _integrity()
            return
        self.session.add(
            k.KnowledgeManifestRow(
                content_sha256=checked.content_sha256,
                actor_id=UUID(actor_id),
                created_at=now,
                payload=checked.model_dump(mode="json"),
            )
        )
        self.session.flush()

    @staticmethod
    def _publication(row: k.KnowledgePublicationRow) -> KnowledgePublication:
        value = KnowledgePublication.model_validate_json(json.dumps(row.payload))
        if (
            value.id,
            value.sequence,
            value.operation_key,
            value.previous_manifest_sha256,
            value.manifest_sha256,
            value.actor_id,
            value.created_at,
            value.content_sha256,
        ) != (
            str(row.id),
            row.sequence,
            str(row.operation_key),
            row.previous_manifest_sha256,
            row.manifest_sha256,
            str(row.actor_id),
            row.created_at,
            row.content_sha256,
        ):
            raise _integrity()
        return value

    def current_publication(self) -> KnowledgePublication | None:
        row = self.session.scalar(
            select(k.KnowledgePublicationRow)
            .order_by(k.KnowledgePublicationRow.sequence.desc())
            .limit(1)
        )
        return self._publication(row) if row is not None else None

    def publication_by_key(self, key: str) -> KnowledgePublication | None:
        row = self.session.scalar(
            select(k.KnowledgePublicationRow).where(
                k.KnowledgePublicationRow.operation_key == UUID(key)
            )
        )
        return self._publication(row) if row is not None else None

    def publish(self, value: KnowledgePublication, expected_sequence: int) -> None:
        self.require_role(UUID(value.actor_id), "admin")
        checked = KnowledgePublication.model_validate_json(value.model_dump_json())
        previous = self.current_publication()
        if (
            (previous.sequence if previous else -1) != expected_sequence
            or checked.sequence != expected_sequence + 1
            or checked.previous_manifest_sha256 != (previous.manifest_sha256 if previous else None)
        ):
            raise LearningError("conflict", "Knowledge publication changed before finalization.")
        self.session.add(
            k.KnowledgePublicationRow(
                id=UUID(checked.id),
                sequence=checked.sequence,
                operation_key=UUID(checked.operation_key),
                previous_manifest_sha256=checked.previous_manifest_sha256,
                manifest_sha256=checked.manifest_sha256,
                actor_id=UUID(checked.actor_id),
                created_at=checked.created_at,
                content_sha256=checked.content_sha256,
                payload=checked.model_dump(mode="json"),
            )
        )
        self.session.flush()

    def index(self, digest: str) -> EmbeddingIndex | None:
        row = self.session.get(k.KnowledgeIndexRow, digest)
        if row is None:
            return None
        value = EmbeddingIndex.model_validate_json(json.dumps(row.payload))
        if (
            value.index_sha256,
            value.manifest_sha256,
            value.metadata.profile.space_sha256,
            value.metadata.profile.model_id,
            value.metadata.profile.dimensions,
            value.metadata.created_at,
        ) != (
            row.index_sha256,
            row.manifest_sha256,
            row.embedding_space_sha256,
            row.model_id,
            row.dimensions,
            row.created_at,
        ):
            raise _integrity()
        return value

    def index_by_key(self, key: str) -> EmbeddingIndex | None:
        row = self.session.scalar(
            select(k.KnowledgeIndexRow).where(k.KnowledgeIndexRow.operation_key == UUID(key))
        )
        return self.index(row.index_sha256) if row is not None else None

    def put_index(self, value: EmbeddingIndex, key: str, actor_id: str) -> None:
        self.require_role(UUID(actor_id), "admin")
        checked = EmbeddingIndex.model_validate_json(value.model_dump_json())
        self.session.add(
            k.KnowledgeIndexRow(
                index_sha256=checked.index_sha256,
                manifest_sha256=checked.manifest_sha256,
                operation_key=UUID(key),
                actor_id=UUID(actor_id),
                created_at=checked.metadata.created_at,
                embedding_space_sha256=checked.metadata.profile.space_sha256,
                model_id=checked.metadata.profile.model_id,
                dimensions=checked.metadata.profile.dimensions,
                payload=checked.model_dump(mode="json"),
            )
        )
        self.session.flush()

    def receipt(self, receipt_id: str) -> KnowledgeReleaseReceipt | None:
        row = self.session.get(k.KnowledgeReceiptRow, UUID(receipt_id))
        if row is None:
            return None
        value = KnowledgeReleaseReceipt.model_validate_json(json.dumps(row.payload))
        if (
            value.id,
            value.created_at,
            value.request_id_sha256,
            value.manifest_sha256,
            value.index_sha256,
            value.content_sha256,
        ) != (
            str(row.id),
            row.created_at,
            row.request_id_sha256,
            row.manifest_sha256,
            row.index_sha256,
            row.content_sha256,
        ):
            raise _integrity()
        return value

    def put_receipt(self, value: KnowledgeReleaseReceipt) -> None:
        checked = KnowledgeReleaseReceipt.model_validate_json(value.model_dump_json())
        self.session.add(
            k.KnowledgeReceiptRow(
                id=UUID(checked.id),
                created_at=checked.created_at,
                request_id_sha256=checked.request_id_sha256,
                manifest_sha256=checked.manifest_sha256,
                index_sha256=checked.index_sha256,
                content_sha256=checked.content_sha256,
                payload=checked.model_dump(mode="json"),
            )
        )
        self.session.flush()


class SqlKnowledgeRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @contextmanager
    def _scope(self, write: bool) -> Iterator[KnowledgeStore]:
        try:
            with self.database.session() as session, session.begin():
                if write:
                    result = session.execute(
                        update(m.WriteGate).where(m.WriteGate.id == 1).values(id=1)
                    )
                    if getattr(result, "rowcount", None) != 1:
                        raise LearningError(
                            "dependency_unavailable", "Knowledge serialization is unavailable."
                        )
                elif self.database.engine.dialect.name == "postgresql":
                    session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
                yield SqlKnowledgeStore(session)
        except IntegrityError:
            raise LearningError(
                "conflict", "Knowledge change conflicts with preserved history."
            ) from None
        except SQLAlchemyError:
            raise LearningError(
                "dependency_unavailable", "Knowledge storage is unavailable."
            ) from None
        except ValueError:
            raise _integrity() from None

    def read(self) -> AbstractContextManager[KnowledgeStore]:
        return self._scope(False)

    def write(self) -> AbstractContextManager[KnowledgeStore]:
        return self._scope(True)
