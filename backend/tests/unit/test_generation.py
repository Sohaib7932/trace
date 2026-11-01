"""Strict generation data contracts; admission and generation execution are absent."""

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.domain.lesson_spec import LessonSpecV1
from app.schemas.generation import (
    MAX_COMPLETION_CAPTURE_BYTES,
    MAX_GENERATED_CONTENT_BYTES,
    GeneratedChallengeContent,
    GenerationCompletion,
    GenerationRequest,
)
from tests.generation_fixtures import completion_data, content_data, evidence_data, request_data


def locate(root, path):
    for key in path:
        root = root[key]
    return root


@pytest.mark.parametrize("family", ["notes-v1", "tasks-nested-v1"])
def test_content_and_server_brief_accept_existing_example_copy_slots(family):
    body, brief = content_data(family), request_data(family)
    content = GeneratedChallengeContent.model_validate(body)
    request = GenerationRequest.model_validate(brief)
    assert content.model_dump(mode="json") == body
    assert request.model_dump(mode="json") == brief
    assert GeneratedChallengeContent.model_validate_json(content.model_dump_json()) == content
    assert not issubclass(GeneratedChallengeContent, LessonSpecV1)
    assert "LessonSpecV1" not in GeneratedChallengeContent.model_json_schema().get("$defs", {})


def object_paths(value, path=()):
    if isinstance(value, dict):
        yield path
        for key, child in value.items():
            yield from object_paths(child, path + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from object_paths(child, path + (index,))


CONTRACTS = [
    (GeneratedChallengeContent, content_data()),
    (GenerationRequest, request_data()),
    (GenerationCompletion, completion_data()),
]
OBJECTS = [(model, data, path) for model, data in CONTRACTS for path in object_paths(data)]


@pytest.mark.parametrize("model,source,path", OBJECTS)
@pytest.mark.parametrize(
    "field", ["metadata", "answer", "checkpoint_id", "evaluation_rule_id", "private"]
)
def test_unknown_or_authoritative_fields_rejected_at_every_nested_level(model, source, path, field):
    data = deepcopy(source)
    locate(data, path)[field] = "Not a permitted capability"
    with pytest.raises(ValidationError):
        model.model_validate(data)


@pytest.mark.parametrize("model,source", CONTRACTS)
def test_every_nested_model_and_collection_is_immutable(model, source):
    result = model.model_validate(source)

    def check(value):
        if hasattr(type(value), "model_fields"):
            for name in type(value).model_fields:
                child = getattr(value, name)
                with pytest.raises(ValidationError):
                    setattr(value, name, child)
                check(child)
        elif isinstance(value, tuple):
            for child in value:
                check(child)
        else:
            assert not isinstance(value, (dict, list, set))

    check(result)


@pytest.mark.parametrize("model,data", CONTRACTS[:2])
@pytest.mark.parametrize("version", ["2.0.0", "1.0", 1, None])
def test_content_and_request_contract_version_is_fixed(model, data, version):
    candidate = {**data, "contract_version": version}
    with pytest.raises(ValidationError):
        model.model_validate(candidate)


@pytest.mark.parametrize("model,data", CONTRACTS[:2])
def test_contract_version_is_required(model, data):
    candidate = deepcopy(data)
    del candidate["contract_version"]
    with pytest.raises(ValidationError):
        model.model_validate(candidate)


TEXT_FIELDS = [
    (("title",), 120),
    (("description",), 600),
    (("objectives", 0, "statement"), 600),
    (("scenario_narrative",), 2000),
    (("prediction", "prompt"), 1000),
    (("investigation_prompt",), 1000),
    (("modification_instructions",), 1000),
    (("hints", "orient"), 500),
    (("hints", "compare"), 500),
    (("hints", "investigate_evidence"), 500),
    (("explanations", "concept"), 1000),
    (("explanations", "evidence"), 1000),
    (("misconceptions", 0, "statement"), 600),
    (("misconceptions", 0, "suggested_feedback"), 600),
]


@pytest.mark.parametrize("path,limit", TEXT_FIELDS)
def test_copy_lengths_have_real_boundaries(path, limit):
    data = content_data()
    locate(data, path[:-1])[path[-1]] = "x" * limit
    assert GeneratedChallengeContent.model_validate(data)
    locate(data, path[:-1])[path[-1]] += "x"
    with pytest.raises(ValidationError) as failure:
        GeneratedChallengeContent.model_validate(data)
    assert any(error["type"] == "string_too_long" for error in failure.value.errors())


@pytest.mark.parametrize(
    "text",
    [
        "",
        " \n\t",
        "<script>bad</script>",
        "https://example.test",
        "javascript:alert(1)",
        "```python\nprint('bad')\n```",
        "~~~sh\necho bad\n~~~",
        "    print('bad')",
        "import os",
        "from os import system",
        "def run(): pass",
        "class Runner: pass",
        "for value in values: run(value)",
        'payload = {"field": "value"}',
        "eval('bad')",
        "client.post('endpoint')",
        "rm -rf example",
        "powershell.exe -Command bad",
        "$(bad)",
        "SELECT * FROM example",
        "INSERT INTO example VALUES (1)",
        "bad\x00copy",
    ],
)
def test_plain_copy_rejects_markup_urls_and_obvious_executable_syntax(text):
    data = {**content_data(), "scenario_narrative": text}
    with pytest.raises(ValidationError):
        GeneratedChallengeContent.model_validate(data)


def test_educational_text_is_preserved_without_normalization():
    text = "  Compare the receiving contract.\nThen inspect independent evidence.  "
    content = GeneratedChallengeContent.model_validate(
        {**content_data(), "scenario_narrative": text}
    )
    assert content.scenario_narrative == text


@pytest.mark.parametrize(
    "path,count", [(("objectives",), 0), (("objectives",), 4), (("misconceptions",), 4)]
)
def test_generated_collection_limits(path, count):
    data = content_data()
    original = locate(data, path)
    entries = [deepcopy(original[0]) for _ in range(count)]
    for index, entry in enumerate(entries):
        entry["slot_key"] = f"copy-{index}"
    locate(data, path[:-1])[path[-1]] = entries
    with pytest.raises(ValidationError):
        GeneratedChallengeContent.model_validate(data)


@pytest.mark.parametrize("field", ["objectives", "misconceptions"])
def test_duplicate_copy_slots_rejected(field):
    data = content_data()
    data[field].append(deepcopy(data[field][0]))
    with pytest.raises(ValidationError, match="unique"):
        GeneratedChallengeContent.model_validate(data)


@pytest.mark.parametrize("slot", ["rejected", "saved", "server_error"])
def test_prediction_slots_are_fixed_and_all_required(slot):
    data = content_data()
    del data["prediction"]["choice_wording"][slot]
    with pytest.raises(ValidationError):
        GeneratedChallengeContent.model_validate(data)
    data["prediction"]["choice_wording"]["correct"] = "default"
    with pytest.raises(ValidationError):
        GeneratedChallengeContent.model_validate(data)


@pytest.mark.parametrize(
    "value", ["Freeform outcome label", {"label": "Anything", "correct": True}, 1, "", "x" * 65]
)
def test_prediction_wording_contains_only_bounded_keys(value):
    data = content_data()
    data["prediction"]["choice_wording"]["rejected"] = value
    with pytest.raises(ValidationError):
        GeneratedChallengeContent.model_validate(data)


@pytest.mark.parametrize(
    "field",
    [
        "metadata",
        "instructions",
        "reasoning",
        "learner_id",
        "email",
        "credentials",
        "database_url",
        "correct_mapping",
        "verification",
    ],
)
def test_server_request_has_no_open_metadata_instructions_or_personal_data(field):
    data = {**request_data(), field: "Not a brief field"}
    with pytest.raises(ValidationError):
        GenerationRequest.model_validate(data)


@pytest.mark.parametrize(
    "field,count",
    [
        ("permitted_narrative_variants", 0),
        ("permitted_narrative_variants", 9),
        ("requested_objective_slots", 0),
        ("requested_objective_slots", 4),
        ("requested_misconception_slots", 4),
        ("allowed_instructional_facts", 0),
    ],
)
def test_request_collection_limits(field, count):
    data = request_data()
    data[field] = ["copy-" + str(index) for index in range(count)]
    with pytest.raises(ValidationError):
        GenerationRequest.model_validate(data)


@pytest.mark.parametrize(
    "field",
    [
        "permitted_narrative_variants",
        "requested_objective_slots",
        "requested_misconception_slots",
        "allowed_instructional_facts",
    ],
)
def test_request_references_cannot_be_duplicated(field):
    data = request_data()
    data[field].append(data[field][0])
    with pytest.raises(ValidationError, match="unique"):
        GenerationRequest.model_validate(data)


@pytest.mark.parametrize("slot", ["rejected", "saved", "server_error"])
@pytest.mark.parametrize("operation", ["empty", "too-many", "duplicate", "correctness"])
def test_approved_wording_options_are_bounded_without_correctness_flags(slot, operation):
    data = request_data()
    options = data["approved_prediction_wording"][slot]
    if operation == "empty":
        options.clear()
    elif operation == "too-many":
        options[:] = [
            {"key": f"wording-{index}", "label": "A bounded outcome description."}
            for index in range(9)
        ]
    elif operation == "duplicate":
        options.append(deepcopy(options[0]))
    else:
        options[0]["correct"] = True
    with pytest.raises(ValidationError):
        GenerationRequest.model_validate(data)


def test_request_limits_template_and_fact_capabilities_without_admission():
    with pytest.raises(ValidationError):
        GenerationRequest.model_validate({**request_data(), "template_family": "arbitrary-code"})
    with pytest.raises(ValidationError, match="nested"):
        GenerationRequest.model_validate(
            {**request_data(), "allowed_instructional_facts": ["nested-receiver-shape"]}
        )
    with pytest.raises(ValidationError):
        GenerationRequest.model_validate(
            {**request_data(), "allowed_instructional_facts": ["raw-sql"]}
        )
    assert GenerationRequest.model_validate({**request_data(), "learner_evidence": None})
    # Reference membership is deliberately not checked by these standalone types.
    data = {**content_data(), "context_variant": "another-bounded-reference"}
    assert (
        GeneratedChallengeContent.model_validate(data).context_variant
        not in request_data()["permitted_narrative_variants"]
    )


@pytest.mark.parametrize("field", list(evidence_data()))
@pytest.mark.parametrize("value", [-1, 10001, True, "1", 1.0])
def test_factual_evidence_counts_are_bounded_integers(field, value):
    data = request_data()
    data["learner_evidence"][field] = value
    with pytest.raises(ValidationError):
        GenerationRequest.model_validate(data)


@pytest.mark.parametrize(
    "field", ["correct_prediction_count", "hints_delivered_count", "correct_retrieval_answer_count"]
)
def test_evidence_cannot_claim_more_successes_than_observations(field):
    data = request_data()
    data["learner_evidence"][field] = 100
    with pytest.raises(ValidationError):
        GenerationRequest.model_validate(data)


@pytest.mark.parametrize(
    "status",
    [
        "success",
        "refusal",
        "truncated",
        "timeout",
        "rate_limited",
        "unavailable",
        "transport_error",
    ],
)
def test_completion_statuses_are_explicit_transport_states(status):
    data = completion_data(status)
    frame = GenerationCompletion.model_validate(data)
    assert frame.status == status and frame.model_dump(mode="json") == data
    assert frame.transport.source == "transport"
    assert frame.transport.model.returned_model_id is None


@pytest.mark.parametrize("status", ["passed", "validated", "published", "completed", True, 1, None])
def test_transport_cannot_claim_content_validation_or_other_statuses(status):
    with pytest.raises(ValidationError):
        GenerationCompletion.model_validate(completion_data(status))


@pytest.mark.parametrize("raw", [None, "", " \n\t"])
def test_success_requires_output_text(raw):
    data = completion_data()
    data["raw_json"] = raw
    with pytest.raises(ValidationError):
        GenerationCompletion.model_validate(data)


def test_raw_completion_is_preserved_and_is_never_typed_admission():
    raw = ' \n{"title":"first","title":"second","answer":"untrusted claim"} \n'
    frame = GenerationCompletion.model_validate(completion_data(raw_json=raw))
    assert frame.raw_json == raw
    assert "untrusted claim" not in repr(frame)
    assert not hasattr(frame, "validated")
    # The envelope preserves malformed/truncated JSON for later admission handling.
    assert (
        GenerationCompletion.model_validate(completion_data("truncated", '{"title":')).raw_json
        == '{"title":'
    )
    oversized = " " * MAX_GENERATED_CONTENT_BYTES + json.dumps(content_data())
    assert (
        GenerationCompletion.model_validate(completion_data(raw_json=oversized)).raw_json
        == oversized
    )
    with pytest.raises(ValidationError, match="65536"):
        GenerationCompletion.model_validate(
            completion_data(raw_json="é" * (MAX_COMPLETION_CAPTURE_BYTES // 2 + 1))
        )


def test_completion_metadata_is_transport_observation_not_model_generated_claims():
    data = completion_data(raw_json='{"provider":"model-claimed-provider"}')
    result = GenerationCompletion.model_validate(data)
    assert result.transport.provider.provider_id == "test-transport"
    data["transport"]["source"] = "model"
    with pytest.raises(ValidationError):
        GenerationCompletion.model_validate(data)


def test_content_budget_is_utf8_and_includes_all_nested_copy():
    data = content_data()
    for path, limit in TEXT_FIELDS:
        locate(data, path[:-1])[path[-1]] = "x" * limit
    data["objectives"] = [{"slot_key": f"objective-{i}", "statement": "x" * 600} for i in range(3)]
    data["misconceptions"] = [
        {"slot_key": f"misconception-{i}", "statement": "x" * 600, "suggested_feedback": "x" * 600}
        for i in range(3)
    ]
    data["scenario_narrative"] = "é" * 2000
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    excess = len(encoded) - MAX_GENERATED_CONTENT_BYTES
    assert 0 < excess < 2000
    data["scenario_narrative"] = "a" * excess + "é" * (2000 - excess)
    content = GeneratedChallengeContent.model_validate(data)
    assert len(content.model_dump_json().encode("utf-8")) == MAX_GENERATED_CONTENT_BYTES
    data["scenario_narrative"] = data["scenario_narrative"].replace("a", "é", 1)
    with pytest.raises(ValidationError, match="16384"):
        GeneratedChallengeContent.model_validate(data)
