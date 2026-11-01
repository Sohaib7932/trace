"""Authored candidate definitions execute through unchanged trusted validation ports."""

from uuid import NAMESPACE_URL, uuid5

import pytest

from app.ai.providers.fake_question_generator import FakeQuestionGenerator
from app.blueprints.candidates import notes_blueprint_candidate, tasks_blueprint_candidate
from app.domain.lesson_spec.canonical import canonical_bytes, finalize_definition
from app.schemas.generation import GenerationRequest
from app.schemas.generation_admission import AdmissionAccepted
from app.schemas.lesson_composition import CompositionIdentity
from app.services.candidate_validation import CandidateValidationService
from app.services.challenge_content_admission import ChallengeContentAdmission
from app.services.lesson_composition import compose_lesson_spec
from app.verification.candidate_runtime import IsolatedCandidateRuntime


def composition_case(factory):
    proposal = factory()
    blueprint = proposal.trusted_blueprint()
    definition = proposal.definition
    prediction = definition.checkpoints[0]
    request = GenerationRequest.model_validate(
        {
            "contract_version": "1.0.0",
            "template_family": proposal.template_family,
            "permitted_narrative_variants": ["review-baseline"],
            "requested_objective_slots": [objective.id for objective in definition.objectives],
            "requested_misconception_slots": [item.id for item in definition.misconceptions],
            "approved_prediction_wording": {
                choice.id: [{"key": "approved-label", "label": choice.label}]
                for choice in prediction.choices
            },
            "allowed_instructional_facts": [
                "request-receiver-contract",
                "validation-before-persistence",
                "independent-readback",
            ]
            + (["nested-receiver-shape"] if proposal.template_family == "tasks-nested-v1" else []),
        }
    )
    completion = FakeQuestionGenerator().generate(request)
    admitted = ChallengeContentAdmission().admit(request, completion)
    assert isinstance(admitted, AdmissionAccepted)
    identity = CompositionIdentity(
        lesson_id=definition.lesson_id,
        version="2.0.0",
        version_id=str(uuid5(NAMESPACE_URL, f"test:composed-blueprint:{definition.lesson_id}")),
    )
    target = (
        tasks_blueprint_candidate().trusted_blueprint()
        if proposal.template_family == "notes-v1"
        else None
    )
    candidate = compose_lesson_spec(
        request, admitted, blueprint, identity, trusted_transfer_target=target
    )
    return proposal, blueprint, request, admitted, identity, target, candidate


@pytest.mark.parametrize("factory", [notes_blueprint_candidate, tasks_blueprint_candidate])
def test_actual_candidate_runtime_checks_both_profiles_and_all_independent_evidence(factory):
    proposal = factory()
    result = IsolatedCandidateRuntime().validate(proposal.definition)
    assert result.status == "passed"
    assert result.performed and result.completed
    assert tuple(profile.profile for profile in result.profiles) == ("baseline", "repair")
    for profile in result.profiles:
        assert profile.evaluation_matched
        assert {check.code for check in profile.checks} == {
            "http_status",
            "api_response",
            "validation",
            "row_count",
            "stored_values",
        }
        assert all(check.passed for check in profile.checks)
    assert proposal.review_status == "pending"
    assert proposal.production_approved is proposal.release_eligible is False


@pytest.mark.parametrize("factory", [notes_blueprint_candidate, tasks_blueprint_candidate])
def test_unchanged_admission_composition_and_gate_accept_technical_candidate_without_approval(
    factory,
):
    proposal, blueprint, request, admitted, identity, target, candidate = composition_case(factory)
    result = CandidateValidationService(IsolatedCandidateRuntime()).validate(
        candidate, request, admitted, blueprint, identity, trusted_transfer_target=target
    )
    assert result.status == "validated"
    assert all(stage.status == "passed" for stage in result.stages)
    assert result.runtime_verification_performed and result.runtime_verification_completed
    assert (
        result.release_eligible is candidate.release_eligible is proposal.release_eligible is False
    )
    assert proposal.review_status == "pending" and not proposal.production_approved
    assert candidate.definition.private == blueprint.definition.private
    assert candidate.metadata.blueprint == blueprint.reference()


def test_notes_gate_requires_complete_exact_transfer_candidate_even_if_source_is_digest_valid():
    _, blueprint, request, admitted, identity, _, candidate = composition_case(
        notes_blueprint_candidate
    )
    result = CandidateValidationService(IsolatedCandidateRuntime()).validate(
        candidate, request, admitted, blueprint, identity
    )
    assert result.status == "unavailable" and result.code == "transfer_target_unavailable"
    assert not result.runtime_verification_performed and not result.release_eligible


@pytest.mark.parametrize("factory", [notes_blueprint_candidate, tasks_blueprint_candidate])
def test_gate_rejects_private_configuration_changes_even_with_fresh_valid_digest(factory):
    _, blueprint, request, admitted, identity, target, candidate = composition_case(factory)
    payload = candidate.definition.model_dump(mode="json")
    payload["private"]["verification"]["timeout_seconds"] = 9
    changed = finalize_definition(payload)
    tampered = candidate.model_copy(
        update={
            "definition": changed,
            "canonical_digest": changed.content_sha256,
            "canonical_definition_bytes": canonical_bytes(changed),
        }
    )
    result = CandidateValidationService(IsolatedCandidateRuntime()).validate(
        tampered, request, admitted, blueprint, identity, trusted_transfer_target=target
    )
    assert result.status == "invalid" and result.code == "trusted_configuration_changed"
    assert not result.runtime_verification_performed and not result.release_eligible
