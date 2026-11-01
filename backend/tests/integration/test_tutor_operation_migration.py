"""Upgrade preserves legacy guidance; reservation history cannot be downgraded away."""

from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, inspect, select, text, update
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.ai.providers.fake import FakeTutorProvider
from app.db import models as m
from app.db.learning import SqlLearningRepository
from app.db.migrations import migration_config
from app.db.session import Database
from app.domain.learning import LearningSession, Prediction, TutorInteraction
from app.domain.tutoring_operations import HintOperation
from app.services.catalog import seed_first_lesson
from app.services.learning import LearningService
from tests.conftest import migrate


def revision(database, target):
    config = migration_config()
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, target)


def legacy_guidance(database):
    repository = SqlLearningRepository(database)
    lesson = seed_first_lesson(repository)
    now = datetime.now(UTC)
    with repository.write() as store:
        credential = store.create_identity("c" * 64, now + timedelta(days=1))
        session = LearningSession(
            uuid4(),
            credential.learner_id,
            lesson.id,
            "awaiting_prediction",
            str(uuid4()),
            now,
            None,
        )
        store.add_session(session)
        store.add_prediction(
            Prediction(uuid4(), session.id, "rejected", "Original", str(uuid4()), now)
        )
        store.set_state(session.id, "ready_for_attempt")
        hint = TutorInteraction(
            uuid4(),
            session.id,
            None,
            1,
            "Historical fixture guidance.",
            "delivered",
            str(uuid4()),
            now,
        )
        store.add_hint(hint)
    return credential.learner_id, session.id, hint


def assert_integrity(database, expected):
    with database.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert connection.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == expected
        )


def test_upgrade_preserves_historical_hint_identity_and_next_sequence(settings):
    database = Database(settings)
    try:
        migrate(database, "0006_candidate_lifecycle")
        owner, session_id, old = legacy_guidance(database)
        with database.engine.connect() as connection:
            before = connection.execute(text("SELECT * FROM tutor_interactions")).mappings().all()
        migrate(database)
        with database.engine.connect() as connection:
            after = connection.execute(text("SELECT * FROM tutor_interactions")).mappings().all()
        assert after == before
        service = LearningService(SqlLearningRepository(database), FakeTutorProvider())
        assert service.hint(owner, session_id, None, old.idempotency_key) == old
        second = service.hint(owner, session_id, None, str(uuid4()))
        assert second.sequence == 2
        assert service.progress(owner, session_id).hint_request_count == 2
        assert_integrity(database, "0007_tutor_reservations")
        with pytest.raises(RuntimeError, match="reservation history exists"):
            revision(database, "0006_candidate_lifecycle")
        assert_integrity(database, "0007_tutor_reservations")
    finally:
        database.dispose()


def test_empty_reservation_downgrade_preserves_legacy_guidance_and_reupgrades(settings):
    database = Database(settings)
    try:
        migrate(database, "0006_candidate_lifecycle")
        _, _, original = legacy_guidance(database)
        migrate(database)
        revision(database, "0006_candidate_lifecycle")
        assert "hint_operations" not in inspect(database.engine).get_table_names()
        with SqlLearningRepository(database).read() as store:
            assert store.hints(original.session_id) == [original]
        assert_integrity(database, "0006_candidate_lifecycle")
        migrate(database)
        assert "hint_operations" in inspect(database.engine).get_table_names()
        assert_integrity(database, "0007_tutor_reservations")
    finally:
        database.dispose()


def test_reservation_constraints_and_triggers_enforce_identity_and_result(database):
    owner, session_id, legacy = legacy_guidance(database)
    repository = SqlLearningRepository(database)
    at = datetime.now(UTC)
    operation = HintOperation(
        uuid4(), session_id, None, 2, str(uuid4()), at, at + timedelta(seconds=30)
    )
    with repository.write() as store:
        store.add_hint_operation(operation)
    for changed in [
        replace(operation, id=uuid4(), sequence=3),
        replace(operation, id=uuid4(), session_id=uuid4(), sequence=1),
        replace(operation, id=uuid4(), sequence=1),
        replace(operation, id=uuid4(), idempotency_key=str(uuid4()), sequence=3),
    ]:
        with pytest.raises(IntegrityError), database.session() as db, db.begin():
            db.add(m.HintOperation(**asdict(changed)))
            db.flush()
    for statement in [
        update(m.HintOperation).values(deadline_at=at + timedelta(seconds=60)),
        update(m.HintOperation).values(status="finalized", completed_at=at),
        delete(m.HintOperation),
    ]:
        with pytest.raises(IntegrityError), database.session() as db, db.begin():
            db.execute(statement)
    with pytest.raises(IntegrityError), database.session() as db, db.begin():
        db.add(
            m.TutorInteraction(
                **asdict(
                    TutorInteraction(
                        uuid4(),
                        session_id,
                        None,
                        2,
                        "Wrong result identity",
                        "delivered",
                        operation.idempotency_key,
                        at,
                    )
                )
            )
        )
        db.flush()
    result = TutorInteraction(
        operation.id, session_id, None, 2, "Guidance", "delivered", operation.idempotency_key, at
    )
    with repository.write() as store:
        store.add_hint(result)
        store.finish_hint_operation(operation.id, at)
    with repository.read() as store:
        saved = store.hint_operations(session_id)[0]
        assert saved.status == "finalized" and saved.completed_at == at
        assert store.hints(session_id) == [legacy, result]
    with pytest.raises(IntegrityError), database.session() as db, db.begin():
        db.execute(update(m.HintOperation).values(status="pending", completed_at=None))
    with database.session() as db:
        assert len(db.scalars(select(m.HintOperation)).all()) == 1
