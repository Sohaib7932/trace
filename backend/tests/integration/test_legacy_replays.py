"""Exercise retries across pending, revision and terminal learner states."""

from uuid import uuid4

import pytest

from tests.integration.test_learning import post, progress, verify


@pytest.mark.parametrize("terminal", ["completed", "abandoned"])
def test_saved_responses_replay_without_reopening_terminal_history(learner, terminal):
    key = str(uuid4())
    created = post(learner, "/sessions", {"lesson_id": "fastapi-payload-mismatch"}, key)
    assert created.status_code == 201
    session = created.json()["id"]
    path = f"/sessions/{session}"
    prediction_body = {"selected_answer": "saved", "reasoning": "  My original prediction.  "}
    prediction = post(learner, path + "/prediction", prediction_body, key)
    assert prediction.status_code == 201
    assert progress(learner, session)["session"]["state"] == "ready_for_attempt"
    bad_body = {
        "change_type": "rename_payload_field",
        "field_name": "body",
        "explanation": "  First.  ",
    }
    bad = post(learner, path + "/attempts", bad_body, key)
    assert bad.status_code == 201
    failed = verify(learner, session, bad.json()["id"], key)
    assert failed.status_code == 200 and failed.json()["status"] == "failed"
    assert progress(learner, session)["summary"]["prediction_correct"] is False
    hint_body = {"attempt_id": bad.json()["id"]}
    hint = post(learner, path + "/hints", hint_body, key)
    assert hint.status_code == 201
    good_key = str(uuid4())
    good_body = {
        "change_type": "rename_payload_field",
        "field_name": "content",
        "explanation": "Repair.",
    }
    good = post(learner, path + "/attempts", good_body, good_key)
    assert good.status_code == 201 and good.json()["hints_before"] == 1
    # A final earlier result also replays while a newer candidate is pending.
    assert verify(learner, session, bad.json()["id"], key).json() == failed.json()
    assert verify(learner, session, bad.json()["id"]).json() == failed.json()
    if terminal == "completed":
        passed = verify(learner, session, good.json()["id"], key)
        assert passed.status_code == 200 and passed.json()["status"] == "passed"
    else:
        assert post(learner, path + "/abandon", {}).status_code == 200
    saved = progress(learner, session)
    assert saved["session"]["state"] == terminal
    assert saved["prediction"]["reasoning"] == prediction_body["reasoning"]
    assert post(learner, path + "/prediction", prediction_body, key).json() == prediction.json()
    assert post(learner, path + "/attempts", bad_body, key).json() == bad.json()
    assert post(learner, path + "/attempts", good_body, good_key).json() == good.json()
    assert post(learner, path + "/hints", hint_body, key).json() == hint.json()
    assert verify(learner, session, bad.json()["id"], key).json() == failed.json()
    replay = post(learner, "/sessions", {"lesson_id": "fastapi-payload-mismatch"}, key)
    assert replay.status_code == 201 and replay.json() == saved["session"]
    for suffix, body in [
        ("/prediction", prediction_body),
        ("/attempts", bad_body),
        ("/hints", hint_body),
    ]:
        assert post(learner, path + suffix, body).status_code == 409
    assert (
        post(
            learner, path + "/prediction", {**prediction_body, "reasoning": "Changed"}, key
        ).status_code
        == 409
    )
    assert (
        post(learner, path + "/attempts", {**bad_body, "explanation": "Changed"}, key).status_code
        == 409
    )
    assert post(learner, path + "/hints", {"attempt_id": good.json()["id"]}, key).status_code == 409
    assert post(learner, path + "/abandon", {}).status_code == (
        409 if terminal == "completed" else 200
    )
    if terminal == "completed":
        assert verify(learner, session, good.json()["id"], key).json() == passed.json()
        assert verify(learner, session, good.json()["id"]).json() == passed.json()
    else:
        assert verify(learner, session, good.json()["id"], key).status_code == 409
    assert progress(learner, session) == saved


@pytest.mark.parametrize(
    "stage", ["awaiting_prediction", "ready_for_attempt", "verification_pending", "needs_revision"]
)
def test_abandonment_is_terminal_at_every_nonterminal_stage(learner, stage):
    from tests.integration.test_learning import attempt, predict, start

    session = start(learner)
    if stage != "awaiting_prediction":
        assert predict(learner, session).status_code == 201
    if stage in {"verification_pending", "needs_revision"}:
        candidate = attempt(learner, session)
        if stage == "needs_revision":
            assert verify(learner, session, candidate["id"]).json()["status"] == "failed"
    before = progress(learner, session)
    assert before["session"]["state"] == stage
    assert post(learner, f"/sessions/{session}/abandon", {}).json()["state"] == "abandoned"
    saved = progress(learner, session)
    assert saved["session"]["completed_at"] is None
    for field in ["lesson", "prediction", "attempts", "hints", "verifications"]:
        assert saved[field] == before[field]
    assert post(learner, f"/sessions/{session}/abandon", {}).json() == saved["session"]
    assert progress(learner, session) == saved
