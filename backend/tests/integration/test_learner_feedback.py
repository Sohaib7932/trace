"""Public feedback reflects owned real runtime facts without internal provenance."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.ai.providers.fake import FakeTutorProvider
from app.ai.providers.fake_evidence_feedback import FakeEvidenceFeedbackProvider
from app.api.dependencies import (
    get_ai_resources,
    get_evidence_feedback_service,
    get_feedback_release_service,
    get_learner_feedback_service,
)
from app.domain.learning import NOTE_CONTENT, NOTE_TITLE, LearningError
from app.domain.transfer import TASK_TITLE, TRANSFER_ID
from app.main import create_app
from app.schemas.feedback_release import FeedbackReleaseScope
from app.schemas.public_feedback import FeedbackVisibilityPolicy, PublicFeedbackReply
from app.schemas.tutoring import TutorMessage
from app.services.catalog import LESSON_ID, seed_transfer_lesson
from app.services.learner_feedback import LearnerFeedbackService
from app.services.learning import LearningService
from app.services.verification import VerificationService
from app.verification.asgi_tasks import AsgiTasksVerifier
from tests.integration.test_feedback_release_races import (
    OUTCOMES,
    BlockingFeedback,
    create_context,
    mutate_authorization,
    release_service,
)

CHECKS = {"http_status", "api_response", "validation", "row_count", "stored_values"}
HINT_CANARY = "CONTROLLED_PRIVATE_DELIVERED_HINT_TEXT"


def proposed_policy(*, terminal=True, modes=("account", "guest"), next_actions=()):
    # This is explicitly proposed test configuration, not a registered production policy.
    return FeedbackVisibilityPolicy(
        scope=FeedbackReleaseScope(allowed_modes=modes, allow_terminal_reflection=terminal),
        include_recall=False,
        next_action_ids=next_actions,
        allow_mock_delivery=True,
        approval_reference="proposed-integration-test-policy",
    )


def facade(context, provider=None, policy=None):
    provider = provider or FakeEvidenceFeedbackProvider()
    return (
        LearnerFeedbackService(release_service(context, provider), policy, context.clock),
        provider,
    )


def sections(reply):
    return {section.kind: section.items for section in reply.sections}


def text(reply):
    return " ".join(item.text for section in reply.sections for item in section.items)


def leaves(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from leaves(child)
    elif isinstance(value, list):
        for child in value:
            yield from leaves(child)
    else:
        yield value


def assert_public_privacy(context, provider, reply, *extra_canaries):
    encoded = reply.model_dump_json()
    canaries = {
        str(context.owner),
        NOTE_TITLE,
        NOTE_CONTENT,
        TASK_TITLE,
        HINT_CANARY,
        "Controlled prediction.",
        "Controlled attempt.",
        "CONTROLLED_PRIVATE_PROVIDER_EXCEPTION",
        *extra_canaries,
    }
    if context.principal.account is not None:
        canaries.add(str(context.principal.account.id))
    if context.principal.credential is not None:
        canaries.add(str(context.principal.credential.id))
    with context.repository.read() as store:
        current = store.owned_session(context.owner, context.session.id)
        lesson = store.version_by_id(current.lesson_version_id)
        canaries.update((str(lesson.id), lesson.content_hash))
        for record in (
            store.prediction(current.id),
            *store.attempts(current.id),
            *store.runs(current.id),
            *store.hints(current.id),
            *store.hint_operations(current.id),
        ):
            if record is not None:
                canaries.add(str(record.id))
        for run in store.runs(current.id):
            canaries.update(str(check.id) for check in store.checks(run.id))
            rows = store.notes(run.id) if lesson.lesson_id == LESSON_ID else store.tasks(run.id)
            canaries.update(str(row.id) for row in rows)
    requests = getattr(provider, "requests", None)
    if requests is None:
        requests = provider.calls
    for request in requests:
        for value in leaves(request.model_dump(mode="json")):
            if isinstance(value, str):
                with suppress(ValueError):
                    canaries.add(str(UUID(value)))
    # The authorized public session identity is intentionally retained.
    canaries.discard(str(context.session.id))
    assert all(canary not in encoded for canary in canaries)
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
        "requested_model_id",
        "returned_model_id",
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

    inspect(reply.model_dump(mode="json"))
    for reason in ("provider_timeout", "provider_exception", "invalid_output", "source_invalid"):
        assert reason not in encoded
    assert PublicFeedbackReply.model_validate_json(encoded) == reply


def assert_local_citations(reply):
    assert [item.alias for item in reply.evidence_citations] == [
        f"e{index}" for index in range(1, len(reply.evidence_citations) + 1)
    ]
    assert [item.alias for item in reply.lesson_citations] == [
        f"l{index}" for index in range(1, len(reply.lesson_citations) + 1)
    ]
    for section in reply.sections:
        for statement in section.items:
            assert set(statement.evidence_aliases) <= {
                item.alias for item in reply.evidence_citations
            }
            assert set(statement.lesson_aliases) <= {item.alias for item in reply.lesson_citations}
    for reference in reply.evidence_citations:
        assert {check.code for check in reference.checks} <= CHECKS
        assert all(type(check.matched) is bool for check in reference.checks)


@pytest.mark.parametrize("mode", ("guest", "account"))
def test_audience_is_disabled_by_default_without_evaluation(database, monkeypatch, mode):
    context = create_context(database, mode=mode)

    def forbidden(*_):
        raise AssertionError("Disabled policy must not calculate feedback correctness")

    monkeypatch.setattr(
        "app.services.engineering_evidence.EngineeringEvidenceService.extract", forbidden
    )
    service, provider = facade(context)
    reply = service.feedback(context.principal, context.session.id)
    assert reply.availability == "not_supported"
    assert reply.feedback_state is None and reply.delivery_state == "unavailable"
    assert not reply.sections and not reply.evidence_citations and not reply.lesson_citations
    assert provider.calls == []


def test_no_prediction_and_both_prediction_answers_are_identically_not_ready(database, monkeypatch):
    context = create_context(database, phase="prediction")
    wrong = context.session
    correct = context.learning.create_session(context.owner, LESSON_ID, "1.0.0", str(uuid4()))
    context.clock.advance()
    context.learning.predict(
        context.owner, correct.id, "rejected", "Controlled correct prediction.", str(uuid4())
    )
    context.clock.advance()
    empty = context.learning.create_session(context.owner, LESSON_ID, "1.0.0", str(uuid4()))
    context.clock.advance()

    def forbidden(*_):
        raise AssertionError("Pre-attempt public feedback must not calculate correctness")

    monkeypatch.setattr(
        "app.services.engineering_evidence.EngineeringEvidenceService.extract", forbidden
    )
    service, provider = facade(context, policy=proposed_policy())
    replies = [
        service.feedback(context.principal, session.id) for session in (empty, correct, wrong)
    ]
    assert provider.calls == []
    normalized = [reply.model_dump(exclude={"session_id"}) for reply in replies]
    assert normalized[0] == normalized[1] == normalized[2]
    for reply in replies:
        assert reply.availability == "not_ready" and reply.feedback_state is None
        assert (
            reply.delivery_state == "unavailable" and reply.lesson is None and reply.as_of is None
        )
        assert reply.sections == reply.evidence_citations == reply.lesson_citations == ()


@pytest.mark.parametrize("pending", (False, True))
def test_submitted_and_pending_attempts_are_partial_without_invented_execution(database, pending):
    context = create_context(database, phase="submitted")
    if pending:
        run, _, _ = context.verification._reserve(
            context.owner, context.session.id, context.submitted.id, str(uuid4())
        )
        assert run.status == "pending"
        context.clock.advance()
    service, provider = facade(context, policy=proposed_policy())
    reply = service.feedback(context.principal, context.session.id)
    assert reply.availability == "available" and reply.feedback_state == "partially_supported"
    assert "submitted" in text(reply).lower() and "unproven" in text(reply).lower()
    assert not any(reference.checks for reference in reply.evidence_citations)
    assert "next" not in sections(reply)
    assert_local_citations(reply)
    assert_public_privacy(context, provider, reply)


def test_failed_notes_then_real_correction_disclose_only_actual_checks(database):
    context = create_context(database, mode="account")
    service, provider = facade(context, policy=proposed_policy())
    failed = service.feedback(context.principal, context.session.id)
    assert failed.availability == "available" and failed.feedback_state == "supported"
    assert "needs_improvement" in sections(failed)
    checks = next(
        reference.checks
        for reference in failed.evidence_citations
        if reference.description == "Your runtime verification"
    )
    assert {check.code for check in checks} == CHECKS and not all(check.matched for check in checks)
    assert_public_privacy(context, provider, failed)
    context.clock.advance()
    correction = context.learning.attempt(
        context.owner, context.session.id, "content", "PRIVATE_CORRECTION_EXPLANATION", str(uuid4())
    )
    context.clock.advance()
    assert (
        context.verification.verify(
            context.owner, context.session.id, correction.id, str(uuid4())
        ).status
        == "passed"
    )
    context.clock.advance()
    passed = service.feedback(context.principal, context.session.id)
    assert passed.availability == "available" and passed.feedback_state == "supported"
    assert "next" not in sections(passed)
    assert "chronology" in text(passed) and "diagnosis" in text(passed)
    checks = next(
        reference.checks
        for reference in passed.evidence_citations
        if reference.description == "Your runtime verification"
    )
    assert {check.code for check in checks} == CHECKS and all(check.matched for check in checks)
    assert_local_citations(passed)
    assert_public_privacy(context, provider, passed, "PRIVATE_CORRECTION_EXPLANATION")


def task_context(database):
    context = create_context(database)
    notes_id = context.session.id
    context.clock.advance()
    repaired = context.learning.attempt(context.owner, notes_id, "content", "", str(uuid4()))
    context.clock.advance()
    assert (
        context.verification.verify(context.owner, notes_id, repaired.id, str(uuid4())).status
        == "passed"
    )
    seed_transfer_lesson(context.repository)
    context.clock.advance()
    context.session = context.learning.create_session(
        context.owner, TRANSFER_ID, "1.0.0", str(uuid4())
    )
    context.clock.advance()
    context.learning.predict(
        context.owner, context.session.id, "saved", "PRIVATE_TASK_PREDICTION", str(uuid4())
    )
    context.clock.advance()
    context.submitted = context.learning.attempt(
        context.owner, context.session.id, "flat", "PRIVATE_FLAT_EXPLANATION", str(uuid4())
    )
    context.verification = VerificationService(
        context.repository,
        context.verification.verifier,
        5,
        tasks_verifier=AsgiTasksVerifier(context.repository, 5),
        clock=context.clock,
    )
    context.clock.advance()
    assert (
        context.verification.verify(
            context.owner, context.session.id, context.submitted.id, str(uuid4())
        ).status
        == "failed"
    )
    context.clock.advance()
    context.original_notes_id = notes_id
    return context


def test_tasks_flat_failure_nested_success_and_transfer_have_no_parent_identifier(database):
    context = task_context(database)
    service, provider = facade(context, policy=proposed_policy())
    failed = service.feedback(context.principal, context.session.id)
    assert failed.feedback_state == "supported" and "needs_improvement" in sections(failed)
    assert failed.lesson.lesson_id == TRANSFER_ID and failed.lesson.version == "1.0.0"
    assert_public_privacy(
        context,
        provider,
        failed,
        str(context.original_notes_id),
        "PRIVATE_TASK_PREDICTION",
        "PRIVATE_FLAT_EXPLANATION",
    )
    context.clock.advance()
    nested = context.learning.attempt(
        context.owner, context.session.id, "nested", "PRIVATE_NESTED_EXPLANATION", str(uuid4())
    )
    context.clock.advance()
    assert (
        context.verification.verify(
            context.owner, context.session.id, nested.id, str(uuid4())
        ).status
        == "passed"
    )
    context.clock.advance()
    completed = service.feedback(context.principal, context.session.id)
    assert completed.feedback_state == "supported" and "next" not in sections(completed)
    assert any(
        reference.description == "Your completed Tasks exercise"
        for reference in completed.evidence_citations
    )
    assert "not recorded" in text(completed)
    assert_public_privacy(
        context,
        provider,
        completed,
        str(context.original_notes_id),
        "PRIVATE_NESTED_EXPLANATION",
        "PRIVATE_TASK_PREDICTION",
        "PRIVATE_FLAT_EXPLANATION",
    )
    assert_local_citations(completed)


def test_infrastructure_error_stays_unavailable_execution_not_learner_failure(database):
    context = create_context(database, phase="submitted")

    class UnavailableRuntime:
        def observe(self, *_):
            raise RuntimeError("CONTROLLED_PRIVATE_RUNTIME_DETAILS")

    verification = VerificationService(
        context.repository, UnavailableRuntime(), 5, clock=context.clock
    )
    context.clock.advance()
    assert (
        verification.verify(
            context.owner, context.session.id, context.submitted.id, str(uuid4())
        ).status
        == "error"
    )
    context.clock.advance()
    service, provider = facade(context, policy=proposed_policy())
    reply = service.feedback(context.principal, context.session.id)
    assert reply.availability == "available" and reply.feedback_state == "partially_supported"
    assert "does not establish a learner mistake" in text(reply)
    assert not any(reference.checks for reference in reply.evidence_citations)
    assert_public_privacy(context, provider, reply, "CONTROLLED_PRIVATE_RUNTIME_DETAILS")


@pytest.mark.parametrize("outcome", OUTCOMES)
def test_provider_failures_use_safe_delivery_without_private_diagnostics(database, outcome):
    context = create_context(database)
    provider = BlockingFeedback(outcome)
    provider.release.set()
    service, _ = facade(context, provider, proposed_policy())
    reply = service.feedback(context.principal, context.session.id)
    assert reply.availability == "available" and reply.feedback_state == "supported"
    assert reply.delivery_state == ("mock" if outcome == "mock" else "deterministic")
    assert_public_privacy(context, provider, reply)


def test_private_provider_metadata_and_payload_are_rejected_whole(database):
    context = create_context(database)
    canaries = (
        "PRIVATE_PROVIDER_ID",
        "PRIVATE_MODEL_ID",
        "PRIVATE_EVALUATOR_CONFIGURATION",
        "PRIVATE_OBSERVED_HTTP_PAYLOAD",
        "PRIVATE_EXPECTED_RUNTIME_VALUE",
    )

    class ExposingProvider(FakeEvidenceFeedbackProvider):
        def explain(self, request):
            valid = super().explain(request)
            payload = json.loads(valid.text)
            payload.update(
                zip(
                    ("provider_id", "model_id", "evaluator", "observed", "expected"),
                    canaries,
                    strict=True,
                )
            )
            return valid.model_copy(update={"text": json.dumps(payload)})

    provider = ExposingProvider()
    service, _ = facade(context, provider, proposed_policy())
    reply = service.feedback(context.principal, context.session.id)
    assert reply.delivery_state == "deterministic" and reply.feedback_state == "supported"
    assert_public_privacy(context, provider, reply, *canaries)


@pytest.mark.parametrize("timing", ("before", "after", "equal", "pending", "error"))
def test_assistance_provenance_does_not_disclose_guidance_or_infer_independence(database, timing):
    context = create_context(database, phase="prediction")

    class ControlledTutor(FakeTutorProvider):
        def generate_hint(self, _):
            if timing == "error":
                raise RuntimeError("CONTROLLED_PRIVATE_TUTOR_ERROR")
            return TutorMessage(text=HINT_CANARY, source="test_fixture")

    learning = LearningService(context.repository, ControlledTutor(), context.clock)
    if timing == "after":
        context.clock.advance()
        context.submitted = learning.attempt(
            context.owner, context.session.id, "body", "", str(uuid4())
        )
        context.clock.advance()
    if timing == "pending":
        learning._reserve_hint(context.owner, context.session.id, None, str(uuid4()), None)
    else:
        delivered = learning.hint(context.owner, context.session.id, None, str(uuid4()))
        assert delivered.status == ("error" if timing == "error" else "delivered")
    if timing != "after":
        if timing != "equal":
            context.clock.advance()
        context.submitted = learning.attempt(
            context.owner, context.session.id, "body", "", str(uuid4())
        )
    context.clock.advance()
    service, provider = facade(context, policy=proposed_policy())
    reply = service.feedback(context.principal, context.session.id)
    request = provider.calls[0]
    action = next(
        item
        for item in request.evidence.observations
        if item.event_type == "modification_submitted"
        and item.source.record_id == context.submitted.id
    )
    claim = next(item for item in request.claims if item.claim_id == "assistance-context")
    approved_wordings = {wording.text for wording in claim.wordings}
    retained = [item for item in sections(reply)["why"] if item.text in approved_wordings]
    assert len(retained) == 1 and claim.evidence_ids == (action.id,)
    citation = next(
        reference
        for reference in reply.evidence_citations
        if reference.description == "Your submitted attempt"
        and reference.occurred_at == action.occurred_at
    )
    assert retained[0].evidence_aliases == (citation.alias,)
    if timing == "before":
        assert action.assistance.category == "tutor_assisted"
        assert action.assistance.delivered_before
        assert claim.role == "fact" and retained[0].role == "observation"
    else:
        assert action.assistance.category == "unknown"
        assert action.assistance.delivered_before == ()
        assert claim.role == retained[0].role == "limitation"
        assert "delivered before" not in text(reply)
        assert "guidance preceded the selected action" not in text(reply)
    assert "You worked independently" not in text(reply)
    assert_public_privacy(context, provider, reply, "CONTROLLED_PRIVATE_TUTOR_ERROR")


@pytest.mark.parametrize("terminal", ("abandoned", "completed"))
def test_terminal_feedback_never_offers_new_action_even_with_explicit_next_allowlist(
    database, terminal
):
    context = create_context(database)
    if terminal == "abandoned":
        context.learning.abandon(context.owner, context.session.id)
    else:
        context.clock.advance()
        correction = context.learning.attempt(
            context.owner, context.session.id, "content", "", str(uuid4())
        )
        context.clock.advance()
        assert (
            context.verification.verify(
                context.owner, context.session.id, correction.id, str(uuid4())
            ).status
            == "passed"
        )
    context.clock.advance()
    service, _ = facade(
        context, policy=proposed_policy(next_actions=("compare-receiving-contract",))
    )
    reply = service.feedback(context.principal, context.session.id)
    assert reply.availability == "available" and "next" not in sections(reply)
    assert all(item.role != "next_action" for section in reply.sections for item in section.items)
    assert "Compare the approved request builder" not in text(reply)


def test_public_only_lesson_digest_and_field_citations_match_exact_public_bytes(database):
    context = create_context(database)
    service, _ = facade(context, policy=proposed_policy())
    reply = service.feedback(context.principal, context.session.id)
    with context.repository.read() as store:
        session = store.owned_session(context.owner, context.session.id)
        public = store.version_by_id(session.lesson_version_id).public_content
    expected = hashlib.sha256(
        json.dumps(
            public, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()
    assert reply.lesson.public_content_sha256 == expected
    for reference in reply.lesson_citations:
        assert reference.lesson == reply.lesson
        assert (
            reference.sha256 == hashlib.sha256(public[reference.field].encode("utf-8")).hexdigest()
        )


def test_unavailable_source_has_no_evaluated_sections_or_private_error(database, monkeypatch):
    context = create_context(database)

    def unavailable(*_):
        raise LearningError("dependency_unavailable", "CONTROLLED_PRIVATE_SOURCE_ERROR")

    monkeypatch.setattr(
        "app.services.engineering_evidence.EngineeringEvidenceService.extract", unavailable
    )
    service, provider = facade(context, policy=proposed_policy())
    reply = service.feedback(context.principal, context.session.id)
    assert reply.availability == reply.feedback_state == reply.delivery_state == "unavailable"
    assert reply.sections == reply.evidence_citations == reply.lesson_citations == ()
    assert reply.lesson is None and reply.as_of is None and provider.calls == []
    assert "CONTROLLED_PRIVATE_SOURCE_ERROR" not in reply.model_dump_json()


@pytest.mark.parametrize("mutation", ("revoked", "new_attempt"))
def test_facade_never_projects_unauthorized_or_stale_evaluation(database, monkeypatch, mutation):
    context = create_context(database)
    provider = BlockingFeedback()
    service, _ = facade(context, provider, proposed_policy())
    projected = []

    def forbidden(*_):
        projected.append(True)
        raise AssertionError("Unauthorized or stale results must not reach public projection")

    monkeypatch.setattr("app.services.learner_feedback.project_public_feedback", forbidden)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.feedback, context.principal, context.session.id)
        try:
            assert provider.entered.wait(5)
            context.clock.advance()
            if mutation == "revoked":
                mutate_authorization(context, "revoked")
            else:
                context.learning.attempt(
                    context.owner, context.session.id, "body", "", str(uuid4())
                )
        finally:
            provider.release.set()
        with pytest.raises(LearningError) as error:
            future.result(timeout=5)
    assert error.value.code == ("unauthenticated" if mutation == "revoked" else "feedback_changed")
    assert projected == []


def test_known_authorization_deadline_is_checked_after_projection(database, monkeypatch):
    import app.services.learner_feedback as module

    context = create_context(database)
    service, provider = facade(context, policy=proposed_policy())
    original = module.project_public_feedback

    def delayed(*args, **kwargs):
        reply = original(*args, **kwargs)
        context.clock.now = context.principal.expires_at
        return reply

    monkeypatch.setattr(module, "project_public_feedback", delayed)
    with pytest.raises(LearningError) as error:
        service.feedback(context.principal, context.session.id)
    assert error.value.code == "unauthenticated" and len(provider.calls) == 1


@pytest.mark.parametrize("foreign", (False, True))
def test_foreign_and_unknown_sessions_have_identical_sanitized_behavior(database, foreign):
    context = create_context(database)
    session_id = create_context(database).session.id if foreign else uuid4()
    service, provider = facade(context, policy=proposed_policy())
    with pytest.raises(LearningError) as error:
        service.feedback(context.principal, session_id)
    assert error.value.code == "not_found" and str(error.value) == "Session not found."
    assert provider.calls == []


def test_internal_application_wiring_reuses_resources_and_remains_disabled(settings, database):
    context = create_context(database)
    app = create_app(settings, database, clock=context.clock)
    expected = json.loads((Path(__file__).resolve().parents[2] / "openapi.json").read_text())
    with TestClient(app):
        request = Request({"type": "http", "app": app, "headers": []})
        resources = get_ai_resources(request)
        feedback = get_evidence_feedback_service(request, context.repository, resources)
        release = get_feedback_release_service(request, database, feedback)
        service = get_learner_feedback_service(request, release)
        assert feedback.provider is resources.evidence_feedback_provider
        assert resources.evidence_feedback_provider.client is resources.client
        assert service.policy == FeedbackVisibilityPolicy.disabled()
        reply = service.feedback(context.principal, context.session.id)
        assert reply.availability == "not_supported"
        assert resources.client.transport is None and resources.client.usage_snapshot() == ()
        assert app.openapi() == expected
        assert len(expected["paths"]) == 22
        assert (
            sum(
                method in {"get", "post", "put", "patch", "delete", "head", "options"}
                for path in expected["paths"].values()
                for method in path
            )
            == 24
        )
    assert resources.client.closed
