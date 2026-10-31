import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError

from alembic import command
from app.db import models as m
from app.db.learning import SqlLearningRepository, SqlLearningStore
from app.db.migrations import migration_config
from app.db.session import Database
from app.domain.learning import LearningError
from app.domain.transfer import TASK_PRIORITY, TASK_TITLE, TRANSFER_ID
from app.services import catalog
from app.services.catalog import seed_transfer_lesson
from app.services.retrieval import RetrievalService, schedule_checkpoints
from app.verification.asgi_tasks import AsgiTasksVerifier
from tests.integration.test_learning import attempt, post, predict, progress, start, verify


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 1, 9, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock(learning_app: FastAPI) -> MutableClock:
    clock = MutableClock()
    learning_app.state.clock = clock
    return clock


def complete_original(client: TestClient) -> str:
    session = start(client)
    assert predict(client, session).status_code == 201
    correction = attempt(client, session, "content")
    assert verify(client, session, correction["id"]).json()["status"] == "passed"
    return session


def start_transfer(client: TestClient) -> str:
    response = post(client, "/sessions", {"lesson_id": TRANSFER_ID})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def mapping(client: TestClient, session: str, field: str, key: str | None = None):
    return post(
        client,
        f"/sessions/{session}/attempts",
        {
            "change_type": "nest_payload_field",
            "field_name": field,
            "explanation": "Compare JSON levels, not just the presence of a value.",
        },
        key,
    )


def journey(client: TestClient):
    response = client.get("/api/v1/learners/me/journey")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


@pytest.fixture
def investigated(learner: TestClient, database: Database, clock: MutableClock) -> str:
    seed_transfer_lesson(SqlLearningRepository(database))
    complete_original(learner)
    session = start_transfer(learner)
    assert predict(learner, session).status_code == 201
    flat = mapping(learner, session, "flat")
    assert flat.status_code == 201
    assert verify(learner, session, flat.json()["id"]).json()["status"] == "failed"
    return session


def finish_transfer(client: TestClient, session: str):
    corrected = mapping(client, session, "nested")
    assert corrected.status_code == 201, corrected.text
    response = verify(client, session, corrected.json()["id"])
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "passed", response.text
    return response.json()


def test_real_nested_verification_isolated_fresh_read_and_atomic_schedule(
    learner: TestClient,
    database: Database,
    investigated: str,
    clock: MutableClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_version = catalog.seed_first_lesson(SqlLearningRepository(database))
    assert (
        original_version.content_hash
        == "c3231631019829efe5cd1882b361cf22b8bdcdd51caca2a67a60dd73b326707e"
    )
    before = progress(learner, investigated)
    flat = before["verifications"][0]
    checks = {c["code"]: c for c in flat["checks"]}
    assert flat["status"] == "failed" and checks["http_status"]["observed"] == "422"
    assert checks["row_count"]["observed"] == "0"
    assert set(json.loads(checks["validation"]["observed"])) == {
        "missing:metadata",
        "extra_forbidden:priority",
    }
    with database.session() as fresh:
        assert fresh.scalar(select(func.count()).select_from(m.RuntimeTask)) == 0
        assert fresh.scalar(select(func.count()).select_from(m.RuntimeNote)) == 1
    writes, reads = [], []
    add, read = SqlLearningStore.add_task, SqlLearningStore.tasks

    def capture_write(store, *args):
        writes.append(store.session)
        return add(store, *args)

    def capture_read(store, *args):
        reads.append(store.session)
        return read(store, *args)

    monkeypatch.setattr(SqlLearningStore, "add_task", capture_write)
    monkeypatch.setattr(SqlLearningStore, "tasks", capture_read)
    passed = finish_transfer(learner, investigated)
    assert writes[0] is not reads[0]
    assert all(c["matched"] for c in passed["checks"])
    checks = {c["code"]: c for c in passed["checks"]}
    assert checks["http_status"]["observed"] == "201"
    assert checks["row_count"]["source"] == "fresh_database_read"
    with database.session() as fresh:
        task = fresh.scalar(select(m.RuntimeTask).where(m.RuntimeTask.run_id == UUID(passed["id"])))
        assert task and (task.title, task.priority) == (TASK_TITLE, TASK_PRIORITY)
        assert str(task.id) == json.loads(checks["api_response"]["observed"])["id"]
        assert fresh.scalar(select(func.count()).select_from(m.RuntimeNote)) == 1
    after = progress(learner, investigated)
    assert after["prediction"] == before["prediction"]
    assert [a["field_name"] for a in after["attempts"]] == ["flat", "nested"]
    assert all(a["change_type"] == "nest_payload_field" for a in after["attempts"])
    assert after["session"]["state"] == "completed"
    history = journey(learner)
    assert all(p["completed"] for p in history["phases"])
    checkpoints = history["checkpoints"]
    assert len(checkpoints) == 2
    assert [datetime.fromisoformat(c["due_at"]) for c in checkpoints] == [
        clock.now + timedelta(days=n) for n in (1, 7)
    ]
    assert all(c["status"] == "upcoming" for c in checkpoints)
    assert verify(learner, investigated, passed["attempt_id"]).json() == passed
    assert journey(learner)["checkpoints"] == checkpoints
    another = start_transfer(learner)
    assert predict(learner, another).status_code == 201
    flat_attempt = mapping(learner, another, "flat").json()
    later_failure = verify(learner, another, flat_attempt["id"]).json()
    assert later_failure["status"] == "failed"
    assert next(c for c in later_failure["checks"] if c["code"] == "row_count")["observed"] == "0"
    with database.session() as fresh:
        assert fresh.scalar(select(func.count()).select_from(m.RuntimeTask)) == 1
    assert journey(learner)["checkpoints"] == checkpoints


def test_transfer_publication_and_pin_are_independent(
    learner: TestClient,
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SqlLearningRepository(database)
    version = seed_transfer_lesson(repository)
    assert seed_transfer_lesson(repository) == version
    complete_original(learner)
    session = start_transfer(learner)
    changed = {**catalog.TRANSFER_CONTENT, "title": "A different future version"}
    monkeypatch.setattr(catalog, "TRANSFER_CONTENT", changed)
    with pytest.raises(LearningError, match="new version"):
        seed_transfer_lesson(repository)
    with repository.write() as store:
        store.publish(
            replace(
                version,
                id=uuid4(),
                version="1.1.0",
                public_content=changed,
                content_hash=catalog.transfer_hash(changed),
                created_at=version.created_at + timedelta(seconds=1),
            )
        )
    saved = progress(learner, session)
    assert saved["session"]["lesson_version_id"] == str(version.id)
    assert saved["lesson"]["title"] == "The Nested Payload Problem"
    public = learner.get(f"/api/v1/lessons/{TRANSFER_ID}").json()
    assert public["version"] == "1.1.0"
    assert not {"expected_field", "prediction_answer", "content_hash"} & public.keys()
    with pytest.raises(IntegrityError), database.session() as db, db.begin():
        db.execute(
            update(m.LessonVersion)
            .where(m.LessonVersion.id == version.id)
            .values(expected_field="flat")
        )


def test_prerequisite_prediction_and_investigation_cannot_be_skipped(
    learner: TestClient,
    database: Database,
) -> None:
    seed_transfer_lesson(SqlLearningRepository(database))
    assert post(learner, "/sessions", {"lesson_id": TRANSFER_ID}).status_code == 409
    assert not journey(learner)["phases"][1]["available"]
    complete_original(learner)
    session = start_transfer(learner)
    assert mapping(learner, session, "flat").status_code == 409
    assert mapping(learner, session, "nested").status_code == 409
    assert predict(learner, session).status_code == 201
    assert mapping(learner, session, "nested").status_code == 409
    assert (
        post(
            learner,
            f"/sessions/{session}/attempts",
            {"change_type": "rename_payload_field", "field_name": "content"},
        ).status_code
        == 422
    )
    flat = mapping(learner, session, "flat")
    assert flat.status_code == 201
    assert mapping(learner, session, "nested").status_code == 409
    assert verify(learner, session, flat.json()["id"]).json()["status"] == "failed"
    assert mapping(learner, session, "nested").status_code == 201


@pytest.mark.parametrize("failure", ["commit", "readback", "forged", "exception"])
def test_task_infrastructure_cannot_complete_or_schedule(
    learner: TestClient,
    database: Database,
    investigated: str,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    corrected = mapping(learner, investigated, "nested").json()
    with monkeypatch.context() as patch:

        def unavailable(*args):
            raise LearningError("dependency_unavailable", "Read unavailable")

        if failure == "readback":
            patch.setattr(SqlLearningStore, "tasks", unavailable)
        elif failure == "exception":
            patch.setattr(AsgiTasksVerifier, "observe", unavailable)
        elif failure == "forged":

            async def forged(*args):
                return 201, {
                    "id": str(uuid4()),
                    "title": TASK_TITLE,
                    "metadata": {"priority": TASK_PRIORITY},
                }

            patch.setattr(AsgiTasksVerifier, "_request", forged)
        else:

            def fail_insert(conn, cursor, statement, parameters, context, executemany):
                if statement.startswith("INSERT INTO runtime_tasks"):
                    raise OperationalError("fixture insert failure", {}, None)

            event.listen(database.engine, "before_cursor_execute", fail_insert)
        try:
            key = str(uuid4())
            failed = verify(learner, investigated, corrected["id"], key)
            assert failed.status_code == 200 and failed.json()["status"] == "error"
            assert verify(learner, investigated, corrected["id"], key).json() == failed.json()
            assert progress(learner, investigated)["session"]["state"] == "verification_pending"
            assert journey(learner)["checkpoints"] == []
            if failure == "readback":
                assert (
                    next(c for c in failed.json()["checks"] if c["code"] == "row_count")["observed"]
                    == "unavailable"
                )
        finally:
            if failure == "commit":
                event.remove(database.engine, "before_cursor_execute", fail_insert)
    passed = verify(learner, investigated, corrected["id"]).json()
    assert passed["status"] == "passed"
    assert len(journey(learner)["checkpoints"]) == 2


def test_exact_boundaries_hidden_initial_answer_and_missed_checkpoints(
    learner: TestClient,
    investigated: str,
    clock: MutableClock,
) -> None:
    finish_transfer(learner, investigated)
    checkpoints = journey(learner)["checkpoints"]
    first, second = checkpoints
    path = f"/retrievals/{first['id']}/attempts"
    assert post(learner, path, {"selection": "b"}).status_code == 409
    assert learner.get(f"/api/v1/retrievals/{first['id']}").json()["question"] is None
    due = datetime.fromisoformat(first["due_at"])
    clock.now = due - timedelta(microseconds=1)
    assert journey(learner)["checkpoints"][0]["status"] == "upcoming"
    clock.now = due
    question = learner.get(f"/api/v1/retrievals/{first['id']}").json()
    assert question["checkpoint"]["status"] == "due" and question["attempts"] == []
    assert "answer" not in question["question"] and "explanation" not in question["question"]
    assert (
        "zone" in question["question"]["payload"]
        and "metadata" not in question["question"]["schema_code"]
    )
    assert journey(learner)["checkpoints"][1]["status"] == "upcoming"
    clock.now = datetime.fromisoformat(second["due_at"])
    assert [c["status"] for c in journey(learner)["checkpoints"]] == ["due", "due"]
    clock.now += timedelta(days=30)
    assert [c["status"] for c in journey(learner)["checkpoints"]] == ["due", "due"]
    assert post(learner, path, {"selection": "b"}).json()["correct"] is True
    assert journey(learner)["checkpoints"][0]["due_at"] == first["due_at"]


def test_retrieval_history_idempotency_completion_and_database_guards(
    learner: TestClient,
    database: Database,
    investigated: str,
    clock: MutableClock,
) -> None:
    finish_transfer(learner, investigated)
    checkpoint = journey(learner)["checkpoints"][0]
    clock.now = datetime.fromisoformat(checkpoint["due_at"])
    path = f"/retrievals/{checkpoint['id']}/attempts"
    key = str(uuid4())
    first = post(learner, path, {"selection": "a", "reasoning": "  Original thought.  "}, key)
    assert first.status_code == 201 and first.json()["correct"] is False
    assert (
        post(learner, path, {"selection": "a", "reasoning": "  Original thought.  "}, key).json()
        == first.json()
    )
    assert post(learner, path, {"selection": "b"}, key).status_code == 409
    second_key = str(uuid4())
    second = post(learner, path, {"selection": "b"}, second_key)
    assert second.status_code == 201 and second.json()["correct"] is True
    assert post(learner, path, {"selection": "b"}, second_key).json() == second.json()
    assert post(learner, path, {"selection": "b"}).status_code == 409
    saved = learner.get(f"/api/v1/retrievals/{checkpoint['id']}").json()
    assert [a["number"] for a in saved["attempts"]] == [1, 2]
    assert saved["attempts"][0] == first.json()
    assert saved["checkpoint"]["status"] == "completed"
    for statement in [
        update(m.RetrievalAttempt).values(reasoning="rewritten"),
        update(m.RetrievalCheckpoint)
        .where(m.RetrievalCheckpoint.id == UUID(checkpoint["id"]))
        .values(due_at=clock.now + timedelta(days=5)),
    ]:
        with pytest.raises(IntegrityError), database.session() as db, db.begin():
            db.execute(statement)
    with TestClient(learner.app, cookies=learner.cookies) as reloaded:
        assert reloaded.get(f"/api/v1/retrievals/{checkpoint['id']}").json() == saved


def test_retrieval_owner_origin_and_input_protection(
    learner: TestClient,
    learning_app: FastAPI,
    investigated: str,
    clock: MutableClock,
) -> None:
    finish_transfer(learner, investigated)
    checkpoint = journey(learner)["checkpoints"][0]
    path = f"/retrievals/{checkpoint['id']}"
    with TestClient(learning_app) as other:
        other.headers.update({"Origin": "http://localhost:3000", "X-Trace-Client": "learning-web"})
        assert other.post("/api/v1/learners/anonymous", json={}).status_code == 200
        assert (
            other.get("/api/v1" + path).status_code
            == other.get(f"/api/v1/retrievals/{uuid4()}").status_code
            == 404
        )
        assert post(other, path + "/attempts", {"selection": "b"}).status_code == 404
        assert journey(other)["checkpoints"] == []
        assert post(other, "/sessions", {"lesson_id": TRANSFER_ID}).status_code == 409
    clock.now = datetime.fromisoformat(checkpoint["due_at"])
    assert post(learner, path + "/attempts", {"selection": "arbitrary"}).status_code == 422
    assert post(learner, path + "/attempts", {"selection": "b", "correct": True}).status_code == 422
    assert (
        learner.post(
            "/api/v1" + path + "/attempts",
            json={"selection": "b"},
            headers={"Origin": "https://foreign.example", "Idempotency-Key": str(uuid4())},
        ).status_code
        == 403
    )


def test_concurrent_schedule_and_retrieval_replays_use_independent_transactions(
    learner: TestClient,
    database: Database,
    investigated: str,
    clock: MutableClock,
) -> None:
    finish_transfer(learner, investigated)
    owner = UUID(learner.get("/api/v1/learners/me").json()["learner_id"])
    repository = SqlLearningRepository(database)
    with repository.read() as store:
        source = store.owned_session(owner, UUID(investigated))
    assert source and source.completed_at

    def schedule_again(_):
        with repository.write() as store:
            schedule_checkpoints(store, source, source.completed_at)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(schedule_again, range(4)))
    checkpoints = journey(learner)["checkpoints"]
    assert len(checkpoints) == 2
    clock.now = datetime.fromisoformat(checkpoints[0]["due_at"])
    service = RetrievalService(repository, clock)
    key = str(uuid4())

    def submit(_):
        return service.submit(
            owner, UUID(checkpoints[0]["id"]), "b", "Recall the nested contract.", key
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(submit, range(4)))
    assert len({a.id for a in responses}) == 1
    assert journey(learner)["checkpoints"][0]["attempt_count"] == 1
    clock.now = datetime.fromisoformat(checkpoints[1]["due_at"])

    def distinct_submission(_):
        return service.submit(
            owner, UUID(checkpoints[1]["id"]), "c", "An initial response.", str(uuid4())
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        distinct = list(pool.map(distinct_submission, range(4)))
    assert sorted(a.number for a in distinct) == [1, 2, 3, 4]
    assert len({a.id for a in distinct}) == 4
    assert journey(learner)["checkpoints"][1]["status"] == "due"


def test_populated_transfer_downgrade_refuses_history_loss(
    learner: TestClient,
    database: Database,
    investigated: str,
) -> None:
    before = progress(learner, investigated)
    config = migration_config()
    with (
        pytest.raises(RuntimeError, match="discard transfer history"),
        database.engine.begin() as connection,
    ):
        config.attributes["connection"] = connection
        command.downgrade(config, "0003_constraint_names")
    assert progress(learner, investigated) == before


def test_schedule_insert_failure_rolls_back_completion_and_recovers_without_duplicates(
    learner: TestClient,
    database: Database,
    investigated: str,
    clock: MutableClock,
) -> None:
    corrected = mapping(learner, investigated, "nested").json()

    def fail_schedule(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO retrieval_checkpoints"):
            raise OperationalError("fixture scheduling failure", {}, None)

    event.listen(database.engine, "before_cursor_execute", fail_schedule)
    try:
        response = verify(learner, investigated, corrected["id"])
        assert response.status_code == 503
    finally:
        event.remove(database.engine, "before_cursor_execute", fail_schedule)
    saved = progress(learner, investigated)
    assert saved["session"]["state"] == "verification_pending"
    assert saved["verifications"][-1]["status"] == "pending"
    assert journey(learner)["checkpoints"] == []
    clock.now += timedelta(seconds=61)
    recovered = verify(learner, investigated, corrected["id"])
    assert recovered.status_code == 200 and recovered.json()["status"] == "passed"
    assert len(journey(learner)["checkpoints"]) == 2
    saved = progress(learner, investigated)
    assert [r["status"] for r in saved["verifications"]] == ["failed", "error", "passed"]
    assert verify(learner, investigated, corrected["id"]).json() == recovered.json()


def test_real_module_2_history_survives_forward_migration(
    learner: TestClient, database: Database
) -> None:
    original = complete_original(learner)
    before = progress(learner, original)
    config = migration_config()
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0003_constraint_names")
    assert progress(learner, original) == before
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        command.check(config)
    assert progress(learner, original) == before
    with pytest.raises(IntegrityError), database.session() as db, db.begin():
        db.execute(update(m.Prediction).values(reasoning="overwrite"))
    seed_transfer_lesson(SqlLearningRepository(database))
    assert start_transfer(learner)


def test_valid_near_expiry_credential_renews_without_changing_owner_or_persisting_token(
    learner: TestClient,
    database: Database,
) -> None:
    from app.services.identity import COOKIE_NAME, credential_digest

    raw = learner.cookies.get(COOKIE_NAME)
    owner = learner.get("/api/v1/learners/me").json()["learner_id"]
    with database.session() as db, db.begin():
        db.execute(
            update(m.LearnerCredential).values(expires_at=datetime.now(UTC) + timedelta(days=1))
        )
    renewed = learner.post("/api/v1/learners/anonymous", json={})
    assert renewed.status_code == 200 and renewed.json()["learner_id"] == owner
    assert learner.cookies.get(COOKIE_NAME) == raw
    assert "httponly" in renewed.headers["set-cookie"].lower()
    assert datetime.fromisoformat(renewed.json()["expires_at"]) > datetime.now(UTC) + timedelta(
        days=29
    )
    with database.session() as fresh:
        rows = fresh.scalars(select(m.LearnerCredential)).all()
        assert len(rows) == 1 and rows[0].token_hash == credential_digest(raw)
    assert raw not in renewed.text


@pytest.mark.parametrize("race", ["revoked", "expired"])
def test_bootstrap_cannot_renew_a_credential_invalidated_between_read_and_write(
    learner: TestClient,
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
    race: str,
) -> None:
    from app.services.identity import IdentityService

    original_session = complete_original(learner)
    old_owner = learner.get("/api/v1/learners/me").json()["learner_id"]
    with database.session() as db, db.begin():
        db.execute(
            update(m.LearnerCredential).values(expires_at=datetime.now(UTC) + timedelta(days=1))
        )
    authenticate = IdentityService.authenticate

    def invalidate_after_read(service, raw):
        credential = authenticate(service, raw)
        with database.session() as db, db.begin():
            values = (
                {"revoked_at": datetime.now(UTC)}
                if race == "revoked"
                else {"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
            )
            db.execute(
                update(m.LearnerCredential)
                .where(m.LearnerCredential.id == credential.id)
                .values(**values)
            )
        return credential

    monkeypatch.setattr(IdentityService, "authenticate", invalidate_after_read)
    response = learner.post("/api/v1/learners/anonymous", json={})
    assert response.status_code == 200 and response.json()["learner_id"] != old_owner
    monkeypatch.setattr(IdentityService, "authenticate", authenticate)
    assert learner.get(f"/api/v1/sessions/{original_session}").status_code == 404
