"""Raw-wire admission, exact brief binding and safe result boundaries."""

import json
from copy import deepcopy

import pytest
from pydantic import TypeAdapter, ValidationError

from app.ai.providers.fake_question_generator import FakeQuestionGenerator
from app.domain.generation_copy import EXPLANATION_SLOTS, HINT_SLOTS, PREDICTION_SLOTS
from app.schemas.generation import (
    MAX_GENERATED_CONTENT_BYTES,
    GeneratedChallengeContent,
    GenerationCompletion,
    GenerationRequest,
)
from app.schemas.generation_admission import (
    AdmissionAccepted,
    AdmissionFailureCode,
    AdmissionRejected,
    AdmissionResult,
)
from app.services import challenge_content_admission as admission_module
from app.services.challenge_content_admission import (
    MAX_ADMISSION_JSON_DEPTH,
    ChallengeContentAdmission,
)
from tests.generation_fixtures import completion_data, content_data, request_data


def brief(family="notes-v1", **changes):
    return GenerationRequest.model_validate({**request_data(family), **changes})


def completion(raw, status="success"):
    data = completion_data(status)
    data["raw_json"] = raw
    return GenerationCompletion.model_validate(data)


def admit(data=None, *, request=None, raw=None):
    if raw is None:
        raw = json.dumps(content_data() if data is None else data)
    return ChallengeContentAdmission().admit(
        brief() if request is None else request, completion(raw)
    )


def rejected(result, code, stage):
    assert isinstance(result, AdmissionRejected)
    assert result.status == "rejected" and result.code == code and result.stage == stage
    assert 0 < len(result.message) <= 200
    return result


@pytest.mark.parametrize("family", ["notes-v1", "tasks-nested-v1"])
def test_valid_content_retains_typed_frozen_copy_and_server_family(family):
    request = brief(family)
    result = admit(content_data(family), request=request)
    assert isinstance(result, AdmissionAccepted)
    assert result.contract_version == result.admission_policy_version == "1.0.0"
    assert result.template_family == family
    assert isinstance(result.content, GeneratedChallengeContent)
    assert result.release_eligible is False and not hasattr(result, "published")
    with pytest.raises(ValidationError):
        result.content.prediction.choice_wording.rejected = "changed"
    with pytest.raises(ValidationError):
        result.content.objectives[0].statement = "Changed."
    with pytest.raises(ValidationError):
        result.release_eligible = True
    with pytest.raises(ValidationError):
        AdmissionAccepted.model_validate({**result.model_dump(), "release_eligible": True})
    restored = TypeAdapter(AdmissionResult).validate_json(result.model_dump_json())
    assert restored == result


@pytest.mark.parametrize(
    "status,code",
    [
        ("refusal", "completion_refused"),
        ("truncated", "completion_truncated"),
        ("timeout", "completion_unsuccessful"),
        ("rate_limited", "completion_unsuccessful"),
        ("unavailable", "completion_unsuccessful"),
        ("transport_error", "completion_unsuccessful"),
    ],
)
def test_unsuccessful_completions_are_never_parsed_or_recovered(status, code, monkeypatch):
    request, response = brief(), completion('{"partial":', status)

    def forbidden(*args, **kwargs):
        pytest.fail("Unsuccessful completion reached JSON parsing")

    monkeypatch.setattr(admission_module.json, "loads", forbidden)
    result = ChallengeContentAdmission().admit(request, response)
    rejected(result, code, "completion")


@pytest.mark.parametrize("raw", [None, "", " \n\t"])
def test_missing_successful_output_is_already_forbidden_by_completion_contract(raw):
    # Do not bypass Phase 2.1 validation to manufacture an impossible completion.
    with pytest.raises(ValidationError):
        completion(raw)
    result = ChallengeContentAdmission().admit(brief(), completion(raw, "transport_error"))
    rejected(result, "completion_unsuccessful", "completion")


def test_original_wire_size_including_whitespace_is_enforced_at_the_boundary(monkeypatch):
    request = brief()
    raw = json.dumps(content_data())
    raw += " " * (MAX_GENERATED_CONTENT_BYTES - len(raw.encode("utf-8")))
    assert len(raw.encode("utf-8")) == MAX_GENERATED_CONTENT_BYTES
    assert isinstance(admit(request=request, raw=raw), AdmissionAccepted)
    response = completion(raw + " ")

    def forbidden(*args, **kwargs):
        pytest.fail("Oversized output reached JSON parsing")

    monkeypatch.setattr(admission_module.json, "loads", forbidden)
    rejected(
        ChallengeContentAdmission().admit(request, response), "raw_output_too_large", "raw_size"
    )


def test_raw_size_counts_utf8_bytes_not_characters():
    data = {**content_data(), "scenario_narrative": "é" * 2000}
    raw = json.dumps(data, ensure_ascii=False)
    raw += " " * (MAX_GENERATED_CONTENT_BYTES - 1 - len(raw))
    assert len(raw) < MAX_GENERATED_CONTENT_BYTES < len(raw.encode("utf-8"))
    rejected(admit(raw=raw), "raw_output_too_large", "raw_size")


@pytest.mark.parametrize("raw", ['{"title":', '{"a":1,}', "{} {}", "// comment\n{}"])
def test_malformed_json_is_rejected(raw):
    rejected(admit(raw=raw), "invalid_json", "json")


@pytest.mark.parametrize(
    "raw",
    [
        '{"title":"one","title":"two"}',
        '{"title":"one","\\u0074itle":"two"}',
        '{"prediction":{"prompt":"one","prompt":"two"}}',
        '{"objectives":[{"slot_key":"one","slot_key":"two"}]}',
        '{"unused":{"nested":{"key":1,"key":2}}}',
    ],
)
def test_duplicate_properties_are_rejected_before_any_dictionary_discards_them(raw):
    rejected(admit(raw=raw), "duplicate_json_property", "json")


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"])
def test_non_standard_or_overflowing_json_numbers_are_rejected(number):
    rejected(admit(raw='{"unused":' + number + "}"), "non_standard_json_number", "json")


@pytest.mark.parametrize("raw", ["[]", '"text"', "null", "true", "1", "1.25"])
def test_only_object_roots_are_accepted(raw):
    rejected(admit(raw=raw), "json_root_not_object", "json")


@pytest.mark.parametrize("raw", [b"\xff", b'{"title":"valid bytes"}'])
def test_bytes_are_not_an_allowed_phase_2_1_completion_representation(raw):
    with pytest.raises(ValidationError):
        completion(raw)


@pytest.mark.parametrize("raw", ['{"title":"\\ud800"}', '{"\\udfff":"value"}'])
def test_escaped_unpaired_unicode_surrogates_are_rejected(raw):
    rejected(admit(raw=raw), "invalid_utf8", "json")


def test_json_depth_and_parser_recursion_fail_closed():
    nested = (
        '{"nested":' + "[" * MAX_ADMISSION_JSON_DEPTH + "0" + "]" * MAX_ADMISSION_JSON_DEPTH + "}"
    )
    rejected(admit(raw=nested), "json_depth_exceeded", "json")
    recursive = '{"nested":' + "[" * 2000 + "0" + "]" * 2000 + "}"
    rejected(admit(raw=recursive), "json_depth_exceeded", "json")


def object_paths(value, path=()):
    if isinstance(value, dict):
        yield path
        for key, child in value.items():
            yield from object_paths(child, path + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from object_paths(child, path + (index,))


def locate(data, path):
    for key in path:
        data = data[key]
    return data


@pytest.mark.parametrize("path", list(object_paths(content_data())))
def test_unknown_fields_at_every_content_object_are_not_discarded(path):
    data = content_data()
    locate(data, path)["private"] = "Untrusted extension."
    rejected(admit(data), "contract_invalid", "contract")


@pytest.mark.parametrize(
    "field", ["answer", "template_family", "source_artifacts", "metadata", "release_eligible"]
)
def test_generated_claims_cannot_expand_the_contract(field):
    rejected(admit({**content_data(), field: "Untrusted claim."}), "contract_invalid", "contract")


@pytest.mark.parametrize("value", [None, True, 1, 1.5, [], {}])
def test_copy_fields_are_strictly_typed(value):
    rejected(admit({**content_data(), "title": value}), "contract_invalid", "contract")


@pytest.mark.parametrize(
    "path,limit",
    [
        (("title",), 120),
        (("scenario_narrative",), 2000),
        (("hints", "orient"), 500),
        (("explanations", "evidence"), 1000),
    ],
)
def test_text_limits_remain_enforced_through_admission(path, limit):
    data = content_data()
    locate(data, path[:-1])[path[-1]] = "x" * (limit + 1)
    rejected(admit(data), "contract_invalid", "contract")


@pytest.mark.parametrize("field", ["objectives", "misconceptions"])
def test_collection_limits_and_duplicate_slot_constraints_are_preserved(field):
    data = content_data()
    data[field].append(deepcopy(data[field][0]))
    rejected(admit(data), "contract_invalid", "contract")
    data[field] = [dict(data[field][0], slot_key=f"copy-{index}") for index in range(4)]
    rejected(admit(data), "contract_invalid", "contract")


@pytest.mark.parametrize("family", ["notes-v1", "tasks-nested-v1"])
def test_other_family_objectives_are_rejected_even_if_syntactically_valid(family):
    other = "tasks-nested-v1" if family == "notes-v1" else "notes-v1"
    rejected(
        admit(content_data(other), request=brief(family)),
        "template_reference_mismatch",
        "references",
    )


@pytest.mark.parametrize(
    "field,slots",
    [
        ("requested_objective_slots", ["trace-nesting"]),
        ("requested_objective_slots", ["unreviewed-objective"]),
        ("requested_misconception_slots", ["unreviewed-misconception"]),
    ],
)
def test_a_brief_cannot_create_cross_family_or_unreviewed_copy_destinations(field, slots):
    rejected(admit(request=brief(**{field: slots})), "template_reference_mismatch", "references")


def test_unknown_objectives_and_unsupported_variants_are_request_bound():
    data = content_data()
    data["objectives"][0]["slot_key"] = "unknown-objective"
    rejected(admit(data), "objective_slots_mismatch", "references")
    data = {**content_data(), "context_variant": "not-in-this-brief"}
    rejected(admit(data), "context_variant_not_permitted", "references")
    # A valid variant can be admitted only when this exact request permits it.
    assert isinstance(
        admit(data, request=brief(permitted_narrative_variants=["not-in-this-brief"])),
        AdmissionAccepted,
    )


@pytest.mark.parametrize("mode", ["missing", "unknown", "unrequested"])
def test_misconception_copy_matches_requested_slots_exactly(mode):
    data = content_data()
    request = brief()
    if mode == "missing":
        data["misconceptions"] = []
    elif mode == "unknown":
        data["misconceptions"][0]["slot_key"] = "unknown-misconception"
    else:
        request = brief(requested_misconception_slots=[])
    rejected(admit(data, request=request), "misconception_slots_mismatch", "references")


def test_wording_keys_are_authorized_per_outcome_and_per_exact_request():
    data = request_data()
    for slot, options in data["approved_prediction_wording"].items():
        options[0]["key"] = slot.replace("_", "-") + "-wording"
    request = GenerationRequest.model_validate(data)
    generated = FakeQuestionGenerator().generate(request)
    assert isinstance(ChallengeContentAdmission().admit(request, generated), AdmissionAccepted)
    body = json.loads(generated.raw_json)
    body["prediction"]["choice_wording"]["rejected"] = "saved-wording"
    rejected(admit(body, request=request), "prediction_wording_not_permitted", "references")
    # Keys approved for another request are insufficient, even in the same slot.
    rejected(admit(request=request), "prediction_wording_not_permitted", "references")


FIXED_SLOTS = [
    *((("prediction", "choice_wording"), slot) for slot in sorted(PREDICTION_SLOTS)),
    *((("hints",), slot) for slot in sorted(HINT_SLOTS)),
    *((("explanations",), slot) for slot in sorted(EXPLANATION_SLOTS)),
]


@pytest.mark.parametrize("path,slot", FIXED_SLOTS)
@pytest.mark.parametrize("mode", ["missing", "unrequested"])
def test_fixed_prediction_hint_and_explanation_slots_cannot_change(path, slot, mode):
    data = content_data()
    target = locate(data, path)
    if mode == "missing":
        del target[slot]
    else:
        target["unrequested-slot"] = "Unrequested copy."
    rejected(admit(data), "contract_invalid", "contract")


def test_missing_objective_reference_is_rejected_without_recovery():
    rejected(admit({**content_data(), "objectives": []}), "contract_invalid", "contract")


@pytest.mark.parametrize(
    "text",
    [
        "<script>bad</script>",
        "https://example.test",
        "www.example.test",
        "javascript:bad",
        "```python\nprint('bad')\n```",
        "~~~sh\nbad\n~~~",
        "import os",
        "client.post('bad')",
        "print('bad')",
        'payload = {"field":"value"}',
        "rm -rf example",
        "SELECT * FROM example",
    ],
)
def test_existing_plain_text_restrictions_reject_prohibited_syntax(text):
    # Phase 2.1 already runs these guards at the typed contract stage.
    rejected(admit({**content_data(), "scenario_narrative": text}), "contract_invalid", "contract")


def test_reference_failure_precedes_the_final_content_gate(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid references reached the final content gate")

    monkeypatch.setattr(admission_module, "educational_copy", forbidden)
    rejected(
        admit({**content_data(), "context_variant": "unrequested"}),
        "context_variant_not_permitted",
        "references",
    )


def test_final_content_gate_cannot_turn_a_guard_failure_into_acceptance(monkeypatch):
    def restricted(text):
        raise ValueError("Sensitive internal guard detail")

    monkeypatch.setattr(admission_module, "educational_copy", restricted)
    result = rejected(admit(), "content_restricted", "content")
    assert "Sensitive" not in result.model_dump_json()


@pytest.mark.parametrize(
    "raw",
    [
        '{"sensitive-diagnostic-sentinel":1,"sensitive-diagnostic-sentinel":2}',
        '{"title":"sensitive-diagnostic-sentinel",',
        '{"private":"sensitive-diagnostic-sentinel"}',
        json.dumps({**content_data(), "context_variant": "sensitive-diagnostic-sentinel"}),
    ],
)
def test_rejections_never_echo_generated_values_keys_or_exception_details(raw):
    result = admit(raw=raw)
    assert isinstance(result, AdmissionRejected)
    encoded = result.model_dump_json()
    assert "sensitive-diagnostic-sentinel" not in encoded + repr(result)
    assert (
        not {"raw_json", "content", "traceback", "exception", "input"} & result.model_dump().keys()
    )
    assert "Traceback" not in encoded and "ValueError" not in encoded
    assert isinstance(result.code, AdmissionFailureCode)
    assert TypeAdapter(AdmissionResult).validate_json(encoded) == result
    with pytest.raises(ValidationError):
        result.message = "Changed."
