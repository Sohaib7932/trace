"""The fake is a deterministic copy source, never a tutor or live AI provider."""

import builtins
import inspect
import json
import random
import secrets
import socket
import time
import uuid
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import get_type_hints

import pytest
import sqlalchemy
from sqlalchemy.orm import Session

from app.ai.providers.fake_question_generator import FakeQuestionGenerator
from app.ai.providers.question_fixtures import COPY_FIXTURES
from app.ai.question_generator import QuestionGenerator
from app.domain.generation_copy import TEMPLATE_COPY_SLOTS
from app.schemas.generation import GenerationRequest
from app.schemas.generation_admission import AdmissionAccepted, AdmissionRejected
from app.services.challenge_content_admission import ChallengeContentAdmission
from tests.generation_fixtures import reference_definition, request_data

FAMILIES = ["notes-v1", "tasks-nested-v1"]


@pytest.mark.parametrize("family", FAMILIES)
def test_reviewed_fixtures_match_existing_public_copy_destinations(family):
    public = reference_definition(family)
    slots = TEMPLATE_COPY_SLOTS[family]
    fixture = COPY_FIXTURES[family]
    assert slots.objectives == {item["id"] for item in public["objectives"]}
    assert slots.misconceptions == {item["id"] for item in public["misconceptions"]}
    assert {item.slot_key for item in fixture.objectives} == slots.objectives
    assert {item.slot_key for item in fixture.misconceptions} == slots.misconceptions


@pytest.mark.parametrize("family", FAMILIES)
def test_fake_obeys_generator_port_and_produces_admissible_copy(family):
    provider: QuestionGenerator = FakeQuestionGenerator()
    request = GenerationRequest.model_validate(request_data(family))
    completion = provider.generate(request)
    result = ChallengeContentAdmission().admit(request, completion)
    assert isinstance(result, AdmissionAccepted)
    assert result.template_family == family and result.release_eligible is False
    assert result.content == COPY_FIXTURES[family]
    assert get_type_hints(FakeQuestionGenerator.generate) == get_type_hints(
        QuestionGenerator.generate
    )
    assert not inspect.iscoroutinefunction(provider.generate)
    for name in ["generate_hint", "explain_attempt", "analyse_misconception"]:
        assert not hasattr(provider, name)


@pytest.mark.parametrize("family", FAMILIES)
def test_metadata_is_server_controlled_and_explicitly_fake(family):
    completion = FakeQuestionGenerator().generate(
        GenerationRequest.model_validate(request_data(family))
    )
    assert completion.status == "success"  # Transport success, not live AI or release.
    assert completion.transport.source == "transport"
    assert completion.transport.provider.provider_id == "fake-question-generator-test-fixture"
    assert completion.transport.provider.request_id is None
    assert completion.transport.model.requested_model_id is None
    assert completion.transport.model.returned_model_id == "static-copy-test-fixture-v1"
    body = json.loads(completion.raw_json)
    assert not {"provider", "model", "transport", "provenance", "private"} & body.keys()


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize(
    "fixture,code",
    [
        ("valid", None),
        ("refusal", "completion_refused"),
        ("malformed_json", "invalid_json"),
        ("truncated", "completion_truncated"),
        ("unknown_fields", "contract_invalid"),
        ("unsupported_references", "objective_slots_mismatch"),
        ("invalid_content", "contract_invalid"),
    ],
)
def test_every_fixture_is_deterministic_and_has_the_expected_admission_outcome(
    family, fixture, code
):
    request = GenerationRequest.model_validate(request_data(family))
    restored = GenerationRequest.model_validate_json(request.model_dump_json())
    provider = FakeQuestionGenerator(fixture)
    first = provider.generate(request)
    assert first == provider.generate(request) == FakeQuestionGenerator(fixture).generate(restored)
    assert first.model_dump_json() == provider.generate(request).model_dump_json()
    result = ChallengeContentAdmission().admit(request, first)
    if code is None:
        assert isinstance(result, AdmissionAccepted)
    else:
        assert isinstance(result, AdmissionRejected) and result.code == code


@pytest.mark.parametrize("family", FAMILIES)
def test_fake_binds_only_permitted_references_and_optional_misconception_slots(family):
    data = request_data(family)
    data["permitted_narrative_variants"] = ["server-selected-narrative", "another-narrative"]
    data["requested_misconception_slots"] = []
    for index, options in enumerate(data["approved_prediction_wording"].values()):
        options[0]["key"] = f"server-wording-{index}"
    request = GenerationRequest.model_validate(data)
    result = ChallengeContentAdmission().admit(request, FakeQuestionGenerator().generate(request))
    assert isinstance(result, AdmissionAccepted)
    assert result.content.context_variant == "server-selected-narrative"
    assert not result.content.misconceptions
    assert set(result.content.prediction.choice_wording.model_dump().values()) == {
        "server-wording-0",
        "server-wording-1",
        "server-wording-2",
    }


def test_generation_and_admission_have_no_io_clock_randomness_or_record_access(monkeypatch):
    requests = [GenerationRequest.model_validate(request_data(family)) for family in FAMILIES]

    def forbidden(*args, **kwargs):
        pytest.fail("Generation/admission attempted I/O, time or randomness")

    for owner, name in [
        (builtins, "open"),
        (Path, "read_text"),
        (Path, "read_bytes"),
        (socket, "create_connection"),
        (socket, "getaddrinfo"),
        (socket.socket, "connect"),
        (sqlalchemy, "create_engine"),
        (Session, "execute"),
        (Session, "get"),
        (random, "random"),
        (secrets, "token_hex"),
        (uuid, "uuid4"),
        (time, "time"),
        (time, "monotonic"),
    ]:
        monkeypatch.setattr(owner, name, forbidden)
    for request in requests:
        result = ChallengeContentAdmission().admit(
            request, FakeQuestionGenerator().generate(request)
        )
        assert isinstance(result, AdmissionAccepted)


def test_factual_evidence_does_not_change_the_fixed_copy_or_require_record_access():
    original = request_data()
    alternate = request_data()
    alternate["learner_evidence"] = {key: 0 for key in alternate["learner_evidence"]}
    provider = FakeQuestionGenerator()
    assert provider.generate(GenerationRequest.model_validate(original)) == provider.generate(
        GenerationRequest.model_validate(alternate)
    )


@pytest.mark.parametrize("field", ["requested_objective_slots", "requested_misconception_slots"])
def test_fake_refuses_briefs_outside_reviewed_copy_destinations(field):
    data = {**request_data(), field: ["unreviewed-slot"]}
    result = FakeQuestionGenerator().generate(GenerationRequest.model_validate(data))
    assert result.status == "refusal" and result.raw_json is None


def test_failure_fixtures_cannot_mutate_the_reviewed_copy_or_later_calls():
    request = GenerationRequest.model_validate(request_data())
    before = FakeQuestionGenerator().generate(request)
    FakeQuestionGenerator("unknown_fields").generate(request)
    FakeQuestionGenerator("unsupported_references").generate(request)
    assert FakeQuestionGenerator().generate(request) == before
    provider = FakeQuestionGenerator()
    with pytest.raises(FrozenInstanceError):
        provider.fixture = "refusal"
    with pytest.raises(ValueError, match="Unknown fake"):
        FakeQuestionGenerator("not-a-fixture")
