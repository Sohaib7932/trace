"""Complete test-only blueprints, strict copy composition and preservation."""

import builtins
import json
import random
import socket
import time
import uuid
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.domain.lesson_spec import initial_learner_projection, validate_lesson_spec
from app.domain.lesson_spec.canonical import canonical_bytes, finalize_definition, verify_digest
from app.domain.lesson_spec.fields import TransferCheckpoint
from app.schemas.generation import GeneratedChallengeContent, GenerationRequest
from app.schemas.generation_admission import (
    AdmissionAccepted,
    AdmissionFailureCode,
    AdmissionRejected,
)
from app.schemas.lesson_composition import (
    ComposedLessonCandidate,
    TrustedLessonBlueprint,
)
from app.services.lesson_composition import compose_lesson_spec
from tests.composition_fixtures import (
    FAMILIES,
    admitted_case,
    blueprint,
    composition_identity,
    test_definition,
)


def compose(family="notes-v1", *, source=None, identity=None, with_target=False):
    request, accepted = admitted_case(family)
    trusted = blueprint(family) if source is None else source
    identity = composition_identity(family) if identity is None else identity
    target = blueprint("tasks-nested-v1") if with_target else None
    return compose_lesson_spec(request, accepted, trusted, identity, trusted_transfer_target=target)


def structural_view(definition):
    """Remove only the expressly writable leaves; everything else must match."""
    result = deepcopy(definition.model_dump(mode="json"))
    for field in ["lesson_id", "version_id", "version", "content_sha256", "title", "summary"]:
        del result[field]
    del result["scenario"]["context"]
    for objective in result["objectives"]:
        del objective["statement"]
    for checkpoint in result["checkpoints"][:3]:
        del checkpoint["prompt"]
        if checkpoint["type"] == "prediction":
            for choice in checkpoint["choices"]:
                del choice["label"]
    for hint in result["hints"]:
        del hint["text"]
    for explanation in result["explanations"]:
        if explanation["release_event"] == "core_verification_passed":
            del explanation["text"]
    for misconception in result["misconceptions"]:
        del misconception["statement"]
        del misconception["suggested_feedback"]
    return result


@pytest.mark.parametrize("family", FAMILIES)
def test_complete_test_only_blueprints_have_verified_server_owned_definitions(family):
    trusted = blueprint(family)
    assert trusted.template_family == family
    assert trusted.definition.lesson_id.startswith("test-blueprint-")
    assert trusted.definition.version == "0.1.0"
    assert verify_digest(trusted.definition)
    assert trusted.definition.private.runtime_binding.template_id == family


def test_wrong_family_digest_or_non_definition_cannot_be_a_trusted_blueprint():
    definition = test_definition()
    with pytest.raises(ValueError):
        TrustedLessonBlueprint(template_family="tasks-nested-v1", definition=definition)
    data = definition.model_dump(mode="json")
    data["content_sha256"] = "0" * 64
    wrong_digest = validate_lesson_spec(data)
    with pytest.raises(ValueError):
        TrustedLessonBlueprint(template_family="notes-v1", definition=wrong_digest)
    with pytest.raises(ValueError):
        TrustedLessonBlueprint(template_family="notes-v1", definition=data)
    _, accepted = admitted_case()
    with pytest.raises(ValueError):
        TrustedLessonBlueprint(template_family="notes-v1", definition=accepted)


@pytest.mark.parametrize("destination", ["objective", "misconception", "hints", "explanation"])
def test_incomplete_or_unregistered_composition_destinations_are_rejected(destination):
    data = test_definition().model_dump(mode="json")
    if destination == "objective":
        data["objectives"][0]["id"] = "unregistered-objective"
        for checkpoint in data["checkpoints"]:
            checkpoint["objective_ids"] = ["unregistered-objective"]
    elif destination == "misconception":
        data["misconceptions"][0]["id"] = "unregistered-misconception"
    elif destination == "hints":
        data["hints"] = data["hints"][:2]
        for checkpoint in data["checkpoints"]:
            checkpoint["hint_ids"] = [key for key in checkpoint["hint_ids"] if key != "hint-3"]
    else:
        data["explanations"] = [
            item
            for item in data["explanations"]
            if item["release_event"] != "core_verification_passed"
        ]
    definition = finalize_definition(data)
    with pytest.raises(ValueError):
        TrustedLessonBlueprint(template_family="notes-v1", definition=definition)


def test_multiple_core_explanation_destinations_are_ambiguous_and_rejected():
    data = test_definition().model_dump(mode="json")
    extra = deepcopy(data["explanations"][0])
    extra["id"] = "another-core-explanation"
    data["explanations"].append(extra)
    definition = finalize_definition(data)
    with pytest.raises(ValueError):
        TrustedLessonBlueprint(template_family="notes-v1", definition=definition)


@pytest.mark.parametrize("collection", ["objectives", "hints", "explanations", "misconceptions"])
def test_duplicate_destinations_fail_existing_strict_validation(collection):
    data = test_definition().model_dump(mode="json")
    data[collection].append(deepcopy(data[collection][0]))
    with pytest.raises(ValueError):
        validate_lesson_spec(data)


@pytest.mark.parametrize("family", FAMILIES)
def test_allowed_copy_is_explicitly_composed_and_every_other_field_is_preserved(family):
    trusted = blueprint(family)
    request, accepted = admitted_case(family)
    identity = composition_identity(family)
    result = compose_lesson_spec(request, accepted, trusted, identity)
    source, candidate, content = trusted.definition, result.definition, accepted.content
    assert structural_view(candidate) == structural_view(source)
    assert candidate.title == content.title and candidate.summary == content.description
    assert candidate.scenario.context == content.scenario_narrative
    assert candidate.objectives[0].statement == content.objectives[0].statement
    assert candidate.checkpoints[0].prompt == content.prediction.prompt
    assert candidate.checkpoints[1].prompt == content.investigation_prompt
    assert candidate.checkpoints[2].prompt == content.modification_instructions
    for outcome, choice in zip(
        ["rejected", "saved", "server_error"], candidate.checkpoints[0].choices, strict=True
    ):
        assert choice.id == outcome
        selected = getattr(content.prediction.choice_wording, outcome)
        options = getattr(request.approved_prediction_wording, outcome)
        assert choice.label == next(option.label for option in options if option.key == selected)
    assert candidate.misconceptions[0].statement == content.misconceptions[0].statement
    assert (
        candidate.misconceptions[0].suggested_feedback
        == content.misconceptions[0].suggested_feedback
    )
    assert candidate.private == source.private
    assert candidate.scenario.input_values == source.scenario.input_values
    assert candidate.scenario.artifacts == source.scenario.artifacts
    assert [artifact.content.encode("utf-8") for artifact in candidate.scenario.artifacts] == [
        artifact.content.encode("utf-8") for artifact in source.scenario.artifacts
    ]
    assert (candidate.lesson_id, candidate.version_id, candidate.version) == (
        identity.lesson_id,
        identity.version_id,
        identity.version,
    )
    assert candidate.content_sha256 == result.canonical_digest
    assert verify_digest(candidate)
    assert canonical_bytes(candidate) == result.canonical_definition_bytes
    assert validate_lesson_spec(result.canonical_definition_bytes) == candidate


@pytest.mark.parametrize("family", FAMILIES)
def test_trusted_factual_explanation_is_retained_with_the_documented_framing_rule(family):
    source = blueprint(family)
    _, accepted = admitted_case(family)
    result = compose(family, source=source)
    before = next(
        item
        for item in source.definition.explanations
        if item.release_event == "core_verification_passed"
    )
    after = next(item for item in result.definition.explanations if item.id == before.id)
    assert after.text == (
        before.text
        + "\n\nConcept framing:\n"
        + accepted.content.explanations.concept
        + "\n\nEvidence framing:\n"
        + accepted.content.explanations.evidence
    )
    assert after.title == before.title
    assert (
        after.checkpoint_id == before.checkpoint_id and after.release_event == before.release_event
    )


def test_hint_levels_and_core_release_event_bind_copy_without_reordering_blueprint_arrays():
    data = test_definition().model_dump(mode="json")
    replacements = {item["id"]: f"blueprint-level-{item['level']}" for item in data["hints"]}
    for hint in data["hints"]:
        hint["id"] = replacements[hint["id"]]
    for checkpoint in data["checkpoints"]:
        checkpoint["hint_ids"] = [replacements[key] for key in checkpoint["hint_ids"]]
    data["hints"].reverse()
    data["explanations"].reverse()
    data["scenario"]["artifacts"].reverse()
    source = TrustedLessonBlueprint(
        template_family="notes-v1", definition=finalize_definition(data)
    )
    result = compose(source=source)
    _, accepted = admitted_case()
    text_by_level = {
        1: accepted.content.hints.orient,
        2: accepted.content.hints.compare,
        3: accepted.content.hints.investigate_evidence,
    }
    assert [hint.id for hint in result.definition.hints] == [
        hint.id for hint in source.definition.hints
    ]
    assert all(hint.text == text_by_level[hint.level] for hint in result.definition.hints)
    assert [item.id for item in result.definition.explanations] == [
        item.id for item in source.definition.explanations
    ]
    assert structural_view(result.definition) == structural_view(source.definition)


@pytest.mark.parametrize("family", FAMILIES)
def test_unrequested_misconception_copy_preserves_the_complete_trusted_slot(family):
    request, accepted = admitted_case(family, without_misconception=True)
    source = blueprint(family)
    result = compose_lesson_spec(request, accepted, source, composition_identity(family))
    assert result.definition.misconceptions == source.definition.misconceptions


def test_transfer_target_and_retrieval_content_rules_schedules_and_explanations_remain_pinned():
    source = blueprint()
    result = compose(source=source, with_target=True)
    assert result.metadata.transfer_target_digest_status == "verified"
    assert result.definition.checkpoints[4:] == source.definition.checkpoints[4:]
    assert result.definition.private.evaluation == source.definition.private.evaluation
    assert result.definition.completion_policy == source.definition.completion_policy
    assert result.definition.tutor_policy == source.definition.tutor_policy
    assert [
        item
        for item in result.definition.explanations
        if item.release_event == "retrieval_response_saved"
    ] == [
        item
        for item in source.definition.explanations
        if item.release_event == "retrieval_response_saved"
    ]


def test_an_unavailable_transfer_definition_is_reported_without_synthesizing_a_digest():
    source = blueprint()
    result = compose(source=source)
    assert result.metadata.transfer_target_digest_status == "unavailable"
    assert (
        result.definition.checkpoints[4].target_version
        == source.definition.checkpoints[4].target_version
    )
    assert compose("tasks-nested-v1").metadata.transfer_target_digest_status == "not_applicable"


@pytest.mark.parametrize("field", ["lesson_id", "version_id", "version", "content_sha256"])
def test_available_transfer_target_must_match_the_whole_pinned_reference(field):
    request, accepted = admitted_case()
    target = test_definition("tasks-nested-v1").model_dump(mode="json")
    if field == "lesson_id":
        target[field] = "another-test-target"
    elif field == "version_id":
        target[field] = "40000000-0000-4000-8000-000000000004"
    elif field == "version":
        target[field] = "0.2.0"
    else:
        target["title"] = "Different target copy with a different verified digest"
    different = TrustedLessonBlueprint(
        template_family="tasks-nested-v1", definition=finalize_definition(target)
    )
    with pytest.raises(ValueError):
        compose_lesson_spec(
            request,
            accepted,
            blueprint(),
            composition_identity(),
            trusted_transfer_target=different,
        )


@pytest.mark.parametrize("field", ["lesson_id", "version_id"])
def test_supplied_identity_cannot_collide_with_a_pinned_transfer_target(field):
    source = blueprint()
    transfer = source.definition.checkpoints[4]
    assert isinstance(transfer, TransferCheckpoint)
    identity = composition_identity(**{field: getattr(transfer.target_version, field)})
    with pytest.raises(ValueError):
        compose(source=source, identity=identity)


@pytest.mark.parametrize(
    "changes",
    [
        {"lesson_id": "Invalid ID"},
        {"version_id": "not-a-uuid"},
        {"version": "1.0"},
        {"version": 1},
        {"lesson_id": True},
        {"metadata": {}},
    ],
)
def test_composition_identity_uses_existing_strict_identifier_types(changes):
    with pytest.raises(ValueError):
        composition_identity(**changes)


def test_rejected_or_untyped_admission_values_cannot_be_composed():
    request, accepted = admitted_case()
    source, identity = blueprint(), composition_identity()
    rejected = AdmissionRejected(
        code=AdmissionFailureCode.CONTRACT_INVALID, stage="contract", message="Invalid copy."
    )
    for value in [rejected, accepted.content, accepted.model_dump(mode="json"), None]:
        with pytest.raises((ValueError, TypeError)):
            compose_lesson_spec(request, value, source, identity)


@pytest.mark.parametrize("field", ["variant", "wording", "misconception"])
def test_an_accepted_result_is_rebound_to_the_original_exact_request(field):
    request, accepted = admitted_case()
    other = request.model_dump(mode="json")
    if field == "variant":
        other["permitted_narrative_variants"] = ["different-permitted-variant"]
    elif field == "wording":
        for options in other["approved_prediction_wording"].values():
            options[:] = options[:1]
    else:
        other["requested_misconception_slots"] = []
    with pytest.raises(ValueError):
        compose_lesson_spec(
            GenerationRequest.model_validate(other), accepted, blueprint(), composition_identity()
        )


def test_a_structurally_valid_success_envelope_cannot_bypass_admission_references():
    request, accepted = admitted_case()
    content = accepted.content.model_dump(mode="json")
    content["context_variant"] = "not-approved-for-this-request"
    claimed = AdmissionAccepted(
        contract_version="1.0.0",
        template_family="notes-v1",
        content=GeneratedChallengeContent.model_validate(content),
    )
    with pytest.raises(ValueError):
        compose_lesson_spec(request, claimed, blueprint(), composition_identity())


def test_wrong_family_content_or_blueprint_cannot_be_composed():
    request, accepted = admitted_case("notes-v1")
    _, other = admitted_case("tasks-nested-v1")
    with pytest.raises(ValueError):
        compose_lesson_spec(request, other, blueprint(), composition_identity())
    with pytest.raises(ValueError):
        compose_lesson_spec(request, accepted, blueprint("tasks-nested-v1"), composition_identity())


def test_combined_explanation_overflow_rejects_instead_of_truncating_trusted_facts():
    data = test_definition().model_dump(mode="json")
    data["explanations"][0]["text"] = "x" * 4000
    source = TrustedLessonBlueprint(
        template_family="notes-v1", definition=finalize_definition(data)
    )
    before = source.definition.explanations[0].text
    with pytest.raises(ValueError):
        compose(source=source)
    assert source.definition.explanations[0].text == before


@pytest.mark.parametrize("family", FAMILIES)
def test_composition_is_deterministic_and_does_not_mutate_its_inputs(family):
    request, accepted = admitted_case(family)
    source, identity = blueprint(family), composition_identity(family)
    before = [value.model_dump_json() for value in [request, accepted, source, identity]]
    first = compose_lesson_spec(request, accepted, source, identity)
    second = compose_lesson_spec(request, accepted, source, identity)
    assert first == second and first.canonical_definition_bytes == second.canonical_definition_bytes
    assert [value.model_dump_json() for value in [request, accepted, source, identity]] == before
    assert first.state == "composed_unverified" and first.release_eligible is False
    assert first.metadata.contract_version == first.metadata.admission_policy_version == "1.0.0"
    assert first.metadata.template_family == family
    assert first.metadata.context_variant == accepted.content.context_variant
    assert first.metadata.blueprint.content_sha256 == source.definition.content_sha256
    assert first.metadata.blueprint.version_id == source.definition.version_id
    assert (
        first.metadata.blueprint_runtime_revision
        == source.definition.private.runtime_binding.revision
    )


def test_composition_results_are_frozen_and_cannot_declare_release_or_publication():
    result = compose()
    for value, field, replacement in [
        (result, "release_eligible", True),
        (result, "state", "published"),
        (result.metadata, "context_variant", "changed"),
        (result.definition, "title", "Changed"),
    ]:
        with pytest.raises(ValidationError):
            setattr(value, field, replacement)
    with pytest.raises(TypeError):
        result.definition.private.evaluation.rules["prediction"] = None
    for changes in [{"release_eligible": True}, {"state": "published"}, {"published": True}]:
        candidate = {
            "definition": result.definition,
            "canonical_digest": result.canonical_digest,
            "canonical_definition_bytes": result.canonical_definition_bytes,
            "metadata": result.metadata,
        }
        assert ComposedLessonCandidate.model_validate(candidate) == result
        candidate.update(changes)
        with pytest.raises(ValueError):
            ComposedLessonCandidate.model_validate(candidate)


def test_initial_public_projection_has_no_private_digest_future_content_or_composition_metadata():
    result = compose(with_target=True)
    projection = initial_learner_projection(result.definition)
    data = projection.model_dump(mode="json")

    def keys(value):
        if isinstance(value, dict):
            yield from value
            for child in value.values():
                yield from keys(child)
        elif isinstance(value, list):
            for child in value:
                yield from keys(child)

    assert not set(keys(data)) & {
        "private",
        "content_sha256",
        "canonical_digest",
        "canonical_definition_bytes",
        "metadata",
        "context_variant",
        "rules",
        "correct_value",
        "answer",
        "target_version",
        "hints",
        "explanations",
        "misconceptions",
        "completion_policy",
        "tutor_policy",
    }
    serialized = json.dumps(data)
    assert result.canonical_digest not in serialized
    assert result.metadata.context_variant not in serialized
    assert result.metadata.blueprint.content_sha256 not in serialized


def test_composition_requires_no_io_database_randomness_or_wall_clock(monkeypatch):
    inputs = [
        (admitted_case(family), blueprint(family), composition_identity(family))
        for family in FAMILIES
    ]

    def forbidden(*args, **kwargs):
        pytest.fail(
            "Pure composition attempted I/O, database access, randomness or wall-clock time"
        )

    for owner, name in [
        (builtins, "open"),
        (Path, "read_text"),
        (Path, "read_bytes"),
        (socket, "create_connection"),
        (socket, "getaddrinfo"),
        (Session, "execute"),
        (uuid, "uuid4"),
        (random, "random"),
        (time, "time"),
        (time, "monotonic"),
    ]:
        monkeypatch.setattr(owner, name, forbidden)
    for (request, accepted), source, identity in inputs:
        assert compose_lesson_spec(request, accepted, source, identity).release_eligible is False
