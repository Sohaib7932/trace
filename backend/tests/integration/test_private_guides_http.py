"""Real authenticated HTTP/app-lifecycle wiring with a controlled shared transport."""

import json
from uuid import uuid4

import pytest

from app.ai.client import AITransportError
from app.auth.jwt import JwtVerifier
from tests.auth_fixtures import KeysFixture, SigningFixture
from tests.integration.test_live_ai_http import api as api  # noqa: F401
from tests.integration.test_private_guides import content

PATH = "/api/v1/learning-guides"
BODY = {
    "topic": "Python variables",
    "start_level": "beginner",
    "target_level": "intermediate",
    "practical": True,
}


def create(api, body=None, key=None):
    return api.client.post(
        PATH, json=BODY if body is None else body, headers={"Idempotency-Key": key or str(uuid4())}
    )


def test_owned_create_list_read_and_exact_replay_through_real_application_wiring(api):
    api.provider.text = json.dumps(content())
    key = str(uuid4())
    response = create(api, key=key)
    assert response.status_code == 201, response.text
    assert response.headers["Cache-Control"] == "no-store"
    saved = response.json()
    # This fixture simulates the genuine-mode adapter contract (source="ai").
    # It is a controlled local transport, never evidence of an external call.
    assert saved["source"] == api.provider.source and saved["status"] == "ready"
    assert saved["ungraded"] is True and saved["execution_status"] == "not_executed"
    assert api.client.get(PATH + "/" + saved["id"]).json() == saved
    listed = api.client.get(PATH)
    assert listed.status_code == 200 and listed.headers["Cache-Control"] == "no-store"
    assert [item["id"] for item in listed.json()] == [saved["id"]]
    assert create(api, key=key).json() == saved
    assert len(api.provider.calls) == 1 and api.provider.calls[0].capability == "generation"
    assert api.provider.calls[0].response_timeout_seconds <= 10


def test_account_auth_required_and_foreign_missing_guide_ids_are_indistinguishable(api):
    api.provider.text = json.dumps(content())
    saved = create(api).json()
    authorization = api.client.headers.pop("Authorization")
    assert create(api).status_code == 401
    assert api.client.get(PATH).status_code == 401
    api.client.headers["Authorization"] = authorization
    other = SigningFixture(clock=api.clock)
    api.app.state.jwt_verifier = JwtVerifier(api.app.state.settings, KeysFixture(other))
    api.client.headers["Authorization"] = "Bearer " + other.token()
    assert api.client.get(PATH).json() == []
    for identity in (saved["id"], str(uuid4())):
        response = api.client.get(PATH + "/" + identity)
        assert response.status_code == 404
        assert "content" not in response.json()


@pytest.mark.parametrize(
    "body",
    [
        {**BODY, "owner_id": str(uuid4())},
        {**BODY, "topic": "GEMINI_API_KEY=private-canary-value"},
        {**BODY, "start_level": "expert"},
    ],
)
def test_invalid_private_request_never_reaches_provider_and_errors_do_not_echo_input(api, body):
    response = create(api, body)
    assert response.status_code == 422
    assert "private-canary-value" not in response.text
    assert not api.provider.calls


def test_cross_origin_write_and_missing_idempotency_key_are_rejected(api):
    response = api.client.post(PATH, json=BODY)
    assert response.status_code == 422
    api.client.headers["Origin"] = "https://foreign.example"
    assert create(api).status_code == 403
    assert not api.provider.calls


@pytest.mark.parametrize("failure", ["timeout", "invalid"])
def test_provider_timeout_or_invalid_output_is_honest_persisted_unavailable(api, failure):
    if failure == "timeout":
        api.provider.error = AITransportError("timeout")
    else:
        api.provider.text = '{"private_evaluator":"private-canary-value"}'
    response = create(api)
    assert response.status_code == 201
    assert response.json()["status"] == "unavailable"
    assert response.json()["content"] is None and response.json()["source"] is None
    assert "private-canary-value" not in response.text


def test_generation_rate_limit_is_enforced_on_the_server(api):
    api.provider.text = json.dumps(content())
    maximum = api.app.state.guide_operations.settings.requests_per_minute
    for _ in range(maximum):
        assert create(api).status_code == 201
    limited = create(api)
    assert limited.status_code == 429
    assert len(api.provider.calls) == maximum
    assert limited.headers["Cache-Control"] == "no-store"
