"""Provider-compatible string literals preserve strict domain validation; no network."""

import json
from copy import deepcopy

import httpx
import pytest
from pydantic import ValidationError

from app.ai.client import AITransportError
from app.ai.providers.gemini import _gemini_json_schema
from app.schemas.private_guides import GuideContent
from tests.integration.test_private_guides import content
from tests.unit.test_gemini_transport import request, response, transport


def test_actual_guide_schema_has_exact_singleton_enum_on_sdk_wire_without_mutation():
    schema = GuideContent.model_json_schema()
    original = deepcopy(schema)
    checked = request(capability="generation", output_schema_json=json.dumps(schema))
    original_request = checked.model_dump_json()
    calls = []

    def handle(wire):
        calls.append(wire)
        sent = json.loads(wire.content)["generationConfig"]["responseJsonSchema"]
        version = sent["properties"]["schema_version"]
        assert version["enum"] == ["private-learning-guide-v1"]
        assert "const" not in version
        assert sent["required"] == schema["required"]
        assert sent["additionalProperties"] is False
        assert sent["$defs"] == schema["$defs"]
        return httpx.Response(
            200,
            json=response(
                candidates=[
                    {
                        "content": {"role": "model", "parts": [{"text": json.dumps(content())}]},
                        "finishReason": "STOP",
                    }
                ]
            ),
        )

    adapter = transport(handle)
    try:
        result = adapter.complete(checked)
        assert GuideContent.model_validate_json(result.text).schema_version == (
            "private-learning-guide-v1"
        )
        assert len(calls) == 1
        assert schema == original
        assert checked.model_dump_json() == original_request
    finally:
        adapter.close()


def test_nested_schema_nodes_keep_named_const_fields_annotations_and_all_other_constraints():
    schema = {
        "type": "object",
        "properties": {
            "const": {
                "type": "string",
                "const": "a-field-named-const",
                "minLength": 2,
                "pattern": "^a",
                "description": "An ordinary field name.",
                "default": {"const": "annotation-data"},
            },
            "nested": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {"anyOf": [{"type": "string", "const": "item"}, {"type": "null"}]},
                "prefixItems": [{"type": "string", "const": "first"}],
            },
        },
        "$defs": {"fixed": {"type": "string", "const": "v", "enum": ["v", "other"]}},
        "additionalProperties": {"type": "string", "const": "additional"},
        "required": ["const", "nested"],
        "examples": [{"const": "example-data"}],
    }
    original = deepcopy(schema)
    changed = _gemini_json_schema(schema)
    expected = deepcopy(schema)
    field = expected["properties"]["const"]
    field["enum"] = [field.pop("const")]
    item = expected["properties"]["nested"]["items"]["anyOf"][0]
    item["enum"] = [item.pop("const")]
    prefix = expected["properties"]["nested"]["prefixItems"][0]
    prefix["enum"] = [prefix.pop("const")]
    definition = expected["$defs"]["fixed"]
    definition["enum"] = [definition.pop("const")]
    additional = expected["additionalProperties"]
    additional["enum"] = [additional.pop("const")]
    assert changed == expected
    assert schema == original


def test_schema_lists_and_boolean_subschemas_are_cloned_without_promoting_annotations():
    schema = {
        "type": "array",
        "items": [{"type": "string", "const": "tuple-item"}, False],
        "allOf": [{"oneOf": [{"const": "branch"}, True]}],
        "additionalProperties": False,
        "description": "const is a keyword only inside a schema node",
    }
    changed = _gemini_json_schema(schema)
    assert changed["items"] == [{"type": "string", "enum": ["tuple-item"]}, False]
    assert changed["allOf"] == [{"oneOf": [{"enum": ["branch"]}, True]}]
    assert changed["additionalProperties"] is False
    assert schema["items"][0]["const"] == "tuple-item"


@pytest.mark.parametrize("constant", [True, False, 1, 0, None, {}, []])
def test_unsupported_nonstring_constants_are_rejected_before_any_http_call(constant):
    calls = []
    adapter = transport(lambda wire: calls.append(wire) or httpx.Response(200, json=response()))
    try:
        with pytest.raises(AITransportError) as error:
            adapter.complete(request(output_schema_json=json.dumps({"const": constant})))
        assert error.value.code == "invalid_request"
        assert not calls
    finally:
        adapter.close()


@pytest.mark.parametrize("existing", [["another"], [], "fixed"])
def test_contradictory_or_invalid_enums_are_not_weakened(existing):
    calls = []
    adapter = transport(lambda wire: calls.append(wire) or httpx.Response(200, json=response()))
    schema = {"type": "string", "const": "fixed", "enum": existing}
    try:
        with pytest.raises(AITransportError) as error:
            adapter.complete(request(output_schema_json=json.dumps(schema)))
        assert error.value.code == "invalid_request"
        assert not calls
        assert schema["const"] == "fixed"
    finally:
        adapter.close()


def test_wire_normalization_does_not_accept_an_incorrect_domain_specification_literal():
    wrong = content() | {"schema_version": "private_learning_guide_v1"}
    with pytest.raises(ValidationError) as error:
        GuideContent.model_validate(wrong)
    assert any(
        item["loc"] == ("schema_version",) and item["type"] == "literal_error"
        for item in error.value.errors()
    )


def test_normalized_schema_preserves_the_existing_byte_ceiling():
    with pytest.raises(AITransportError) as error:
        _gemini_json_schema({"type": "string", "const": "value", "title": "x" * 65536})
    assert error.value.code == "request_too_large"
