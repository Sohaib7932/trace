"""Learner-requested lessons over HTTP with the deterministic test transport.

No key, no network, never real Gemini.
"""

import json
import logging
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import update

from app.ai.client import AITransportError
from app.core.custom_lesson_settings import CustomLessonSettings
from app.db.custom_lesson_models import CustomLessonRequestRow
from app.services.custom_lesson_generation import (
    DraftRejected,
    LessonDraft,
    LessonRequestData,
    validate_draft,
)
from app.services.custom_lessons import Owner
from tests.integration.test_live_ai_http import api as api  # noqa: F401

TOPIC = "Teach me how FastAPI validates a request body zq-marker-topic"
BODY = {"topic": TOPIC, "language": "Python", "framework": "FastAPI", "lesson_count": 1}


def challenge(**overrides):
    base = {
        "kind": "multiple_choice",
        "prompt": "What status does FastAPI return when a required field is missing?",
        "code": "from pydantic import BaseModel\n\nclass Note(BaseModel):\n    title: str\n",
        "options": ["200 OK", "422 Unprocessable Content", "500 Internal Server Error"],
        "correct_option": 1,
        "model_answer": "",
        "hints": ["Think about who checks the body.", "Pydantic runs first.", "It's a 4xx code."],
        "explanation": "Validation fails before the route runs, so FastAPI answers 422.",
        "verification_mode": "answer_key",
    }
    return {**base, **overrides}


def explain_challenge():
    return challenge(
        kind="explain",
        prompt="Explain why the route body never runs for an invalid request.",
        code="",
        options=[],
        correct_option=-1,
        model_answer="Validation happens before the handler is called.",
        hints=["Order matters.", "What runs first?", "Think about dependencies."],
        verification_mode="practice_only",
    )


def lesson(**overrides):
    base = {
        "status": "lesson",
        "decline_reason": "none",
        "language": "Python",
        "title": "Request validation in FastAPI zq-marker-output",
        "objective": "Predict what FastAPI does with an invalid body.",
        "sections": [
            {"heading": "Validation first", "body": "FastAPI checks the body with Pydantic."}
        ],
        "challenges": [
            challenge(),
            challenge(prompt="Which part of the code declares the shape?"),
            explain_challenge(),
        ],
    }
    return json.dumps({**base, **overrides})


def create(api, body=None, key=None):
    return api.client.post(
        "/api/v1/custom-lessons/requests",
        json=body or BODY,
        headers={"Idempotency-Key": str(key or uuid4())},
    )


def finish(api, request_id):
    assert api.app.state.custom_lessons.runner.wait_for_idle(5)
    return api.client.get(f"/api/v1/custom-lessons/requests/{request_id}").json()


def generation_calls(api):
    return [call for call in api.provider.calls if call.capability == "generation"]


def ready_lesson(api):
    api.provider.text = lesson()
    response = create(api)
    assert response.status_code == 202, response.text
    status = finish(api, response.json()["id"])
    assert status["status"] == "ready", status
    return status["lesson_ids"][0]


def test_create_returns_immediately_then_generates_one_valid_private_lesson(api):
    api.provider.text = lesson()
    response = create(api)
    assert response.status_code == 202
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["status"] in {"queued", "generating", "ready"}
    status = finish(api, response.json()["id"])
    assert (
        status["status"] == "ready"
        and status["lessons_ready"] == 1
        and status["error_code"] is None
    )
    calls = generation_calls(api)
    assert len(calls) == 1
    data = json.loads(calls[0].data_json)
    assert data["untrusted_request"]["topic"] == TOPIC
    assert TOPIC not in calls[0].instructions  # the request is data, never instructions
    # Its own provider timeout (about 20 s remaining), well above the tutor's 10 s.
    assert 15 < calls[0].response_timeout_seconds <= 20.0
    body = api.client.get(f"/api/v1/custom-lessons/{status['lesson_ids'][0]}").json()
    assert body["title"].startswith("Request validation") and len(body["challenges"]) == 3
    assert {c["verification_mode"] for c in body["challenges"]} == {"answer_key", "practice_only"}
    raw = json.dumps(body)
    assert "correct_option" not in raw and "model_answer" not in raw
    assert all(c["explanation"] is None for c in body["challenges"])


def test_answers_are_checked_on_the_server_and_never_return_the_key(api):
    lesson_id = ready_lesson(api)
    view = api.client.get(f"/api/v1/custom-lessons/{lesson_id}").json()
    choice, explain = view["challenges"][0], view["challenges"][2]
    url = f"/api/v1/custom-lessons/{lesson_id}/challenges/{choice['id']}/answers"
    wrong = api.client.post(
        url, json={"selected_option": 0}, headers={"Idempotency-Key": str(uuid4())}
    )
    assert wrong.status_code == 200 and wrong.json()["correct"] is False
    assert (
        wrong.json()["verification_mode"] == "answer_key" and wrong.json()["model_answer"] is None
    )
    key = str(uuid4())
    right = api.client.post(url, json={"selected_option": 1}, headers={"Idempotency-Key": key})
    assert right.json()["correct"] is True and right.json()["attempts"] == 2
    replay = api.client.post(url, json={"selected_option": 1}, headers={"Idempotency-Key": key})
    assert replay.json() == right.json()
    conflict = api.client.post(url, json={"selected_option": 2}, headers={"Idempotency-Key": key})
    assert (
        conflict.status_code == 409 and conflict.json()["error"]["code"] == "idempotency_conflict"
    )
    for response in (wrong, right, replay):
        assert "correct_option" not in response.text
    practice = api.client.post(
        f"/api/v1/custom-lessons/{lesson_id}/challenges/{explain['id']}/answers",
        json={"text": "Because validation runs before the handler."},
        headers={"Idempotency-Key": str(uuid4())},
    ).json()
    assert practice["correct"] is None and practice["verification_mode"] == "practice_only"
    assert practice["model_answer"]
    after = api.client.get(f"/api/v1/custom-lessons/{lesson_id}").json()
    assert after["completed_challenges"] == 2
    assert (
        after["challenges"][0]["answered_correctly"] is True
        and after["challenges"][0]["explanation"]
    )
    assert after["challenges"][2]["answered_correctly"] is None
    invalid = api.client.post(
        url, json={"selected_option": 7}, headers={"Idempotency-Key": str(uuid4())}
    )
    assert invalid.status_code == 422


def test_malformed_output_gets_exactly_one_retry(api):
    outputs = iter(["not json", lesson()])
    api.provider.callback = lambda: setattr(api.provider, "text", next(outputs))
    status = finish(api, create(api).json()["id"])
    assert status["status"] == "ready" and len(generation_calls(api)) == 2


def test_malformed_twice_fails_without_saving(api):
    api.provider.text = '{"status": "lesson"}'
    status = finish(api, create(api).json()["id"])
    assert status["status"] == "failed" and status["error_code"] == "invalid_output"
    assert status["lesson_ids"] == [] and len(generation_calls(api)) == 2
    assert status["message"]


@pytest.mark.parametrize(
    ("draft", "code"),
    [
        (
            lesson(
                challenges=[
                    challenge(hints=["It is 422 Unprocessable Content.", "b", "c"]),
                    challenge(),
                    challenge(),
                ]
            ),
            "answer_leak",
        ),
        (
            lesson(challenges=[challenge(correct_option=5), challenge(), challenge()]),
            "missing_correct_option",
        ),
        (
            lesson(challenges=[challenge(code="def broken(:\n    pass"), challenge(), challenge()]),
            "invalid_python",
        ),
        (
            lesson(sections=[{"heading": "Read", "body": "See https://example.com"}]),
            "unsafe_output",
        ),
        (lesson(language="JavaScript"), "language_mismatch"),
    ],
)
def test_validation_rejections_fail_the_job_and_save_nothing(api, draft, code):
    api.provider.text = draft
    status = finish(api, create(api).json()["id"])
    assert status["status"] == "failed" and status["error_code"] == code
    assert status["lesson_ids"] == [] and len(generation_calls(api)) == 1  # no retry on semantics


def test_model_decline_marks_the_request_rejected_with_a_rewrite_hint(api):
    api.provider.text = lesson(
        status="declined", decline_reason="off_topic", challenges=[], sections=[]
    )
    status = finish(api, create(api).json()["id"])
    assert status["status"] == "rejected" and status["error_code"] == "off_topic"
    assert "programming topic" in status["message"]


@pytest.mark.parametrize(
    ("error", "code"), [("rate_limited", "provider_rate_limited"), ("timeout", "provider_timeout")]
)
def test_provider_errors_fail_without_retrying_rate_limits(api, error, code):
    api.provider.error = AITransportError(error)
    status = finish(api, create(api).json()["id"])
    assert status["status"] == "failed" and status["error_code"] == code
    assert len(generation_calls(api)) == 1


def test_request_rate_and_daily_limits_are_typed_429s(api):
    runtime = api.app.state.custom_lessons
    runtime.service.settings = CustomLessonSettings(
        requests_per_minute=1, daily_requests_per_account=5
    )
    api.provider.text = lesson()
    assert create(api).status_code == 202
    limited = create(api)
    assert (
        limited.status_code == 429
        and limited.json()["error"]["code"] == "custom_lesson_rate_limited"
    )
    runtime.service.settings = CustomLessonSettings(
        requests_per_minute=10, daily_requests_per_account=1
    )
    quota = create(api)
    assert (
        quota.status_code == 429 and quota.json()["error"]["code"] == "custom_lesson_quota_reached"
    )
    runtime.runner.wait_for_idle(5)


@pytest.mark.parametrize(
    ("topic", "code"),
    [
        ("Teach me FastAPI, my password: hunter2hunter2 thanks", "custom_lesson_sensitive_input"),
        ("Teach me how to write ransomware in Python", "custom_lesson_policy_rejected"),
    ],
)
def test_unsafe_or_secret_requests_are_rejected_before_any_provider_call(api, topic, code):
    response = create(api, {**BODY, "topic": topic})
    assert response.status_code == 422 and response.json()["error"]["code"] == code
    assert generation_calls(api) == []


def test_invalid_bodies_are_rejected(api):
    for body in (
        {**BODY, "topic": "short"},
        {**BODY, "lesson_count": 4},
        {**BODY, "extra": 1},
        {**BODY, "practice_styles": []},
    ):
        assert create(api, body).status_code == 422


def test_create_is_idempotent(api):
    api.provider.text = lesson()
    key = uuid4()
    first = create(api, key=key).json()
    again = create(api, key=key)
    assert again.status_code == 202 and again.json()["id"] == first["id"]
    conflict = create(api, {**BODY, "lesson_count": 2}, key=key)
    assert conflict.status_code == 409
    finish(api, first["id"])
    assert len(generation_calls(api)) == 1


def test_cancel_stops_saving_the_lesson(api):
    request_holder = {}

    def cancel_mid_generation():
        api.client.post(f"/api/v1/custom-lessons/requests/{request_holder['id']}/cancel")

    api.provider.text = lesson()
    api.provider.callback = cancel_mid_generation
    request_holder["id"] = create(api).json()["id"]
    status = finish(api, request_holder["id"])
    assert status["status"] == "cancelled" and status["lesson_ids"] == []


def test_restart_and_stale_jobs_are_marked_failed(api):
    api.provider.text = lesson()
    request_id = create(api).json()["id"]
    finish(api, request_id)
    service = api.app.state.custom_lessons.service
    old = api.clock() - timedelta(seconds=service.settings.stale_after_seconds + 1)
    with api.database.session() as session, session.begin():
        session.execute(update(CustomLessonRequestRow).values(status="generating", updated_at=old))
    assert service.recover_interrupted() == 1
    assert (
        api.client.get(f"/api/v1/custom-lessons/requests/{request_id}").json()["error_code"]
        == "interrupted"
    )
    old = api.clock() - timedelta(hours=2)
    with api.database.session() as session, session.begin():
        session.execute(update(CustomLessonRequestRow).values(status="queued", updated_at=old))
    stale = api.client.get(f"/api/v1/custom-lessons/requests/{request_id}").json()
    assert stale["status"] == "failed" and stale["error_code"] == "interrupted"


def test_another_account_cannot_see_or_change_anything(api):
    lesson_id = ready_lesson(api)
    request_id = api.client.get(f"/api/v1/custom-lessons/{lesson_id}").json()["request_id"]
    challenge_id = api.client.get(f"/api/v1/custom-lessons/{lesson_id}").json()["challenges"][0][
        "id"
    ]
    other = {"Authorization": "Bearer " + api.signer.token({"sub": str(uuid4())})}
    assert (
        api.client.get(f"/api/v1/custom-lessons/requests/{request_id}", headers=other).status_code
        == 404
    )
    assert (
        api.client.post(
            f"/api/v1/custom-lessons/requests/{request_id}/cancel", headers=other
        ).status_code
        == 404
    )
    assert api.client.get(f"/api/v1/custom-lessons/{lesson_id}", headers=other).status_code == 404
    assert (
        api.client.delete(f"/api/v1/custom-lessons/{lesson_id}", headers=other).status_code == 404
    )
    answer = api.client.post(
        f"/api/v1/custom-lessons/{lesson_id}/challenges/{challenge_id}/answers",
        json={"selected_option": 1},
        headers={**other, "Idempotency-Key": str(uuid4())},
    )
    assert answer.status_code == 404
    assert api.client.get("/api/v1/custom-lessons", headers=other).json() == {"items": []}
    assert len(api.client.get("/api/v1/custom-lessons").json()["items"]) == 1


def test_delete_removes_the_lesson(api):
    lesson_id = ready_lesson(api)
    assert api.client.delete(f"/api/v1/custom-lessons/{lesson_id}").status_code == 204
    assert api.client.get(f"/api/v1/custom-lessons/{lesson_id}").status_code == 404


def test_guests_and_disabled_feature_get_typed_errors(api):
    guest = api.client.get("/api/v1/custom-lessons", headers={"Authorization": ""})
    assert guest.status_code in {401, 403}
    api.app.state.custom_lessons.service.available = False
    response = create(api)
    assert (
        response.status_code == 503
        and response.json()["error"]["code"] == "custom_lessons_unavailable"
    )
    languages = api.client.get("/api/v1/custom-lessons/languages").json()
    assert languages["generation_available"] is False


def test_languages_never_claim_server_verification(api):
    languages = api.client.get("/api/v1/custom-lessons/languages").json()
    assert {item["verification"] for item in languages["items"]} == {"answer_key"}
    assert "server_verified" not in json.dumps(languages)


def test_no_prompt_or_model_output_is_logged(api, caplog):
    caplog.set_level(logging.DEBUG)
    api.provider.text = lesson()
    finish(api, create(api).json()["id"])
    api.provider.text = "garbage"
    finish(api, create(api, {**BODY, "lesson_count": 2}).json()["id"])
    assert "zq-marker-topic" not in caplog.text and "zq-marker-output" not in caplog.text


def test_validate_draft_unit_rules():
    request = LessonRequestData(
        TOPIC, "Python", "FastAPI", "beginner", "understand", ("multiple_choice", "explain")
    )
    good = LessonDraft.model_validate_json(lesson())
    assert validate_draft(good, request) is good
    find_bug = LessonDraft.model_validate_json(
        lesson(challenges=[challenge(kind="find_bug"), challenge(), challenge()])
    )
    with pytest.raises(DraftRejected) as rejected:
        validate_draft(find_bug, request)
    assert rejected.value.code == "unrequested_style"
    with pytest.raises(DraftRejected):
        validate_draft(LessonDraft.model_validate_json(lesson(challenges=[challenge()])), request)
    assert Owner(uuid4()).account_id
