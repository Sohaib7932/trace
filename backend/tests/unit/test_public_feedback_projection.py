"""Public facts, whole-claim disclosure, local citations and privacy canaries."""

from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest

from app.domain.retrieval import QUESTIONS, RetrievalAttempt, RetrievalCheckpoint, due_at
from app.schemas.evidence_feedback import FeedbackCompletion
from app.schemas.public_feedback import (
    NOTICE_DETERMINISTIC,
    NOTICE_MOCK,
    NOTICE_UNAVAILABLE,
    FeedbackVisibilityPolicy,
    PublicFeedbackReply,
)
from app.services.catalog import TRANSFER_CONTENT
from app.services.public_feedback_projection import (
    _visible,
    project_public_feedback,
    public_content_sha256,
    public_grounding_state,
    validate_public_projection,
)
from app.services.verification import VerificationService
from tests.unit.test_engineering_evidence_sources import add_help, at
from tests.unit.test_evidence_feedback_policy import build, passing_notes, tasks
from tests.unit.test_feedback_release import evaluate, setup


def policy_for(result, *, next_actions=(), mock=True):
    return FeedbackVisibilityPolicy(
        scope=result.envelope.scope,
        include_recall=False,
        next_action_ids=next_actions,
        allow_mock_delivery=mock,
        approval_reference="proposed-projection-test-policy",
    )


def projected(context=None, **options):
    result = evaluate(setup() if context is None else context)
    policy = policy_for(result, **options)
    return result, policy, project_public_feedback(result, policy)


def test_owned_unapproved_lesson_version_is_not_a_public_definition_or_provider_request():
    context = setup()
    source, _, _, _, provider, _, _ = context
    source.lesson = replace(source.lesson, version="1.1.0")
    result = evaluate(context)
    reply = project_public_feedback(result, policy_for(result))
    assert result.envelope.availability == "not_supported"
    assert reply.availability == "not_supported" and reply.lesson is None
    assert reply.feedback_state is None and reply.sections == reply.evidence_citations == ()
    assert not provider.calls


def test_unknown_claim_kind_is_denied_even_with_otherwise_valid_evidence_support():
    result, policy, _ = projected()
    claim = next(
        item for item in result.envelope.plan.claims if item.claim_id == "mapping-submitted"
    )
    records = {item.id: item for item in result.envelope.evidence.observations}
    unknown = claim.model_copy(update={"claim_id": "private-runtime-diagnostics"})
    assert not _visible(unknown, policy, False, records)


def test_recognized_claim_cannot_substitute_a_real_auxiliary_recall_source():
    # Use the existing extractor over an actual pinned recall fixture. This
    # adversarial claim is tested at the pure filter boundary, never issued as
    # a release-authorized envelope or persisted as learner evidence.
    context = setup()
    source = context[0]
    tasks(source)
    question = QUESTIONS[0]
    due = due_at(at(8), 1)
    checkpoint = RetrievalCheckpoint(
        UUID("00000000-0000-4000-8000-000000000101"),
        source.session.id,
        1,
        question.id,
        question.content_hash,
        due,
        at(8),
    )
    selection = next(value for value in ("a", "b", "c") if value != question.answer)
    answer = RetrievalAttempt(
        UUID("00000000-0000-4000-8000-000000000102"),
        checkpoint.id,
        1,
        selection,
        "Controlled recall reasoning.",
        False,
        "Review the contract. " + question.explanation,
        "controlled-recall-key",
        due + timedelta(seconds=1),
    )
    source.saved_checkpoints, source.saved_answers = [checkpoint], {checkpoint.id: [answer]}
    plan = build(
        source,
        TRANSFER_CONTENT,
        start_at=due,
        end_at=due + timedelta(seconds=5),
        as_of=due + timedelta(seconds=5),
    )
    assert plan.evidence.observations == ()
    recall = plan.evidence.retrieval_events[0]
    claim = next(item for item in plan.claims if item.claim_id == "retrieval-record-only")
    substituted = claim.model_copy(update={"claim_id": "mapping-submitted"})
    _, policy, _ = projected()
    assert not _visible(substituted, policy, False, {recall.id: recall})


def statements(reply):
    return [item for section in reply.sections for item in section.items]


def scalars(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from scalars(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from scalars(item)
    else:
        yield value


def test_exact_regeneration_keeps_facts_and_response_local_aliases_without_internal_keys():
    result, policy, reply = projected(next_actions=("compare-receiving-contract",))
    assert reply.availability == "available" and reply.feedback_state == "supported"
    assert reply.delivery_state == "mock" and reply.notice == NOTICE_MOCK
    assert reply.lesson.public_content_sha256 == public_content_sha256(
        result.envelope.public_content
    )
    assert [ref.alias for ref in reply.evidence_citations] == ["e1", "e2", "e3"]
    assert [ref.description for ref in reply.evidence_citations] == [
        "Your original prediction",
        "Your submitted attempt",
        "Your runtime verification",
    ]
    assert all(item.evidence_aliases for item in statements(reply) if item.role == "observation")
    assert validate_public_projection(result, policy, reply) == reply
    assert project_public_feedback(result, policy) == reply
    serialized = reply.model_dump_json()
    assert "claim_id" not in serialized and "record_id" not in serialized
    assert "version_id" not in serialized and "coverage_references" not in serialized


def test_unapproved_next_action_and_its_imperative_why_claim_are_removed_whole():
    result, _, reply = projected()
    assert all(section.kind != "next" for section in reply.sections)
    assert not any("compare" in item.text.lower() for item in statements(reply))
    # These code citations supported only the removed why/next claims. Scenario
    # remains genuinely used by the original-prediction observation.
    assert [ref.field for ref in reply.lesson_citations] == ["scenario"]
    assert result.envelope.plan.claims[-1].claim_id == "compare-receiving-contract"
    assert "receiving-contract" in {claim.claim_id for claim in result.envelope.plan.claims}


def test_explicit_generic_next_permission_retains_only_the_existing_approved_step():
    result, _, reply = projected(next_actions=("compare-receiving-contract",))
    next_section = next(section for section in reply.sections if section.kind == "next")
    assert len(next_section.items) == 1 and next_section.items[0].role == "next_action"
    original = next(
        claim
        for claim in result.envelope.plan.claims
        if claim.claim_id == "compare-receiving-contract"
    )
    assert next_section.items[0].text in {wording.text for wording in original.wordings}
    assert set(next_section.items[0].lesson_aliases) <= {
        ref.alias for ref in reply.lesson_citations
    }


@pytest.mark.parametrize("family", ["notes", "tasks"])
def test_terminal_reflection_never_offers_next_or_imperative_why_guidance(family):
    context = setup()
    if family == "notes":
        passing_notes(context[0], retain_failure=True)
    else:
        tasks(context[0])
    _, _, reply = projected(context, next_actions=("compare-receiving-contract",))
    assert reply.availability == "available" and reply.feedback_state == "supported"
    assert not any(section.kind == "next" for section in reply.sections)
    assert not any("compare" in item.text.lower() for item in statements(reply))
    if family == "tasks":
        assert any("Tasks" in item.text for item in statements(reply))
        assert any("not recorded" in item.text for item in statements(reply))


@pytest.mark.parametrize("selection", [None, "saved", "rejected"])
def test_preattempt_public_result_is_identical_for_absent_correct_and_wrong_prediction(selection):
    context = setup()
    source = context[0]
    source.saved_attempts, source.saved_runs, source.saved_checks = [], [], []
    source.saved_prediction = (
        None if selection is None else replace(source.saved_prediction, selected_answer=selection)
    )
    _, _, reply = projected(context)
    assert reply.availability == "not_ready" and reply.feedback_state is None
    assert reply.sections == reply.evidence_citations == reply.lesson_citations == ()
    assert reply.lesson is reply.as_of is None and not context[4].calls
    baseline = setup()
    baseline[0].saved_prediction = None
    baseline[0].saved_attempts, baseline[0].saved_runs, baseline[0].saved_checks = [], [], []
    assert reply == projected(baseline)[2]


def test_disabled_policy_has_no_evaluated_output_and_cannot_activate_an_audience():
    context = list(setup())
    policy = FeedbackVisibilityPolicy.disabled()
    context[6] = policy.scope
    result = evaluate(context)
    reply = project_public_feedback(result, policy)
    assert reply.availability == "not_supported" and reply.feedback_state is None
    assert reply.lesson is reply.as_of is None and reply.sections == ()
    assert not context[4].calls


@pytest.mark.parametrize("source_error", [False, True])
def test_disallowed_mock_or_unavailable_sources_have_only_coarse_safe_notices(source_error):
    context = setup()
    if source_error:
        context[0].lesson = replace(context[0].lesson, content_hash="0" * 64)
    _, _, reply = projected(context, mock=False)
    assert reply.availability == reply.feedback_state == reply.delivery_state == "unavailable"
    assert reply.notice == NOTICE_UNAVAILABLE
    assert reply.sections == reply.evidence_citations == reply.lesson_citations == ()
    assert reply.lesson is reply.as_of is None


@pytest.mark.parametrize(
    "outcome",
    [
        TimeoutError("PRIVATE_PROVIDER_ERROR_CANARY"),
        RuntimeError("PRIVATE_PROVIDER_ERROR_CANARY"),
        FeedbackCompletion(status="success", source="test_fixture", text="{"),
        FeedbackCompletion(status="unavailable", source="none", text=None, error_code="disabled"),
    ],
)
def test_deterministic_fallback_never_exposes_provider_diagnostics(outcome):
    result, _, reply = projected(setup(outcome), mock=False)
    assert result.reply.fallback_reason is not None
    assert reply.availability == "available" and reply.delivery_state == "deterministic"
    assert reply.notice == NOTICE_DETERMINISTIC
    serialized = reply.model_dump_json()
    assert "PRIVATE_PROVIDER_ERROR_CANARY" not in serialized
    assert "fallback_reason" not in serialized and "provider_exception" not in serialized
    assert "provider_timeout" not in serialized and "invalid_output" not in serialized


@pytest.mark.parametrize("pending", [False, True])
def test_submitted_unexecuted_or_pending_attempt_is_partial_without_a_failed_grade(pending):
    context = setup()
    source = context[0]
    source.saved_checks = []
    source.saved_runs = (
        [replace(source.saved_runs[0], status="pending", completed_at=None)] if pending else []
    )
    _, _, reply = projected(context)
    assert reply.feedback_state == "partially_supported"
    assert not any(ref.checks for ref in reply.evidence_citations)
    assert not any("failed" in item.text.lower() for item in statements(reply))


def test_infrastructure_execution_is_unavailable_evidence_not_a_failed_learner_grade():
    context = setup()
    source = context[0]
    source.saved_runs[0] = replace(source.saved_runs[0], status="error")
    source.saved_checks = []
    VerificationService._checks(source, source.saved_runs[0].id, "body", "content", None, at(5))
    _, _, reply = projected(context)
    assert reply.feedback_state == "partially_supported"
    assert any("unavailable" in item.text.lower() for item in statements(reply))
    assert not any("failed" in item.text.lower() for item in statements(reply))
    runtime = next(
        ref for ref in reply.evidence_citations if ref.description == "Your runtime verification"
    )
    assert runtime.checks == ()
    assert "dependency_or_execution_failure" not in reply.model_dump_json()


@pytest.mark.parametrize("status", ["delivered", "pending", "error", "late", "equal", "external"])
def test_assistance_is_only_actual_strictly_prior_delivery_with_private_support_hidden(status):
    context = setup()
    source = context[0]
    if status == "external":
        source.saved_attempts[0] = replace(
            source.saved_attempts[0], explanation="PRIVATE_EXTERNAL_HELP_CLAIM"
        )
    else:
        add_help(source, "delivered" if status in {"late", "equal"} else status)
        if status in {"late", "equal"}:
            when = at(4) if status == "late" else at(3)
            source.saved_operations[0] = replace(source.saved_operations[0], completed_at=when)
            source.saved_hints[0] = replace(source.saved_hints[0], created_at=when)
        if source.saved_hints and source.saved_hints[0].status == "delivered":
            source.saved_hints[0] = replace(source.saved_hints[0], text="PRIVATE_HINT_TEXT_CANARY")
    result, policy, reply = projected(context)
    assistance = next(item for item in statements(reply) if "selected action" in item.text.lower())
    assert (assistance.role == "observation") == (status == "delivered")
    if status != "delivered":
        assert "unknown" in assistance.text and "independent work" in assistance.text
    serialized = reply.model_dump_json()
    assert (
        "PRIVATE_HINT_TEXT_CANARY" not in serialized
        and "PRIVATE_EXTERNAL_HELP_CLAIM" not in serialized
    )
    assert not any(
        ref.description in {"Your hint request", "Your tutor guidance record"}
        for ref in reply.evidence_citations
    )
    for item in result.envelope.evidence.hint_events:
        assert str(item.id) not in serialized and str(item.source.record_id) not in serialized
    assert validate_public_projection(result, policy, reply) == reply


@pytest.mark.parametrize("has_fact", [False, True])
@pytest.mark.parametrize(
    "state", ["supported", "partially_supported", "insufficient_evidence", "unavailable"]
)
def test_grounding_mapping_never_upgrades_or_turns_auxiliary_data_into_competence(state, has_fact):
    expected = (
        state
        if state in {"unavailable", "insufficient_evidence"} or has_fact
        else "insufficient_evidence"
    )
    assert public_grounding_state(state, has_fact) == expected


@pytest.mark.parametrize(("state", "has_fact"), [("unknown", True), ("supported", 1)])
def test_grounding_helper_rejects_unknown_states_and_coercible_support_flags(state, has_fact):
    with pytest.raises(ValueError):
        public_grounding_state(state, has_fact)


@pytest.mark.parametrize("family", ["notes", "tasks"])
def test_dependent_claims_and_orphaned_support_are_removed_if_the_parent_is_not_visible(
    monkeypatch, family
):
    from app.services import public_feedback_projection as projection

    context = setup()
    if family == "notes":
        passing_notes(context[0], retain_failure=True)
    else:
        tasks(context[0])
    original = projection._visible

    def deny_parent(claim, *args):
        return claim.claim_id != "verification-passed" and original(claim, *args)

    # Inject a denied parent visibility decision over actual trusted source
    # history. This tests dependency safety without inventing learner actions.
    monkeypatch.setattr(projection, "_visible", deny_parent)
    result, _, reply = projected(context)
    removed = {"verification-passed", "observed-recovery", "tasks-transfer-result"}
    prohibited = {
        wording.text
        for claim in result.envelope.plan.claims
        if claim.claim_id in removed
        for wording in claim.wordings
    }
    assert not any(item.text in prohibited for item in statements(reply))
    assert not any(
        ref.description
        in {
            "Your runtime verification",
            "Your recorded recovery sequence",
            "Your completed Tasks exercise",
        }
        for ref in reply.evidence_citations
    )


def test_projection_preserves_only_approved_verification_categories_and_real_match_flags():
    result, _, reply = projected()
    expected = next(
        item
        for item in result.envelope.evidence.observations
        if item.event_type == "verification_finished"
    )
    observed = next(
        ref for ref in reply.evidence_citations if ref.description == "Your runtime verification"
    )
    assert {item.code: item.matched for item in observed.checks} == {
        item.code: item.matched for item in expected.checks
    }
    assert {item.code for item in observed.checks} == {
        "http_status",
        "api_response",
        "validation",
        "row_count",
        "stored_values",
    }
    for item in observed.checks:
        assert set(item.model_dump()) == {"code", "matched"}


def test_all_private_source_ids_hashes_and_canary_text_remain_outside_serialized_public_data():
    context = setup()
    source = context[0]
    source.saved_prediction = replace(
        source.saved_prediction, reasoning="PRIVATE_PREDICTION_REASONING_CANARY"
    )
    source.saved_attempts[0] = replace(
        source.saved_attempts[0], explanation="PRIVATE_ATTEMPT_EXPLANATION_CANARY"
    )
    add_help(source, "delivered")
    source.saved_hints[0] = replace(
        source.saved_hints[0],
        text="PRIVATE_HINT_TEXT_CANARY",
        provider="PRIVATE_PROVIDER_ID_CANARY",
        fixture="PRIVATE_FIXTURE_CANARY",
        prompt_version="PRIVATE_PROMPT_VERSION_CANARY",
    )
    result, _, reply = projected(context)
    serialized = reply.model_dump_json()
    forbidden_ids = {
        result.envelope.authorization.account_id,
        result.envelope.authorization.learner_id,
        result.envelope.request_id,
        result.envelope.lesson.version_id,
        source.saved_prediction.id,
        *[item.id for item in source.saved_attempts],
        *[item.id for item in source.saved_runs],
        *[item.id for item in source.saved_checks],
        *[item.id for item in source.saved_operations],
        *[item.id for item in source.saved_hints],
        *[item.id for item in result.envelope.evidence.observations],
        *[item.id for item in result.envelope.evidence.hint_events],
    }
    assert all(
        str(identity) not in serialized for identity in forbidden_ids if identity is not None
    )
    assert result.envelope.lesson.content_hash not in serialized
    assert result.envelope.authorization.identity_fingerprint not in serialized
    assert "PRIVATE_" not in serialized
    data = tuple(scalars(reply.model_dump(mode="json")))
    assert all(value not in (201, 422, "201", "422") for value in data)
    assert all(
        check.expected not in data and check.observed not in data for check in source.saved_checks
    )
    for field in (
        "expected",
        "observed",
        "record_id",
        "provider_id",
        "version_id",
        "fallback_reason",
        "expected_field",
        "prediction_answer",
    ):
        assert f'"{field}"' not in serialized


def test_authorized_session_uuid_containing_status_digits_is_valid_public_identity():
    context = setup()
    source = context[0]
    session_id = UUID("00000422-0000-4000-8000-000000000001")
    source.session = replace(source.session, id=session_id)
    source.saved_prediction = replace(source.saved_prediction, session_id=session_id)
    source.saved_attempts = [replace(item, session_id=session_id) for item in source.saved_attempts]
    source.saved_runs = [replace(item, session_id=session_id) for item in source.saved_runs]
    _, _, reply = projected(context)
    assert reply.session_id == session_id and str(session_id) in reply.model_dump_json()
    assert 422 not in tuple(scalars(reply.model_dump(mode="json")))


@pytest.mark.parametrize(
    "mutation",
    [
        "invalid_alias",
        "duplicate_alias",
        "dangling_alias",
        "missing_citation",
        "alias_substitution",
        "description",
        "check_outcome",
        "lesson_pin",
        "public_digest",
        "field_digest",
        "text",
        "private_field",
    ],
)
def test_structural_or_cross_source_public_substitutions_are_rejected(mutation):
    result, policy, reply = projected(next_actions=("compare-receiving-contract",))
    body = reply.model_dump(warnings=False)
    first = body["sections"][0]["items"][0]
    if mutation == "invalid_alias":
        first["evidence_aliases"] = ("e0",)
    elif mutation == "duplicate_alias":
        body["evidence_citations"][1]["alias"] = "e1"
    elif mutation == "dangling_alias":
        first["evidence_aliases"] = ("e64",)
    elif mutation == "missing_citation":
        body["evidence_citations"] = body["evidence_citations"][1:]
    elif mutation == "alias_substitution":
        for section in body["sections"]:
            for item in section["items"]:
                item["evidence_aliases"] = tuple(
                    {"e1": "e2", "e2": "e1"}.get(alias, alias) for alias in item["evidence_aliases"]
                )
    elif mutation == "description":
        body["evidence_citations"][0]["description"] = "Your submitted attempt"
    elif mutation == "check_outcome":
        checks = next(item["checks"] for item in body["evidence_citations"] if item["checks"])
        checks[0]["matched"] = not checks[0]["matched"]
    elif mutation == "lesson_pin":
        body["lesson"]["lesson_id"] = "fastapi-nested-payload-transfer"
        for ref in body["lesson_citations"]:
            ref["lesson"]["lesson_id"] = body["lesson"]["lesson_id"]
    elif mutation == "public_digest":
        body["lesson"]["public_content_sha256"] = "0" * 64
        for ref in body["lesson_citations"]:
            ref["lesson"]["public_content_sha256"] = "0" * 64
    elif mutation == "field_digest":
        body["lesson_citations"][0]["sha256"] = "0" * 64
    elif mutation == "text":
        first["text"] = "Unsupported mastery conclusion."
    else:
        body["provider_id"] = "PRIVATE_PROVIDER_CANARY"
    with pytest.raises(ValueError):
        changed = PublicFeedbackReply.model_validate(body)
        validate_public_projection(result, policy, changed)


def test_an_available_partial_result_cannot_be_upgraded_by_public_state_manipulation():
    context = setup()
    context[0].saved_runs, context[0].saved_checks = [], []
    result, policy, reply = projected(context)
    body = reply.model_dump(warnings=False)
    body["feedback_state"] = "supported"
    with pytest.raises(ValueError):
        validate_public_projection(result, policy, PublicFeedbackReply.model_validate(body))


def test_altered_release_scope_or_internal_bindings_cannot_be_projected_as_authorized():
    result, policy, reply = projected()
    different = policy.model_copy(
        update={"scope": policy.scope.model_copy(update={"allowed_modes": ("account",)})}
    )
    with pytest.raises(ValueError):
        project_public_feedback(result, different)
    forged = result.model_copy(
        update={"envelope": result.envelope.model_copy(update={"source_fingerprint": "0" * 64})}
    )
    with pytest.raises(ValueError):
        project_public_feedback(forged, policy)
    with pytest.raises(ValueError):
        project_public_feedback(object(), policy)
    with pytest.raises(ValueError):
        validate_public_projection(result, policy, object())
    assert reply == project_public_feedback(result, policy)
