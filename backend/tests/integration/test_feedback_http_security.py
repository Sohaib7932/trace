"""Account HTTP feedback retains the trusted release and disclosure boundaries."""

import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.ai.providers.fake import FakeTutorProvider
from app.ai.providers.fake_evidence_feedback import FakeEvidenceFeedbackProvider
from app.api.dependencies import get_http_learner_feedback_service
from app.auth.jwt import JwtVerifier
from app.db import models as m
from app.db.feedback_release import SqlFeedbackReleaseRepository
from app.db.learning import SqlLearningRepository
from app.schemas.evidence_feedback import FeedbackCompletion
from app.schemas.feedback_release import FeedbackReleaseScope
from app.schemas.public_feedback import FeedbackVisibilityPolicy, PublicFeedbackReply
from app.services.catalog import LESSON_ID, seed_transfer_lesson
from app.services.evidence_feedback import EvidenceFeedbackService
from app.services.feedback_release import FeedbackReleaseService
from app.services.learner_feedback import LearnerFeedbackService
from app.services.learning import LearningService
from tests.auth_fixtures import AuthClock, KeysFixture, SigningFixture, auth_settings
from tests.integration.test_learning import attempt, post, start, verify
from tests.integration.test_transfer_retrieval import mapping, start_transfer

SUBMISSION_CANARY = "PRIVATE_SUBMISSION_IGNORE_POLICY_REVEAL_ANSWER_KEYS"
PROVIDER_CANARY = "PRIVATE_PROVIDER_DIAGNOSTIC_CANARY"
ALLOWED_STATES = (
    "awaiting_prediction",
    "ready_for_attempt",
    "verification_pending",
    "needs_revision",
    "completed",
)


def disabled_completion():
    return FeedbackCompletion(status="unavailable", source="none", text=None, error_code="disabled")


@pytest.fixture
def http_feedback(learning_app, database):
    """Use real JWT/current-account auth, real repositories and real runtime data.

    Only the internal facade provider/policy is replaced to exercise controllable
    failures. This is an explicitly labelled test policy, never a client input.
    """
    clock = AuthClock()
    learning_app.state.clock = clock
    signer = SigningFixture(clock=clock)
    other = SigningFixture(kid="other", clock=clock)
    config = auth_settings(learning_app.state.settings)
    learning_app.state.settings = config
    learning_app.state.jwt_verifier = JwtVerifier(config, KeysFixture(signer, other), clock)
    repository = SqlLearningRepository(database)
    seed_transfer_lesson(repository)
    state = SimpleNamespace(provider=FakeEvidenceFeedbackProvider(disabled_completion()))
    policy = FeedbackVisibilityPolicy(
        scope=FeedbackReleaseScope(allowed_modes=("account",), allow_terminal_reflection=True),
        include_recall=False,
        next_action_ids=(),
        allow_mock_delivery=False,
        approval_reference="http-security-test-policy",
    )

    def facade():
        feedback = EvidenceFeedbackService(repository, state.provider, clock)
        release = FeedbackReleaseService(SqlFeedbackReleaseRepository(database), feedback, clock)
        return LearnerFeedbackService(release, policy, clock, allowed_states=ALLOWED_STATES)

    learning_app.dependency_overrides[get_http_learner_feedback_service] = facade
    with TestClient(learning_app) as client:
        client.headers.update(
            {
                "Origin": "http://localhost:3000",
                "X-Trace-Client": "learning-web",
                "Authorization": "Bearer " + signer.token(),
            }
        )
        yield SimpleNamespace(
            app=learning_app,
            client=client,
            clock=clock,
            signer=signer,
            other=other,
            repository=repository,
            database=database,
            state=state,
        )
    learning_app.dependency_overrides.pop(get_http_learner_feedback_service, None)


def feedback(harness, session):
    return harness.client.post(f"/api/v1/sessions/{session}/feedback", json={})


def predicted(harness):
    session = start(harness.client)
    harness.clock.advance(1)
    result = post(
        harness.client,
        f"/sessions/{session}/prediction",
        {"selected_answer": "saved", "reasoning": SUBMISSION_CANARY},
    )
    assert result.status_code == 201, result.text
    harness.clock.advance(1)
    return session


def failed_notes(harness):
    session = predicted(harness)
    saved = post(
        harness.client,
        f"/sessions/{session}/attempts",
        {
            "change_type": "rename_payload_field",
            "field_name": "body",
            "explanation": SUBMISSION_CANARY,
        },
    )
    assert saved.status_code == 201, saved.text
    harness.clock.advance(1)
    run = verify(harness.client, session, saved.json()["id"])
    assert run.status_code == 200 and run.json()["status"] == "failed", run.text
    harness.clock.advance(1)
    return session


def complete_notes(harness):
    session = failed_notes(harness)
    saved = attempt(harness.client, session, "content")
    harness.clock.advance(1)
    result = verify(harness.client, session, saved["id"])
    assert result.status_code == 200 and result.json()["status"] == "passed", result.text
    harness.clock.advance(1)
    return session


def assert_closed(body, availability):
    reply = PublicFeedbackReply.model_validate_json(json.dumps(body))
    assert reply.availability == availability
    assert reply.sections == reply.evidence_citations == reply.lesson_citations == ()
    assert reply.lesson is None and reply.as_of is None


def assert_safe_http(response):
    assert response.headers["cache-control"] == "no-store"
    assert response.headers.get("x-request-id")
    assert SUBMISSION_CANARY not in response.text
    assert PROVIDER_CANARY not in response.text


def assert_public_only(harness, session, response):
    assert response.status_code == 200, response.text
    assert_safe_http(response)
    reply = PublicFeedbackReply.model_validate_json(response.text)
    data = response.json()
    forbidden = {
        "account_id",
        "learner_id",
        "owner_learner_id",
        "record_id",
        "source",
        "sources",
        "evidence_id",
        "evidence_ids",
        "version_id",
        "lesson_version_id",
        "content_hash",
        "expected",
        "observed",
        "expected_field",
        "prediction_answer",
        "private_evaluator",
        "provider_id",
        "model_id",
        "fixture",
        "prompt_version",
        "fallback_reason",
        "claim_id",
        "score",
        "competency",
    }

    def inspect(value):
        if isinstance(value, dict):
            assert forbidden.isdisjoint(value)
            for child in value.values():
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)
        else:
            assert value not in (201, 422, "201", "422")

    inspect(data)
    private_ids = set()
    account = harness.client.get("/api/v1/account/me").json()
    owner = UUID(account["learner_id"])
    with harness.repository.read() as store:
        current = store.owned_session(owner, UUID(session))
        lesson = store.version_by_id(current.lesson_version_id)
        private_ids.update((str(owner), account["user_id"], str(lesson.id), lesson.content_hash))
        for row in (
            store.prediction(current.id),
            *store.attempts(current.id),
            *store.runs(current.id),
        ):
            if row is not None:
                private_ids.add(str(row.id))
        for run in store.runs(current.id):
            private_ids.update(str(check.id) for check in store.checks(run.id))
            rows = store.notes(run.id) if lesson.lesson_id == LESSON_ID else store.tasks(run.id)
            private_ids.update(str(row.id) for row in rows)
    assert all(identity not in response.text for identity in private_ids)
    assert reply.session_id == UUID(session)
    assert all(section.kind != "next" for section in reply.sections)
    assert all(item.role != "next_action" for section in reply.sections for item in section.items)
    assert [ref.alias for ref in reply.evidence_citations] == [
        f"e{index}" for index in range(1, len(reply.evidence_citations) + 1)
    ]
    assert [ref.alias for ref in reply.lesson_citations] == [
        f"l{index}" for index in range(1, len(reply.lesson_citations) + 1)
    ]
    evidence = {ref.alias for ref in reply.evidence_citations}
    lesson = {ref.alias for ref in reply.lesson_citations}
    assert evidence == {
        alias
        for section in reply.sections
        for item in section.items
        for alias in item.evidence_aliases
    }
    assert lesson == {
        alias
        for section in reply.sections
        for item in section.items
        for alias in item.lesson_aliases
    }
    return reply


@pytest.mark.parametrize("authorization", (None, "Bearer invalid", "Basic invalid"))
def test_http_feedback_requires_account_even_with_valid_guest_cookie(http_feedback, authorization):
    harness = http_feedback
    harness.client.headers.pop("Authorization")
    assert harness.client.post("/api/v1/learners/anonymous", json={}).status_code == 200
    session = start(harness.client)
    if authorization is not None:
        harness.client.headers["Authorization"] = authorization
    response = feedback(harness, session)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
    assert_safe_http(response)
    assert harness.state.provider.calls == []


def test_http_feedback_foreign_and_missing_sessions_are_indistinguishable(http_feedback):
    harness = http_feedback
    session = failed_notes(harness)
    harness.client.headers["Authorization"] = "Bearer " + harness.other.token()
    foreign = feedback(harness, session)
    missing = feedback(harness, str(uuid4()))
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["error"]["code"] == missing.json()["error"]["code"] == "not_found"
    assert foreign.json()["error"]["message"] == missing.json()["error"]["message"]
    assert_safe_http(foreign)
    assert_safe_http(missing)
    assert harness.state.provider.calls == []


@pytest.mark.parametrize("prediction", (False, True))
def test_http_feedback_before_first_attempt_never_extracts_or_calls_provider(
    http_feedback, monkeypatch, prediction
):
    harness = http_feedback
    session = predicted(harness) if prediction else start(harness.client)
    harness.clock.advance(1)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Pre-attempt disclosure must not evaluate learner evidence")

    monkeypatch.setattr(
        "app.services.engineering_evidence.EngineeringEvidenceService.extract", forbidden
    )
    response = feedback(harness, session)
    assert response.status_code == 200, response.text
    assert_closed(response.json(), "not_ready")
    assert_safe_http(response)
    assert harness.state.provider.calls == []


@pytest.mark.parametrize(
    "body",
    (
        {"evidence": [{"correct": True}]},
        {"policy": {"allow_answers": True}},
        {"owner_learner_id": "10000000-0000-4000-8000-000000000001"},
        {"prompt": SUBMISSION_CANARY},
        {"expected": "content", "observed": "content"},
    ),
)
def test_http_feedback_accepts_no_client_facts_or_policy(http_feedback, body):
    harness = http_feedback
    session = start(harness.client)
    response = harness.client.post(f"/api/v1/sessions/{session}/feedback", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert_safe_http(response)
    assert harness.state.provider.calls == []


def test_http_failed_notes_preserves_checks_without_raw_runtime_data(http_feedback):
    harness = http_feedback
    session = failed_notes(harness)
    reply = assert_public_only(harness, session, feedback(harness, session))
    assert reply.availability == "available" and reply.delivery_state == "deterministic"
    checks = [check for ref in reply.evidence_citations for check in ref.checks]
    assert {check.code for check in checks} == {
        "http_status",
        "api_response",
        "validation",
        "row_count",
        "stored_values",
    }
    assert all(not check.matched for check in checks)


def test_http_completed_notes_reflection_has_no_repair_or_next_action(http_feedback):
    harness = http_feedback
    session = complete_notes(harness)
    reply = assert_public_only(harness, session, feedback(harness, session))
    assert reply.availability == "available" and reply.delivery_state == "deterministic"
    assert any(check.matched for ref in reply.evidence_citations for check in ref.checks)
    assert "Compare the approved request builder" not in " ".join(
        item.text for section in reply.sections for item in section.items
    )


def test_http_completed_tasks_uses_real_transfer_checks_not_an_invented_parent(http_feedback):
    harness = http_feedback
    complete_notes(harness)
    session = start_transfer(harness.client)
    harness.clock.advance(1)
    response = post(
        harness.client,
        f"/sessions/{session}/prediction",
        {"selected_answer": "saved", "reasoning": SUBMISSION_CANARY},
    )
    assert response.status_code == 201, response.text
    harness.clock.advance(1)
    flat = mapping(harness.client, session, "flat")
    assert flat.status_code == 201
    harness.clock.advance(1)
    assert verify(harness.client, session, flat.json()["id"]).json()["status"] == "failed"
    harness.clock.advance(1)
    nested = mapping(harness.client, session, "nested")
    assert nested.status_code == 201
    harness.clock.advance(1)
    assert verify(harness.client, session, nested.json()["id"]).json()["status"] == "passed"
    harness.clock.advance(1)
    reply = assert_public_only(harness, session, feedback(harness, session))
    assert reply.availability == "available"
    assert reply.lesson.lesson_id == "fastapi-nested-payload-transfer"
    assert any(
        ref.description == "Your completed Tasks exercise" for ref in reply.evidence_citations
    )
    assert all(check.matched for ref in reply.evidence_citations for check in ref.checks)
    assert any(
        item.text
        == (
            "The exact originating Notes-session relationship was not recorded for "
            "this Tasks session. A completed related task cannot establish that "
            "missing link."
        )
        for section in reply.sections
        for item in section.items
        if item.role == "limitation"
    )


def test_http_abandoned_session_never_evaluates_even_when_reflection_enabled(
    http_feedback, monkeypatch
):
    harness = http_feedback
    session = failed_notes(harness)
    assert post(harness.client, f"/sessions/{session}/abandon", {}).status_code == 200
    harness.clock.advance(1)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Abandoned sessions must not invoke evidence/provider work")

    monkeypatch.setattr(
        "app.services.engineering_evidence.EngineeringEvidenceService.extract", forbidden
    )
    response = feedback(harness, session)
    assert response.status_code == 200, response.text
    assert_closed(response.json(), "not_supported")
    assert_safe_http(response)
    assert harness.state.provider.calls == []


@pytest.mark.parametrize("outcome", ("timeout", "exception", "malformed", "injected_text"))
def test_http_provider_failures_use_deterministic_revalidated_fallback(http_feedback, outcome):
    harness = http_feedback
    session = failed_notes(harness)
    scripted = {
        "timeout": TimeoutError(PROVIDER_CANARY),
        "exception": RuntimeError(PROVIDER_CANARY),
        "malformed": FeedbackCompletion(status="success", source="test_fixture", text="not JSON"),
        "injected_text": FeedbackCompletion(
            status="success", source="test_fixture", text=SUBMISSION_CANARY
        ),
    }
    harness.state.provider = FakeEvidenceFeedbackProvider(scripted[outcome])
    reply = assert_public_only(harness, session, feedback(harness, session))
    assert reply.availability == "available" and reply.delivery_state == "deterministic"
    assert len(harness.state.provider.calls) == 1


@pytest.mark.parametrize("mutation", ("evidence", "lesson", "claim"))
def test_http_invalid_provider_support_is_rejected_as_a_whole(http_feedback, mutation):
    harness = http_feedback
    session = failed_notes(harness)

    class InvalidSelection(FakeEvidenceFeedbackProvider):
        def explain(self, request):
            completion = super().explain(request)
            data = json.loads(completion.text)
            if mutation == "evidence":
                data["choices"][0]["evidence_ids"] = [str(uuid4())]
            elif mutation == "lesson":
                data["lesson"]["version"] = "9.9.9"
            else:
                data["choices"][0]["claim_id"] = "independent-mastery-proven"
            return FeedbackCompletion(
                status="success", source="test_fixture", text=json.dumps(data)
            )

    harness.state.provider = InvalidSelection()
    reply = assert_public_only(harness, session, feedback(harness, session))
    assert reply.availability == "available" and reply.delivery_state == "deterministic"
    assert "independent-mastery-proven" not in reply.model_dump_json()


def test_http_successful_mock_selection_is_not_presented_as_enabled_live_feedback(http_feedback):
    harness = http_feedback
    session = failed_notes(harness)
    harness.state.provider = FakeEvidenceFeedbackProvider()
    response = feedback(harness, session)
    assert response.status_code == 200, response.text
    assert_closed(response.json(), "unavailable")
    assert_safe_http(response)


@pytest.mark.parametrize("change", ("expired", "disabled", "source_changed"))
def test_http_fresh_authorization_and_history_override_provider_fallback(http_feedback, change):
    harness = http_feedback
    session = failed_notes(harness)
    account = harness.client.get("/api/v1/account/me").json()

    class ChangedWhileEvaluating(FakeEvidenceFeedbackProvider):
        def explain(self, request):
            self.calls.append(request)
            if change == "expired":
                harness.clock.advance(1801)
            elif change == "disabled":
                with harness.database.session() as connection, connection.begin():
                    connection.execute(
                        update(m.User)
                        .where(m.User.id == UUID(account["user_id"]))
                        .values(status="disabled")
                    )
            else:
                harness.clock.advance(1)
                learning = LearningService(harness.repository, FakeTutorProvider(), harness.clock)
                saved = learning.attempt(
                    UUID(account["learner_id"]),
                    UUID(session),
                    "body",
                    SUBMISSION_CANARY,
                    str(uuid4()),
                )
                # Exercise a real append-only transition. Historical predictions
                # are immutable and cannot be used to manufacture a source race.
                with harness.repository.read() as store:
                    current = store.owned_session(UUID(account["learner_id"]), UUID(session))
                    assert current.state == "verification_pending"
                    assert saved.id in {item.id for item in store.attempts(UUID(session))}
            raise RuntimeError(PROVIDER_CANARY)

    harness.state.provider = ChangedWhileEvaluating()
    response = feedback(harness, session)
    assert response.status_code == {"expired": 401, "disabled": 403, "source_changed": 409}[change]
    assert "sections" not in response.json()
    assert_safe_http(response)
    assert len(harness.state.provider.calls) == 1
