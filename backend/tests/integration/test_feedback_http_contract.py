"""The feedback HTTP contract accepts identity from auth, never learner assertions."""

from uuid import UUID, uuid4

import pytest

from app.auth.jwt import JwtVerifier
from app.schemas.public_feedback import PublicFeedbackReply
from tests.auth_fixtures import KeysFixture, SigningFixture, auth_settings
from tests.integration.test_learning import attempt, post, predict, start


@pytest.fixture
def account_feedback(learner, learning_app):
    signer = SigningFixture()
    config = auth_settings(learning_app.state.settings)
    learning_app.state.settings = config
    learning_app.state.jwt_verifier = JwtVerifier(config, KeysFixture(signer))
    learner.headers["Authorization"] = "Bearer " + signer.token()
    return learner, learning_app


def endpoint(session_id):
    return f"/api/v1/sessions/{session_id}/feedback"


def test_feedback_requires_bearer_even_with_valid_guest_cookie(learner):
    session = start(learner)
    response = learner.post(endpoint(session), json={})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
    assert response.headers["Cache-Control"] == "no-store"


def test_feedback_before_attempt_is_closed_without_provider_content(account_feedback):
    client, _ = account_feedback
    session = start(client)
    response = client.post(endpoint(session), json={})
    assert response.status_code == 200, response.text
    reply = PublicFeedbackReply.model_validate_json(response.text)
    assert reply.availability == "not_ready"
    assert reply.session_id == UUID(session)
    assert reply.feedback_state is None
    assert reply.lesson is None and reply.as_of is None
    assert not reply.sections and not reply.evidence_citations and not reply.lesson_citations
    assert response.headers["Cache-Control"] == "no-store"


def test_feedback_uses_public_schema_and_deterministic_delivery(account_feedback):
    client, _ = account_feedback
    session = start(client)
    assert predict(client, session).status_code == 201
    saved = attempt(client, session)
    response = client.post(endpoint(session), json={})
    assert response.status_code == 200, response.text
    reply = PublicFeedbackReply.model_validate_json(response.text)
    assert reply.availability == "available"
    assert reply.delivery_state == "deterministic"
    assert reply.schema_version == "evidence-feedback-public-v1"
    assert reply.policy_version == "evidence-feedback-visibility-v1"
    assert reply.session_id == UUID(session)
    assert str(saved["id"]) not in response.text
    assert all(section.kind != "next" for section in reply.sections)
    assert reply.notice == "This feedback uses deterministic evidence rules."
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "body",
    [
        {"learner_id": str(uuid4())},
        {"account_id": str(uuid4())},
        {"correct": True},
        {"evidence": []},
        {"selected_answer": "saved"},
        {"allow_terminal_reflection": True},
        {"allow_mock_delivery": True},
        {"provider": "live"},
        {"expected": "CONTROLLED_PRIVATE_CLIENT_INPUT"},
        {"observed": "CONTROLLED_PRIVATE_CLIENT_INPUT"},
        {"start_at": "2020-01-01T00:00:00Z"},
        {"session_id": str(uuid4())},
    ],
)
def test_feedback_rejects_client_assertions_and_configuration(account_feedback, body):
    client, _ = account_feedback
    session = start(client)
    response = client.post(endpoint(session), json=body)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    # The feedback ingress replaces validation internals with a closed error.
    # Client field names/values are not needed to explain this empty-body API.
    assert error["details"] == []
    assert error["message"] == "Feedback request validation failed."
    assert "CONTROLLED_PRIVATE_CLIENT_INPUT" not in response.text
    assert response.headers["Cache-Control"] == "no-store"


def test_feedback_requires_empty_object_body_and_uuid_path(account_feedback):
    client, _ = account_feedback
    session = start(client)
    for response in (
        client.post(endpoint(session)),
        client.post(endpoint(session), json=[]),
        client.post(endpoint("not-a-uuid"), json={}),
    ):
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"
        assert response.headers["Cache-Control"] == "no-store"


def test_feedback_requires_origin_and_trace_client_header(account_feedback):
    client, _ = account_feedback
    session = start(client)
    for headers in (
        {"Origin": "https://unapproved.example.test"},
        {"X-Trace-Client": "another-client"},
    ):
        response = client.post(endpoint(session), json={}, headers=headers)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden"
        assert response.json()["error"]["message"] == "Feedback access is denied."
        assert response.headers["Cache-Control"] == "no-store"


def test_feedback_recompute_does_not_require_or_create_idempotent_mutation(account_feedback):
    client, _ = account_feedback
    session = start(client)
    assert predict(client, session).status_code == 201
    attempt(client, session)
    before = client.get(f"/api/v1/sessions/{session}/progress").json()
    first = client.post(endpoint(session), json={})
    second = client.post(endpoint(session), json={})
    assert first.status_code == second.status_code == 200
    assert first.json()["availability"] == second.json()["availability"] == "available"
    after = client.get(f"/api/v1/sessions/{session}/progress").json()
    assert after == before


def test_feedback_openapi_exposes_only_empty_body_and_safe_reply(learning_app):
    schema = learning_app.openapi()
    operation = schema["paths"]["/api/v1/sessions/{session_id}/feedback"]["post"]
    assert operation["operationId"] == "get_session_feedback"
    assert operation["requestBody"]["required"] is True
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/Contract"
    }
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/PublicFeedbackReply"
    }
    assert operation["security"] == [{"HTTPBearer": []}]
    assert "Idempotency-Key" not in {item["name"] for item in operation["parameters"]}
    assert schema["components"]["schemas"]["Contract"]["additionalProperties"] is False


def test_existing_hint_route_remains_independent_of_feedback_delivery(account_feedback):
    client, _ = account_feedback
    session = start(client)
    assert predict(client, session).status_code == 201
    response = post(client, f"/sessions/{session}/hints", {})
    assert response.status_code == 201
    assert response.json()["provider"] == "fake"
    assert response.json()["status"] == "delivered"
    assert response.json()["interaction_type"] == "hint"


def test_public_feedback_does_not_activate_internal_mock_provider(account_feedback):
    client, app = account_feedback
    session = start(client)
    assert predict(client, session).status_code == 201
    attempt(client, session)

    class InternalProvider:
        calls = 0

        def explain(self, request):
            self.calls += 1
            raise AssertionError("CONTROLLED_INTERNAL_PROVIDER_MUST_NOT_RUN")

    internal = InternalProvider()
    app.state.ai_resources.evidence_feedback_provider = internal
    response = client.post(endpoint(session), json={})
    assert response.status_code == 200, response.text
    assert response.json()["availability"] == "available"
    assert response.json()["delivery_state"] == "deterministic"
    assert "CONTROLLED_INTERNAL_PROVIDER_MUST_NOT_RUN" not in response.text
    assert internal.calls == 0


def test_closed_feedback_resources_fail_safely(account_feedback):
    client, app = account_feedback
    session = start(client)
    app.state.feedback_operations.close()
    response = client.post(endpoint(session), json={})
    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "dependency_unavailable",
        "message": "Feedback is unavailable. Try again later.",
        "request_id": response.headers["X-Request-ID"],
        "details": [],
    }
    assert response.headers["Cache-Control"] == "no-store"
