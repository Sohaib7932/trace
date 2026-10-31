import importlib.util
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import MetaData, UniqueConstraint, event, select, update
from sqlalchemy.exc import IntegrityError, OperationalError, StatementError

from alembic import command
from app.core.settings import Settings
from app.db import models as m
from app.db.learning import SqlLearningRepository, SqlLearningStore
from app.db.migrations import migration_config
from app.db.session import Database
from app.domain.learning import LearningError, VerificationRun
from app.main import create_app
from app.services.catalog import LESSON_ID, seed_first_lesson
from app.verification.asgi_notes import AsgiNotesVerifier
from tests.conftest import migrate
from tests.integration.test_learning import attempt, post, predict, progress, start, verify


def test_insecure_cookies_require_explicit_local_configuration() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, cookie_secure=False)
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            cookie_secure=False,
            allow_insecure_local_cookies=True,
            cors_origins=("https://foreign.example",),
        )


def test_secure_cookie_is_the_default(
    learning_app: FastAPI, database: Database, settings: Settings
) -> None:
    with TestClient(create_app(settings, database), base_url="https://testserver") as client:
        response = client.post(
            "/api/v1/learners/anonymous",
            json={},
            headers={"Origin": "http://localhost:3000", "X-Trace-Client": "learning-web"},
        )
        assert "secure" in response.headers["set-cookie"].lower()
        assert client.get("/api/v1/learners/me").status_code == 200


def test_actual_commit_failure_rolls_back_note_and_records_infrastructure_error(
    learner: TestClient, database: Database
) -> None:
    session = start(learner)
    predict(learner, session)
    a = attempt(learner, session, "content")

    def mark_note(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO RUNTIME_NOTES"):
            connection.info["fail_note_commit"] = True

    def fail_commit(connection):
        if connection.info.pop("fail_note_commit", False):
            raise OperationalError("private-path", {}, RuntimeError("private-token"))

    event.listen(database.engine, "before_cursor_execute", mark_note)
    event.listen(database.engine, "commit", fail_commit)
    try:
        response = verify(learner, session, a["id"])
    finally:
        event.remove(database.engine, "before_cursor_execute", mark_note)
        event.remove(database.engine, "commit", fail_commit)
    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert "private" not in response.text
    with database.session() as fresh:
        assert fresh.scalars(select(m.RuntimeNote)).all() == []


def test_readback_failure_is_unavailable_not_invented_zero_rows(
    learner: TestClient, database: Database
) -> None:
    session = start(learner)
    predict(learner, session)
    a = attempt(learner, session, "content")

    def fail_read(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "FROM runtime_notes" in statement:
            raise OperationalError("private-readback-path", {}, RuntimeError("private-token"))

    event.listen(database.engine, "before_cursor_execute", fail_read)
    try:
        result = verify(learner, session, a["id"]).json()
    finally:
        event.remove(database.engine, "before_cursor_execute", fail_read)
    assert result["status"] == "error"
    checks = {c["code"]: c for c in result["checks"]}
    assert checks["http_status"]["observed"] == "201"
    assert checks["row_count"]["observed"] == "unavailable"
    with database.session() as fresh:
        assert len(fresh.scalars(select(m.RuntimeNote)).all()) == 1


def test_readback_uses_an_independent_session(
    learner: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    writers = []
    original_add, original_read = SqlLearningStore.add_note, SqlLearningStore.notes

    def add(store, run_id, title, content):
        writers.append(store.session)
        return original_add(store, run_id, title, content)

    def read(store, run_id):
        assert all(store.session is not writer for writer in writers)
        return original_read(store, run_id)

    monkeypatch.setattr(SqlLearningStore, "add_note", add)
    monkeypatch.setattr(SqlLearningStore, "notes", read)
    session = start(learner)
    predict(learner, session)
    a = attempt(learner, session, "content")
    assert verify(learner, session, a["id"]).json()["status"] == "passed"
    assert len(writers) == 1


def test_forged_success_response_without_row_never_passes(
    learner: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def forged(self, run_id, field):
        return 201, {
            "id": str(uuid4()),
            "title": "Trace verification note",
            "content": "Understanding request validation",
        }

    monkeypatch.setattr(AsgiNotesVerifier, "_request", forged)
    session = start(learner)
    predict(learner, session)
    a = attempt(learner, session, "content")
    result = verify(learner, session, a["id"]).json()
    assert result["status"] == "error"
    assert next(c for c in result["checks"] if c["code"] == "row_count")["observed"] == "0"
    assert progress(learner, session)["session"]["state"] == "verification_pending"


def test_database_outage_is_not_an_authentication_or_learner_error(
    learner: TestClient, database: Database
) -> None:
    def unavailable(*args):
        raise OperationalError("sensitive-path", {}, RuntimeError("sensitive-token"))

    event.listen(database.engine, "before_cursor_execute", unavailable)
    try:
        result = learner.post("/api/v1/learners/anonymous", json={})
    finally:
        event.remove(database.engine, "before_cursor_execute", unavailable)
    assert result.status_code == 503 and result.json()["error"]["code"] == "dependency_unavailable"
    assert "sensitive" not in result.text


def test_missing_version_and_conflicting_repository_write_are_controlled(
    database: Database,
) -> None:
    repo = SqlLearningRepository(database)
    with pytest.raises(LearningError), repo.read() as store:
        store.version_by_id(uuid4())
    version = seed_first_lesson(repo)
    with pytest.raises(LearningError, match="conflicts"), repo.write() as store:
        store.publish(replace(version, id=uuid4()))


def test_same_creation_key_cannot_switch_lesson_version(
    learner: TestClient, database: Database
) -> None:
    repo = SqlLearningRepository(database)
    first = seed_first_lesson(repo)
    with repo.write() as store:
        store.publish(replace(first, id=uuid4(), version="1.1.0"))
    key = str(uuid4())
    assert (
        post(learner, "/sessions", {"lesson_id": LESSON_ID, "version": "1.0.0"}, key).status_code
        == 201
    )
    assert (
        post(learner, "/sessions", {"lesson_id": LESSON_ID, "version": "1.1.0"}, key).status_code
        == 409
    )
    assert post(learner, "/sessions", {"lesson_id": "missing"}, str(uuid4())).status_code == 404


def test_hint_retry_cannot_switch_attempt_context(learner: TestClient) -> None:
    session = start(learner)
    predict(learner, session)
    key = str(uuid4())
    assert post(learner, f"/sessions/{session}/hints", {}, key).status_code == 201
    a = attempt(learner, session)
    assert (
        post(learner, f"/sessions/{session}/hints", {"attempt_id": a["id"]}, key).status_code == 409
    )


def test_current_and_stale_incomplete_verification_have_safe_retry_rules(
    learner: TestClient, database: Database
) -> None:
    session = start(learner)
    predict(learner, session)
    a = attempt(learner, session, "content")
    key = str(uuid4())
    run_id = uuid4()
    repo = SqlLearningRepository(database)
    pending = VerificationRun(
        run_id, UUID(session), UUID(a["id"]), "pending", key, datetime.now(UTC)
    )
    with repo.write() as store:
        store.add_run(pending)
    assert verify(learner, session, a["id"], key).status_code == 409
    # Separate session simulates a restarted server observing an old, unfinished run.
    # created_at is protected by the trigger, so use a second test session for stale state.
    second = start(learner)
    predict(learner, second)
    other = attempt(learner, second, "content")
    stale = VerificationRun(
        uuid4(),
        UUID(second),
        UUID(other["id"]),
        "pending",
        key,
        datetime.now(UTC) - timedelta(minutes=5),
    )
    with repo.write() as store:
        store.add_run(stale)
    result = verify(learner, second, other["id"], key).json()
    assert result["status"] == "error"
    assert result["checks"][0]["source"] == "server_lifecycle"
    assert verify(learner, second, other["id"]).json()["status"] == "passed"
    assert progress(learner, session)["session"]["state"] == "verification_pending"


def test_finalized_evidence_and_version_pin_are_immutable(
    learner: TestClient, database: Database
) -> None:
    session = start(learner)
    predict(learner, session)
    post(learner, f"/sessions/{session}/hints", {})
    a = attempt(learner, session, "content")
    verify(learner, session, a["id"])
    for statement in [
        update(m.VerificationRun).values(feedback="rewritten"),
        update(m.VerificationCheck).values(observed="invented"),
        update(m.TutorInteraction).values(text="rewritten"),
        update(m.LearningEvent).values(event_type="invented"),
        update(m.LearningSession).values(lesson_version_id=uuid4()),
        update(m.RuntimeNote).values(content="invented"),
    ]:
        with pytest.raises(IntegrityError), database.session() as db, db.begin():
            db.execute(statement)


def test_naive_database_timestamps_and_blank_predictions_are_rejected(
    learner: TestClient, database: Database
) -> None:
    with pytest.raises(StatementError), database.session() as db, db.begin():
        db.add(m.Learner(created_at=datetime(2026, 1, 1)))
        db.flush()
    session = start(learner)
    assert (
        post(
            learner,
            f"/sessions/{session}/prediction",
            {"selected_answer": "saved", "reasoning": "   "},
        ).status_code
        == 422
    )


def test_constraint_name_forward_migration_preserves_populated_history(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr(f"sqlite+pysqlite:///{tmp_path / 'legacy.db'}"),
        cookie_secure=False,
        allow_insecure_local_cookies=True,
    )
    database = Database(settings)
    try:
        migrate(database, "0001_foundation")
        legacy = MetaData()
        for table in m.Base.metadata.sorted_tables:
            if table.name in {"runtime_tasks", "retrieval_checkpoints", "retrieval_attempts"}:
                continue  # This fixture deliberately reconstructs the pre-Module-3 schema.
            copy = table.to_metadata(legacy)
            for constraint in copy.constraints:
                if isinstance(constraint, UniqueConstraint):
                    constraint.name = "uq_" + copy.name + "_" + next(iter(constraint.columns)).name
        legacy.create_all(database.engine)
        path = Path(__file__).parents[2] / "alembic/versions/0002_learning_learning_engine.py"
        spec = importlib.util.spec_from_file_location("legacy_guards", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        config = migration_config()
        with database.engine.begin() as connection:
            config.attributes["connection"] = connection
            with Operations.context(MigrationContext.configure(connection)):
                module.install_guards()
            command.stamp(config, "0002_learning")
        seed_first_lesson(SqlLearningRepository(database))
        with TestClient(create_app(settings, database)) as client:
            client.headers.update(
                {"Origin": "http://localhost:3000", "X-Trace-Client": "learning-web"}
            )
            client.post("/api/v1/learners/anonymous", json={})
            session = start(client)
            predict(client, session)
            a = attempt(client, session, "content")
            assert verify(client, session, a["id"]).json()["status"] == "passed"
            before = progress(client, session)
            with database.engine.begin() as connection:
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
                command.check(config)
            assert progress(client, session) == before
            with pytest.raises(IntegrityError), database.session() as db, db.begin():
                db.execute(update(m.Prediction).values(reasoning="rewritten"))
    finally:
        database.dispose()
