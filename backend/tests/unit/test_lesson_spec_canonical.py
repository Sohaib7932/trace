"""Canonicalization against explicit test-only design examples, never registration."""

import hashlib
import json
from copy import deepcopy
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain.lesson_spec import MAX_DEFINITION_BYTES, validate_lesson_spec
from app.domain.lesson_spec import canonical as canonical_module
from app.domain.lesson_spec.canonical import (
    calculate_digest,
    canonical_bytes,
    finalize_definition,
    verify_digest,
)
from tests.generation_fixtures import reference_definition


@pytest.fixture(params=["notes-v1", "tasks-nested-v1"])
def definition_data(request):
    return reference_definition(request.param)


def reverse_objects(value):
    if isinstance(value, dict):
        return {key: reverse_objects(child) for key, child in reversed(value.items())}
    if isinstance(value, list):
        return [reverse_objects(child) for child in value]
    return value


def test_identical_validated_definitions_have_identical_canonical_bytes(definition_data):
    first = validate_lesson_spec(definition_data)
    second = validate_lesson_spec(json.dumps(definition_data).encode("utf-8"))
    assert canonical_bytes(first) == canonical_bytes(second)
    assert calculate_digest(first) == calculate_digest(second)
    assert canonical_bytes(first) == json.dumps(
        definition_data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def test_object_insertion_order_never_changes_bytes_or_digest(definition_data):
    original = validate_lesson_spec(definition_data)
    reordered = validate_lesson_spec(reverse_objects(definition_data))
    assert canonical_bytes(original) == canonical_bytes(reordered)
    assert calculate_digest(original) == calculate_digest(reordered)


def test_arrays_are_not_sorted_or_reordered(definition_data):
    original = validate_lesson_spec(definition_data)
    definition_data["hints"].reverse()
    reversed_hints = validate_lesson_spec(definition_data)
    encoded = json.loads(canonical_bytes(reversed_hints))
    assert [hint["id"] for hint in encoded["hints"]] == ["hint-3", "hint-2", "hint-1"]
    assert calculate_digest(reversed_hints) != calculate_digest(original)


def test_non_ascii_authored_text_is_utf8_and_preserved_exactly(definition_data):
    text = "  Café — தமிழ்\nKeep both spaces.  "
    definition_data["scenario"]["context"] = text
    definition = validate_lesson_spec(definition_data)
    raw = canonical_bytes(definition)
    assert "Café — தமிழ்".encode() in raw
    assert b"\\u00e9" not in raw
    assert json.loads(raw)["scenario"]["context"] == text
    assert definition.scenario.context == text


def test_unicode_normalization_is_not_performed(definition_data):
    definition_data["summary"] = "Café"
    composed = validate_lesson_spec(definition_data)
    definition_data["summary"] = "Cafe\u0301"
    decomposed = validate_lesson_spec(definition_data)
    assert calculate_digest(composed) != calculate_digest(decomposed)


def test_digest_excludes_only_the_root_digest(definition_data):
    original = validate_lesson_spec(definition_data)
    payload = deepcopy(definition_data)
    del payload["content_sha256"]
    expected = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    assert canonical_bytes(original, include_digest=False) == expected
    assert calculate_digest(original) == hashlib.sha256(expected).hexdigest()
    assert b'"private":' in expected
    if original.entry_mode == "catalog":
        # The nested pinned transfer digest is included; only the root is removed.
        assert b'"content_sha256":' in expected
    definition_data["content_sha256"] = "f" * 64
    other = validate_lesson_spec(definition_data)
    assert canonical_bytes(other) != canonical_bytes(original)
    assert calculate_digest(other) == calculate_digest(original)


@pytest.mark.parametrize("field", ["title", "summary"])
def test_educational_copy_changes_the_digest(definition_data, field):
    original = validate_lesson_spec(definition_data)
    definition_data[field] += " Revised"
    assert calculate_digest(validate_lesson_spec(definition_data)) != calculate_digest(original)


def test_private_evaluation_array_order_is_covered_by_the_digest(definition_data):
    original = validate_lesson_spec(definition_data)
    rule = next(
        value
        for value in definition_data["private"]["evaluation"]["rules"].values()
        if value["kind"] == "field_trace"
    )
    rule["required_artifact_ids"].reverse()
    changed = validate_lesson_spec(definition_data)
    assert calculate_digest(changed) != calculate_digest(original)


def test_private_verification_configuration_is_covered_by_the_digest(definition_data):
    original = validate_lesson_spec(definition_data)
    current = definition_data["private"]["verification"]["timeout_seconds"]
    definition_data["private"]["verification"]["timeout_seconds"] = 1 if current != 1 else 2
    assert calculate_digest(validate_lesson_spec(definition_data)) != calculate_digest(original)


@pytest.mark.parametrize(
    "field,value",
    [
        ("lesson_id", "test-only-canonical-lesson"),
        ("version_id", "10000000-0000-4000-8000-000000000001"),
        ("version", "2.3.0"),
    ],
)
def test_server_identity_and_version_are_covered_by_the_digest(definition_data, field, value):
    original = validate_lesson_spec(definition_data)
    definition_data[field] = value
    assert calculate_digest(validate_lesson_spec(definition_data)) != calculate_digest(original)


def test_finalization_replaces_untrusted_digest_and_is_idempotent(definition_data):
    incoming = deepcopy(definition_data)
    incoming["content_sha256"] = "0" * 64
    before = deepcopy(incoming)
    finalized = finalize_definition(incoming)
    assert incoming == before
    assert finalized.content_sha256 != "0" * 64
    assert len(finalized.content_sha256) == 64
    assert finalized.content_sha256 == finalized.content_sha256.lower()
    assert verify_digest(finalized)
    assert validate_lesson_spec(canonical_bytes(finalized)) == finalized
    assert finalize_definition(finalized) == finalized
    assert canonical_bytes(finalize_definition(canonical_bytes(finalized))) == canonical_bytes(
        finalized
    )


def test_stale_supplied_digest_is_detected(definition_data):
    finalized = finalize_definition(definition_data)
    altered = finalized.model_dump(mode="json")
    altered["summary"] += " Revised"
    stale = validate_lesson_spec(altered)
    assert not verify_digest(stale)
    assert verify_digest(finalize_definition(stale))


@pytest.mark.parametrize("digest", [None, "not-a-digest", "A" * 64, "f" * 63])
def test_finalization_still_requires_a_complete_strict_definition(definition_data, digest):
    definition_data["content_sha256"] = digest
    with pytest.raises(ValueError):
        finalize_definition(definition_data)


def test_complete_definition_budget_is_enforced(definition_data):
    # Explanation count is not separately limited; use unique, strictly valid
    # core explanation IDs to exceed the complete document budget.
    explanation = definition_data["explanations"][0]
    definition_data["explanations"] += [
        {**explanation, "id": f"oversized-copy-{index}", "text": "x" * 4000} for index in range(20)
    ]
    with pytest.raises(ValueError, match="65536"):
        finalize_definition(definition_data)
    assert len(json.dumps(definition_data).encode("utf-8")) > MAX_DEFINITION_BYTES


@pytest.mark.parametrize(
    "value", [1.0, float("nan"), float("inf"), Decimal("1"), b"copy", {"copy"}, object()]
)
def test_unsupported_json_values_fail_before_serialization(definition_data, value):
    definition_data["summary"] = value
    with pytest.raises(ValueError):
        finalize_definition(definition_data)


@pytest.mark.parametrize("value", [None, {}, [], "{}", 1, True])
def test_canonical_bytes_requires_a_validated_definition(value):
    with pytest.raises(ValueError):
        canonical_bytes(value)


@pytest.mark.parametrize("value", [None, 0, 1, "false"])
def test_canonical_digest_selection_is_a_real_boolean(definition_data, value):
    definition = validate_lesson_spec(definition_data)
    with pytest.raises(ValueError, match="boolean"):
        canonical_bytes(definition, include_digest=value)


@pytest.mark.parametrize("value", ["\ud800", b"\xff"])
def test_invalid_utf8_is_rejected(definition_data, value):
    if isinstance(value, str):
        definition_data["summary"] = value
        raw = json.dumps(definition_data)
    else:
        raw = value
    with pytest.raises(ValueError):
        finalize_definition(raw)


def test_duplicate_raw_json_properties_are_not_erased_during_finalization(definition_data):
    raw = json.dumps(definition_data)
    duplicate = raw[:-1] + ',"title":"duplicate"}'
    with pytest.raises(ValueError, match="Duplicate"):
        finalize_definition(duplicate)


def test_serialization_failures_fail_closed(definition_data, monkeypatch):
    definition = validate_lesson_spec(definition_data)

    def broken(*args, **kwargs):
        raise TypeError("Internal serializer failure")

    monkeypatch.setattr(canonical_module.json, "dumps", broken)
    with pytest.raises(ValueError, match="canonical serialization"):
        canonical_bytes(definition)


def test_finalized_models_keep_existing_immutability(definition_data):
    finalized = finalize_definition(definition_data)
    with pytest.raises(ValidationError):
        finalized.content_sha256 = "f" * 64
    with pytest.raises(TypeError):
        finalized.private.evaluation.rules["extra"] = next(
            iter(finalized.private.evaluation.rules.values())
        )
