import io
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, select, update
from sqlalchemy.exc import IntegrityError, OperationalError

from app.ai.providers.fake import FakeTutorProvider
from app.api.dependencies import get_notes_verifier, get_tutor_provider
from app.db import models as m
from app.db.learning import SqlLearningRepository
from app.db.session import Database
from app.domain.learning import LearningError
from app.services.catalog import LESSON_ID, PUBLIC_CONTENT, lesson_hash, seed_first_lesson
from app.services.identity import COOKIE_NAME, credential_digest
from app.services.learning import LearningService


def post(client: TestClient, path: str, body: dict[str, object], key: str | None = None):
    return client.post(
        "/api/v1" + path, json=body, headers={"Idempotency-Key": key or str(uuid4())}
    )


def start(client: TestClient) -> str:
    response = post(client, "/sessions", {"lesson_id": LESSON_ID, "version": "1.0.0"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def predict(client: TestClient, session: str, key: str | None = None):
    return post(
        client,
        f"/sessions/{session}/prediction",
        {"selected_answer": "rejected", "reasoning": "  The field names differ.  "},
        key,
    )


def attempt(client: TestClient, session: str, field: str = "body", key: str | None = None):
    response = post(
        client,
        f"/sessions/{session}/attempts",
        {"change_type": "rename_payload_field", "field_name": field},
        key,
    )
    assert response.status_code == 201, response.text
    return response.json()


def verify(client: TestClient, session: str, attempt_id: str, key: str | None = None):
    return post(client, f"/sessions/{session}/attempts/{attempt_id}/verify", {}, key)


def progress(client: TestClient, session: str):
    response = client.get(f"/api/v1/sessions/{session}/progress")
    assert response.status_code == 200, response.text
    return response.json()


def test_complete_real_journey_preserves_prediction_attempts_and_fresh_evidence(
    learner: TestClient, database: Database
) -> None:
    session = start(learner)
    original = predict(learner, session).json()
    wrong = attempt(learner, session)
    failed = verify(learner, session, wrong["id"])
    assert failed.status_code == 200, failed.text
    failed_run = failed.json()
    assert failed_run["status"] == "failed"
    checks = {c["code"]: c for c in failed_run["checks"]}
    assert checks["http_status"]["observed"] == "422"
    assert checks["row_count"]["observed"] == "0"
    details = json.loads(checks["api_response"]["observed"])["detail"]
    assert {e["type"] for e in details} == {"missing", "extra_forbidden"}
    with database.session() as fresh:
        assert (
            fresh.scalars(
                select(m.RuntimeNote).where(m.RuntimeNote.run_id == UUID(failed_run["id"]))
            ).all()
            == []
        )
    hint = post(learner, f"/sessions/{session}/hints", {"attempt_id": wrong["id"]}).json()
    assert hint["provider"] == "fake" and hint["fixture"] == "fake-v1"
    corrected = attempt(learner, session, "content")
    passed = verify(learner, session, corrected["id"]).json()
    assert passed["status"] == "passed"
    assert all(c["matched"] for c in passed["checks"])
    with database.session() as fresh:
        notes = fresh.scalars(
            select(m.RuntimeNote).where(m.RuntimeNote.run_id == UUID(passed["id"]))
        ).all()
        assert [(n.title, n.content) for n in notes] == [
            ("Trace verification note", "Understanding request validation")
        ]
    saved = progress(learner, session)
    assert saved["session"]["state"] == "completed" and saved["session"]["completed_at"]
    assert (
        saved["prediction"] == original and original["reasoning"] == "  The field names differ.  "
    )
    assert [a["field_name"] for a in saved["attempts"]] == ["body", "content"]
    assert [a["hints_before"] for a in saved["attempts"]] == [0, 1]
    assert (
        saved["summary"]["correct_after_revision"] and saved["summary"]["hint_assisted_correction"]
    )
    assert saved["summary"]["prediction_correct"] is True
    assert saved["summary"]["hints_delivered"] == 1
    assert learner.get(f"/api/v1/sessions/{session}/prediction").json() == original
    assert len(learner.get(f"/api/v1/sessions/{session}/attempts").json()) == 2
    assert len(learner.get(f"/api/v1/sessions/{session}/verifications").json()) == 2


def test_identity_reuse_hashing_and_no_raw_secret_in_rows_or_logs(
    learner: TestClient, database: Database, learning_app: FastAPI
) -> None:
    raw = learner.cookies.get(COOKIE_NAME)
    output = io.StringIO()
    learning_app.state.logger.handlers[0].setStream(output)
    first = learner.get("/api/v1/learners/me").json()
    assert learner.post("/api/v1/learners/anonymous", json={}).json() == first
    with database.session() as session:
        credentials = session.scalars(select(m.LearnerCredential)).all()
        assert len(credentials) == 1
        assert credentials[0].token_hash == credential_digest(raw)
        for table in m.Base.metadata.sorted_tables:
            assert raw not in str(session.execute(select(table)).all())
    assert raw not in output.getvalue() and raw not in json.dumps(first)


@pytest.mark.parametrize("kind", ["missing", "expired", "revoked", "uuid"])
def test_invalid_credentials_rejected(learner: TestClient, database: Database, kind: str) -> None:
    if kind in {"expired", "revoked"}:
        with database.session() as session, session.begin():
            session.execute(
                update(m.LearnerCredential).values(
                    **(
                        {"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
                        if kind == "expired"
                        else {"revoked_at": datetime.now(UTC)}
                    )
                )
            )
    else:
        learner.cookies.clear()
        if kind == "uuid":
            learner.cookies.set(COOKIE_NAME, str(uuid4()), path="/api/v1")
    assert learner.get("/api/v1/learners/me").status_code == 401


def test_cookie_flags_and_explicit_revocation(learner: TestClient, learning_app: FastAPI) -> None:
    with TestClient(learning_app) as other:
        response = other.post(
            "/api/v1/learners/anonymous",
            json={},
            headers={"Origin": "http://localhost:3000", "X-Trace-Client": "learning-web"},
        )
        cookie = response.headers["set-cookie"].lower()
        assert (
            "httponly" in cookie
            and "samesite=lax" in cookie
            and "path=/api/v1" in cookie
            and "max-age=" in cookie
        )
    assert post(learner, "/learners/me/revoke", {}).status_code == 204
    assert learner.get("/api/v1/learners/me").status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "http://localhost:3000"},
        {"X-Trace-Client": "learning-web"},
        {"Origin": "https://foreign.example", "X-Trace-Client": "learning-web"},
    ],
)
def test_write_protection_rejects_missing_or_foreign_origin(
    learning_app: FastAPI, headers: dict[str, str]
) -> None:
    with TestClient(learning_app) as client:
        assert (
            client.post("/api/v1/learners/anonymous", json={}, headers=headers).status_code == 403
        )


def test_credential_cors_and_ownership_scope(learner: TestClient, learning_app: FastAPI) -> None:
    session = start(learner)
    response = learner.options(
        "/api/v1/sessions",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-Trace-Client,Idempotency-Key",
        },
    )
    assert (
        response.status_code == 200
        and response.headers["access-control-allow-credentials"] == "true"
    )
    with TestClient(learning_app) as other:
        other.headers.update({"Origin": "http://localhost:3000", "X-Trace-Client": "learning-web"})
        other.post("/api/v1/learners/anonymous", json={})
        foreign = other.get(f"/api/v1/sessions/{session}")
        absent = other.get(f"/api/v1/sessions/{uuid4()}")
        assert foreign.status_code == absent.status_code == 404
        assert foreign.json()["error"]["message"] == absent.json()["error"]["message"]
        assert (
            post(
                other,
                f"/sessions/{session}/prediction",
                {"selected_answer": "saved", "reasoning": "x"},
            ).status_code
            == 404
        )


def test_seed_hash_idempotence_and_version_pinning(learner: TestClient, database: Database) -> None:
    repository = SqlLearningRepository(database)
    first = seed_first_lesson(repository)
    assert seed_first_lesson(repository) == first
    assert first.content_hash == lesson_hash(PUBLIC_CONTENT, "content", "rejected")
    session = start(learner)
    new = replace(
        first, id=uuid4(), version="1.1.0", created_at=first.created_at + timedelta(seconds=1)
    )
    with repository.write() as store:
        store.publish(new)
    public = learner.get("/api/v1/lessons/" + LESSON_ID).json()
    assert public["version"] == "1.1.0"
    assert (
        "expected_field" not in public
        and "prediction_answer" not in public
        and "content_hash" not in public
    )
    assert progress(learner, session)["lesson"]["version_id"] == str(first.id)
    assert learner.get("/api/v1/lessons/missing").status_code == 404
    assert learner.get("/api/v1/lessons/" + LESSON_ID + "?version=9.0.0").status_code == 404


def test_seed_refuses_changed_content(database: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    repository = SqlLearningRepository(database)
    seed_first_lesson(repository)
    monkeypatch.setitem(PUBLIC_CONTENT, "title", "Changed published title")
    with pytest.raises(LearningError, match="new version"):
        seed_first_lesson(repository)


def test_prediction_and_attempt_retry_conflicts_and_lifecycle(learner: TestClient) -> None:
    session = start(learner)
    assert learner.get(f"/api/v1/sessions/{session}/prediction").json() is None
    assert (
        post(
            learner,
            f"/sessions/{session}/attempts",
            {"change_type": "rename_payload_field", "field_name": "body"},
        ).status_code
        == 409
    )
    assert post(learner, f"/sessions/{session}/hints", {}).status_code == 409
    key = str(uuid4())
    original = predict(learner, session, key).json()
    assert predict(learner, session, key).json() == original
    assert predict(learner, session).status_code == 409
    assert (
        post(
            learner,
            f"/sessions/{session}/prediction",
            {"selected_answer": "saved", "reasoning": "changed"},
            key,
        ).status_code
        == 409
    )
    assert (
        post(
            learner,
            f"/sessions/{session}/attempts",
            {"change_type": "execute_python", "field_name": "other"},
        ).status_code
        == 422
    )
    key = str(uuid4())
    a = attempt(learner, session, key=key)
    assert attempt(learner, session, key=key) == a
    assert (
        post(
            learner,
            f"/sessions/{session}/attempts",
            {"change_type": "rename_payload_field", "field_name": "content"},
            key,
        ).status_code
        == 409
    )
    assert (
        post(
            learner,
            f"/sessions/{session}/attempts",
            {"change_type": "rename_payload_field", "field_name": "body"},
        ).status_code
        == 409
    )


def test_session_creation_retry_and_forged_completion_rejected(learner: TestClient) -> None:
    key = str(uuid4())
    first = post(learner, "/sessions", {"lesson_id": LESSON_ID}, key)
    assert post(learner, "/sessions", {"lesson_id": LESSON_ID}, key).json() == first.json()
    assert (
        post(learner, "/sessions", {"lesson_id": LESSON_ID, "state": "completed"}).status_code
        == 422
    )
    session = first.json()["id"]
    assert post(learner, f"/sessions/{session}/abandon", {}).json()["state"] == "abandoned"
    assert post(learner, f"/sessions/{session}/abandon", {}).json()["state"] == "abandoned"
    assert predict(learner, session).status_code == 409


def test_verification_retries_do_not_duplicate_notes_or_reuse_another_run(
    learner: TestClient, database: Database
) -> None:
    session = start(learner)
    predict(learner, session)
    good = attempt(learner, session, "content")
    key = str(uuid4())
    original = verify(learner, session, good["id"], key).json()
    assert original["status"] == "passed"
    assert verify(learner, session, good["id"], key).json() == original
    assert verify(learner, session, good["id"]).json() == original
    second = start(learner)
    predict(learner, second)
    bad = attempt(learner, second)
    failed = verify(learner, second, bad["id"]).json()
    assert failed["status"] == "failed"
    assert post(learner, f"/sessions/{second}/attempts/{good['id']}/verify", {}).status_code == 404
    with database.session() as fresh:
        assert len(fresh.scalars(select(m.RuntimeNote)).all()) == 1
    assert (
        post(
            learner,
            f"/sessions/{session}/attempts",
            {"change_type": "rename_payload_field", "field_name": "body"},
        ).status_code
        == 409
    )
    assert post(learner, f"/sessions/{session}/abandon", {}).status_code == 409


def test_forged_verification_payload_cannot_pass(learner: TestClient) -> None:
    session = start(learner)
    predict(learner, session)
    a = attempt(learner, session)
    forged = post(
        learner,
        f"/sessions/{session}/attempts/{a['id']}/verify",
        {"success": True, "status": "passed"},
    )
    assert forged.status_code == 422
    assert progress(learner, session)["verifications"] == []


def test_hints_progress_limit_retry_and_foreign_attempt(learner: TestClient) -> None:
    session = start(learner)
    predict(learner, session)
    assert (
        post(learner, f"/sessions/{session}/hints", {"attempt_id": str(uuid4())}).status_code == 404
    )
    key = str(uuid4())
    first = post(learner, f"/sessions/{session}/hints", {}, key).json()
    assert post(learner, f"/sessions/{session}/hints", {}, key).json() == first
    hints = [first] + [post(learner, f"/sessions/{session}/hints", {}).json() for _ in range(2)]
    assert [h["sequence"] for h in hints] == [1, 2, 3]
    assert len({h["text"] for h in hints}) == 3
    assert post(learner, f"/sessions/{session}/hints", {}).status_code == 409
    assert progress(learner, session)["summary"]["hints_delivered"] == 3


def test_provider_exception_is_recorded_without_invented_guidance(
    learner: TestClient, learning_app: FastAPI
) -> None:
    class Broken(FakeTutorProvider):
        def generate_hint(self, request):
            raise RuntimeError("sensitive-provider-detail")

    learning_app.dependency_overrides[get_tutor_provider] = lambda: Broken()
    session = start(learner)
    predict(learner, session)
    result = post(learner, f"/sessions/{session}/hints", {}).json()
    assert result["status"] == "error" and result["text"] is None
    assert "sensitive" not in json.dumps(result)
    assert progress(learner, session)["prediction"]["reasoning"] == "  The field names differ.  "


def test_verifier_failure_is_error_and_new_key_can_retry(
    learner: TestClient, learning_app: FastAPI
) -> None:
    class BrokenVerifier:
        def observe(self, run_id, field_name):
            raise RuntimeError("sensitive-infrastructure-detail")

    learning_app.dependency_overrides[get_notes_verifier] = lambda: BrokenVerifier()
    session = start(learner)
    predict(learner, session)
    a = attempt(learner, session, "content")
    key = str(uuid4())
    result = verify(learner, session, a["id"], key).json()
    assert result["status"] == "error" and "sensitive" not in json.dumps(result)
    assert progress(learner, session)["session"]["state"] == "verification_pending"
    learning_app.dependency_overrides.clear()
    assert verify(learner, session, a["id"], key).json() == result
    assert verify(learner, session, a["id"]).json()["status"] == "passed"


def test_commit_failure_is_not_a_learner_mistake(learner: TestClient, database: Database) -> None:
    session = start(learner)
    predict(learner, session)
    a = attempt(learner, session, "content")

    def fail_notes_write(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO RUNTIME_NOTES"):
            raise OperationalError("private-db", {}, RuntimeError("private-token"))

    event.listen(database.engine, "before_cursor_execute", fail_notes_write)
    try:
        result = verify(learner, session, a["id"]).json()
    finally:
        event.remove(database.engine, "before_cursor_execute", fail_notes_write)
    assert result["status"] == "error" and "private" not in json.dumps(result)
    with database.session() as fresh:
        assert fresh.scalars(select(m.RuntimeNote)).all() == []


def test_append_only_and_published_records_cannot_be_modified(
    learner: TestClient, database: Database
) -> None:
    session_id = start(learner)
    predict(learner, session_id)
    attempt(learner, session_id)
    for statement in [
        update(m.LessonVersion).values(expected_field="body"),
        update(m.Prediction).values(reasoning="rewritten"),
        update(m.Attempt).values(field_name="content"),
    ]:
        with pytest.raises(IntegrityError), database.session() as db, db.begin():
            db.execute(statement)
    with pytest.raises(IntegrityError), database.session() as db, db.begin():
        db.execute(
            update(m.LearningSession).values(state="completed", completed_at=datetime.now(UTC))
        )


def test_concurrent_identical_prediction_and_attempt_use_independent_transactions(
    learner: TestClient, database: Database
) -> None:
    session = UUID(start(learner))
    owner = UUID(learner.get("/api/v1/learners/me").json()["learner_id"])
    service = LearningService(SqlLearningRepository(database), FakeTutorProvider())
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: service.predict(owner, session, "rejected", "original", key), range(2)
            )
        )
    assert results[0].id == results[1].id
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: service.attempt(owner, session, "body", "", key), range(2))
        )
    assert results[0].id == results[1].id
    assert len(service.progress(owner, session).attempts) == 1


def test_saved_session_survives_database_reopen(learner: TestClient, database: Database) -> None:
    session = start(learner)
    original = predict(learner, session).json()
    reopened = Database(database_settings := learner.app.state.settings)
    try:
        from app.main import create_app

        with TestClient(create_app(database_settings, reopened)) as resumed:
            resumed.cookies.update(learner.cookies)
            assert progress(resumed, session)["prediction"] == original
    finally:
        reopened.dispose()
