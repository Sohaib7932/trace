"""Legacy wire contracts: frozen schemas plus responses from the real application."""

import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from tests.integration.test_learning import attempt, post, predict, progress, start, verify

SNAPSHOT = Path(__file__).parents[1] / "fixtures" / "legacy_api_contracts.json"
FORBIDDEN = {
    "expected_field",
    "prediction_answer",
    "content_hash",
    "question_hash",
    "idempotency_key",
    "token_hash",
    "private",
}


def freeze_contract(document, paths):
    """Freeze only the named legacy operations and their referenced public schemas."""
    operations = {
        path: {
            method: {
                key: value
                for key, value in operation.items()
                if key in {"operationId", "parameters", "requestBody", "responses", "security"}
            }
            for method, operation in document["paths"][path].items()
            if method in {"get", "post", "put", "patch", "delete", "options", "head"}
        }
        for path in paths
    }
    schemas = {}

    def visit(value):
        if isinstance(value, dict):
            reference = value.get("$ref", "")
            if reference.startswith("#/components/schemas/"):
                name = reference.rsplit("/", 1)[1]
                if name not in schemas:
                    schemas[name] = document["components"]["schemas"][name]
                    visit(schemas[name])
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(operations)
    return {"paths": operations, "schemas": schemas}


def assert_public(value):
    if isinstance(value, dict):
        assert not FORBIDDEN.intersection(value)
        for child in value.values():
            assert_public(child)
    elif isinstance(value, list):
        for child in value:
            assert_public(child)


def assert_fields(value, name, snapshot):
    assert set(value) == set(snapshot["contract"]["schemas"][name]["properties"])
    assert_public(value)


def test_legacy_openapi_matches_frozen_contract(app):
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert freeze_contract(app.openapi(), snapshot["contract"]["paths"]) == snapshot["contract"]


def test_real_legacy_responses_and_errors_keep_the_frozen_contract(learner, learning_app):
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    lesson = learner.get("/api/v1/lessons/fastapi-payload-mismatch").json()
    assert_fields(lesson, "LessonResponse", snapshot)
    session = start(learner)
    initial = progress(learner, session)
    assert initial["lesson"]["version"] == "1.0.0"
    assert initial["session"]["lesson_version_id"] == lesson["version_id"]
    assert initial["prediction"] is None
    assert initial["attempts"] == initial["verifications"] == []
    assert_fields(initial, "ProgressResponse", snapshot)
    assert_fields(initial["session"], "SessionResponse", snapshot)
    assert_fields(initial["summary"], "EvidenceSummary", snapshot)

    errors = {
        "missing_lesson": learner.get("/api/v1/lessons/not-a-lesson"),
        "extra_request_field": post(
            learner,
            "/sessions",
            {
                "lesson_id": lesson["id"],
                "unexpected": True,
            },
        ),
        "attempt_before_prediction": post(
            learner,
            f"/sessions/{session}/attempts",
            {
                "change_type": "rename_payload_field",
                "field_name": "body",
            },
        ),
    }
    with TestClient(learning_app) as stranger:
        errors["unauthenticated"] = stranger.get(f"/api/v1/sessions/{session}/progress")
        stranger.headers.update(
            {"Origin": "http://localhost:3000", "X-Trace-Client": "learning-web"}
        )
        assert stranger.post("/api/v1/learners/anonymous", json={}).status_code == 200
        errors["foreign_session"] = stranger.get(f"/api/v1/sessions/{session}/progress")
    for name, response in errors.items():
        body = response.json()
        assert body["error"]["request_id"] == response.headers["X-Request-ID"]
        body["error"]["request_id"] = "<request-id>"
        assert {"status": response.status_code, "body": body} == snapshot["errors"][name]

    prediction = predict(learner, session).json()
    assert_fields(prediction, "PredictionResponse", snapshot)
    bad = attempt(learner, session)
    assert_fields(bad, "AttemptResponse", snapshot)
    failed = verify(learner, session, bad["id"]).json()
    assert failed["status"] == "failed"
    assert_fields(failed, "RunResponse", snapshot)
    assert {check["code"] for check in failed["checks"]} == {
        "http_status",
        "api_response",
        "validation",
        "row_count",
        "stored_values",
    }
    hint = post(learner, f"/sessions/{session}/hints", {"attempt_id": bad["id"]}).json()
    assert_fields(hint, "HintResponse", snapshot)
    good = attempt(learner, session, "content")
    passed = verify(learner, session, good["id"]).json()
    assert passed["status"] == "passed" and all(check["matched"] for check in passed["checks"])
    for run in [failed, passed]:
        for check in run["checks"]:
            assert_fields(check, "CheckResponse", snapshot)
    saved = progress(learner, session)
    assert saved["prediction"] == prediction
    assert saved["attempts"] == [bad, good]
    assert saved["hints"] == [hint]
    assert_fields(saved, "ProgressResponse", snapshot)
    for event in saved["events"]:
        assert_fields(event, "EventResponse", snapshot)
    assert_fields(learner.get("/api/v1/learners/me/journey").json(), "JourneyResponse", snapshot)
    assert learner.get(f"/api/v1/sessions/{session}/prediction").json() == prediction
    assert learner.get(f"/api/v1/sessions/{session}/attempts").json() == [bad, good]
    assert learner.get(f"/api/v1/sessions/{session}/verifications").json() == [failed, passed]
    # Forged client evidence is rejected before a new run is created.
    assert (
        post(
            learner,
            f"/sessions/{session}/attempts/{good['id']}/verify",
            {
                "status": "passed",
                "checks": [],
            },
            str(uuid4()),
        ).status_code
        == 422
    )
    assert progress(learner, session) == saved
