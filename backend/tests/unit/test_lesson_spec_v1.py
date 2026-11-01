"""Pure specification tests using the unchanged design examples as reference data."""

import json
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.lesson_spec import (
    MAX_DEFINITION_BYTES,
    LessonSpecV1,
    initial_learner_projection,
    validate_lesson_spec,
)
from app.domain.lesson_spec.fields import (
    ChoiceRule,
    InvestigationCheckpoint,
    ModificationCheckpoint,
    PredictionCheckpoint,
    RetrievalCheckpoint,
    TransferCheckpoint,
    VerificationCheckpoint,
)

EXAMPLES = (
    Path(__file__).resolve().parents[3] / "docs/architecture/examples/lesson-specification-v1.json"
)
REFERENCE = json.loads(EXAMPLES.read_text(encoding="utf-8"))
NOTES, TASKS = REFERENCE["lesson_versions"]


@pytest.fixture(params=[NOTES, TASKS], ids=["notes", "transfer-only-tasks"])
def definition(request):
    return deepcopy(request.param)


@pytest.mark.parametrize("as_json", [False, True])
def test_reference_definitions_validate_and_roundtrip_without_normalization(definition, as_json):
    incoming = json.dumps(definition).encode("utf-8") if as_json else definition
    result = validate_lesson_spec(incoming)
    assert isinstance(result, LessonSpecV1)
    assert result.model_dump(mode="json") == definition
    assert validate_lesson_spec(result.model_dump_json()) == result
    for cp, kind in zip(
        result.checkpoints[:4],
        [
            PredictionCheckpoint,
            InvestigationCheckpoint,
            ModificationCheckpoint,
            VerificationCheckpoint,
        ],
        strict=True,
    ):
        assert isinstance(cp, kind)


def test_reference_transfer_target_matches_the_separate_definition():
    parent, child = map(validate_lesson_spec, [NOTES, TASKS])
    transfer = parent.checkpoints[4]
    assert isinstance(transfer, TransferCheckpoint)
    assert child.entry_mode == "transfer_only" and len(child.checkpoints) == 4
    assert transfer.target_version.model_dump() == {
        name: child.model_dump()[name]
        for name in ["lesson_id", "version_id", "version", "content_sha256"]
    }


def test_attempt_example_references_match_the_typed_definitions():
    """Check reference consistency, without implementing an attempt interpreter."""
    journal = json.loads(EXAMPLES.with_name("lesson-attempt-v1.json").read_text())
    definitions = {model.version_id: model for model in map(validate_lesson_spec, [NOTES, TASKS])}
    sessions = {row["id"]: row for row in journal["sessions"]}
    runs = {row["id"]: row for row in journal["verification_runs"]}
    attempts = {row["id"]: row for row in journal["modification_attempts"]}

    def checkpoint(session_id, checkpoint_id, kind):
        model = definitions[sessions[session_id]["lesson_version_id"]]
        cp = next(cp for cp in model.checkpoints if cp.id == checkpoint_id)
        assert isinstance(cp, kind)
        return model, cp

    for row in sessions.values():
        model = definitions[row["lesson_version_id"]]
        assert (row["lesson_id"], row["version"], row["definition_digest"]) == (
            model.lesson_id,
            model.version,
            model.content_sha256,
        )
        assert row["learner_id"] == journal["learner_id"]
    for row in journal["predictions"]:
        _, cp = checkpoint(row["session_id"], row["checkpoint_id"], PredictionCheckpoint)
        assert row["selected_answer"] in {choice.id for choice in cp.choices}
    for row in attempts.values():
        _, cp = checkpoint(row["session_id"], row["checkpoint_id"], ModificationCheckpoint)
        assert row["change_type"] == cp.change_type
        assert row["field_name"] in {choice.id for choice in cp.choices}
    for row in runs.values():
        model = definitions[row["lesson_version_id"]]
        assert (
            sessions[row["source_context"]["session_id"]]["lesson_version_id"] == model.version_id
        )
        assert row["runtime_binding"] == model.private.runtime_binding.model_dump(mode="json")
        profile = getattr(model.private.verification.profiles, row["profile_id"])
        assert row["purpose"] == profile.purpose
        assert {check["code"] for check in row["checks"]} == set(profile.required_checks)
        if row["purpose"] == "baseline":
            assert row["attempt_id"] is None
            assert row["input_mapping"] == model.private.verification.fixture.initial_mapping
        else:
            assert attempts[row["attempt_id"]]["field_name"] == row["input_mapping"]
    for row in journal["investigation_responses"]:
        model, cp = checkpoint(row["session_id"], row["checkpoint_id"], InvestigationCheckpoint)
        rule = model.private.evaluation.rules[cp.evaluation_rule_id]
        assert (row["outgoing_field"], row["required_path"]) == (
            rule.expected_outgoing_field,
            rule.expected_required_path,
        )
        assert runs[row["baseline_run_id"]]["purpose"] == "baseline"
        artifacts = {artifact.id: artifact for artifact in model.scenario.artifacts}
        assert {item["artifact_id"] for item in row["annotations"]} == set(
            rule.required_artifact_ids
        )
        for annotation in row["annotations"]:
            reference = annotation["reference"]
            if reference["kind"] == "source_lines":
                assert (
                    1
                    <= reference["start_line"]
                    <= reference["end_line"]
                    <= len(artifacts[annotation["artifact_id"]].content.splitlines())
                )
            else:
                assert reference["run_id"] == row["baseline_run_id"]
    for row in journal["transfer_links"]:
        _, cp = checkpoint(row["parent_session_id"], row["checkpoint_id"], TransferCheckpoint)
        assert (
            cp.target_version.version_id
            == row["target_version_id"]
            == sessions[row["child_session_id"]]["lesson_version_id"]
        )
    for row in journal["retrieval_checkpoints"]:
        model, cp = checkpoint(row["parent_session_id"], row["checkpoint_id"], RetrievalCheckpoint)
        assert model.version_id == row["definition_version_id"]
        assert (cp.ordinal, cp.question.id) == (row["ordinal"], row["question_id"])
        anchor = datetime.fromisoformat(sessions[row["transfer_session_id"]]["completed_at"])
        assert datetime.fromisoformat(row["due_at"]) == anchor + timedelta(
            days=cp.schedule.delay_days
        )


def test_documentation_bundle_is_not_a_definition():
    with pytest.raises(ValueError):
        validate_lesson_spec(REFERENCE)


def test_checkpoint_and_rule_schemas_are_discriminated_unions():
    schema = LessonSpecV1.model_json_schema()

    def resolve(value):
        return schema["$defs"][value["$ref"].rsplit("/", 1)[1]] if "$ref" in value else value

    checkpoints = resolve(resolve(schema["properties"]["checkpoints"])["items"])
    assert checkpoints["discriminator"]["propertyName"] == "type"
    assert set(checkpoints["discriminator"]["mapping"]) == {
        "prediction",
        "investigation",
        "modification",
        "verification",
        "transfer",
        "retrieval",
    }
    policy = schema["$defs"]["EvaluationPolicy"]
    rules = resolve(resolve(policy["properties"]["rules"])["additionalProperties"])
    assert rules["discriminator"]["propertyName"] == "kind"


def path_value(root, path):
    for key in path:
        root = root[key]
    return root


def changed(path, value, original=NOTES):
    result = deepcopy(original)
    path_value(result, path[:-1])[path[-1]] = value
    return result


OBJECT_PATHS = [
    (),
    ("objectives", 0),
    ("scenario",),
    ("scenario", "input_values"),
    ("scenario", "artifacts", 0),
    ("checkpoints", 0),
    ("checkpoints", 0, "choices", 0),
    ("checkpoints", 1),
    ("checkpoints", 2),
    ("checkpoints", 3),
    ("checkpoints", 4),
    ("checkpoints", 4, "target_version"),
    ("checkpoints", 5),
    ("checkpoints", 5, "schedule"),
    ("checkpoints", 5, "question"),
    ("checkpoints", 5, "question", "options", 0),
    ("hints", 0),
    ("explanations", 0),
    ("misconceptions", 0),
    ("misconceptions", 0, "indicator"),
    ("completion_policy",),
    ("tutor_policy",),
    ("private",),
    ("private", "runtime_binding"),
    ("private", "evaluation"),
    ("private", "verification"),
    ("private", "verification", "fixture"),
    ("private", "verification", "profiles"),
    ("private", "verification", "profiles", "initial_failure"),
    ("private", "verification", "profiles", "initial_failure", "stored_values"),
    ("private", "verification", "profiles", "repair"),
    ("private", "verification", "profiles", "repair", "stored_values"),
]
OBJECT_PATHS += [
    ("private", "evaluation", "rules", key) for key in NOTES["private"]["evaluation"]["rules"]
]
REQUIRED_FIELDS = [(path, key) for path in OBJECT_PATHS for key in path_value(NOTES, path)]


@pytest.mark.parametrize("path", OBJECT_PATHS)
def test_unknown_fields_rejected_at_every_definition_object(path):
    document = deepcopy(NOTES)
    path_value(document, path)["unexpected"] = "Never executable"
    with pytest.raises(ValueError):
        validate_lesson_spec(document)


@pytest.mark.parametrize("path,key", REQUIRED_FIELDS)
def test_required_fields_cannot_be_omitted(path, key):
    document = deepcopy(NOTES)
    del path_value(document, path)[key]
    with pytest.raises(ValueError):
        validate_lesson_spec(document)


@pytest.mark.parametrize(
    "path,value",
    [
        (("lesson_id",), "Bad Slug"),
        (("lesson_id",), "../lesson"),
        (("lesson_id",), "a" * 81),
        (("version",), "2.0"),
        (("version",), "v2.0.0"),
        (("version",), "2.0.0-beta"),
        (("version",), "01.0.0"),
        (("version",), 2),
        (("version",), "1" * 33 + ".0.0"),
        (("spec_version",), "2.0.0"),
        (("version_id",), "AAAAAAAA-0000-4000-8000-000000000001"),
        (("version_id",), "10000000000040008000000000000065"),
        (("version_id",), "not-a-uuid"),
        (("content_sha256",), "A" * 64),
        (("content_sha256",), "a" * 63),
        (("objectives", 0, "id"), "server_error"),
        (("checkpoints", 4, "target_version", "version"), "latest"),
        (("checkpoints", 4, "target_version", "version_id"), "bad"),
        (("checkpoints", 4, "target_version", "content_sha256"), "g" * 64),
    ],
)
def test_identifiers_are_strict_and_bounded(path, value):
    with pytest.raises(ValueError):
        validate_lesson_spec(changed(path, value))


@pytest.mark.parametrize(
    "collection", ["objectives", "checkpoints", "hints", "explanations", "misconceptions"]
)
def test_duplicate_ids_rejected(collection):
    document = deepcopy(NOTES)
    if len(document[collection]) > 1:
        document[collection][1]["id"] = document[collection][0]["id"]
    else:
        document[collection].append(deepcopy(document[collection][0]))
    with pytest.raises(ValueError):
        validate_lesson_spec(document)


@pytest.mark.parametrize(
    "path,value",
    [
        (("scenario", "artifacts", 1, "id"), "request-builder"),
        (("checkpoints", 0, "choices", 1, "id"), "rejected"),
        (("checkpoints", 2, "choices", 1, "id"), "body"),
        (("checkpoints", 6, "question", "id"), "shipping-contract-v1"),
        (("checkpoints", 5, "question", "options", 1, "id"), "a"),
        (("hints", 1, "level"), 1),
        (("checkpoints", 1, "objective_ids"), ["trace-contract", "trace-contract"]),
        (("checkpoints", 1, "hint_ids"), ["hint-1", "hint-1"]),
    ],
)
def test_nested_duplicate_ids_and_references_rejected(path, value):
    with pytest.raises(ValueError):
        validate_lesson_spec(changed(path, value))


@pytest.mark.parametrize(
    "path,value",
    [
        (("checkpoints", 1, "depends_on"), []),
        (("checkpoints", 0, "depends_on"), ["verify-note"]),
        (("checkpoints", 6, "depends_on"), ["revisit-day-1"]),
        (("checkpoints", 1, "objective_ids"), ["missing"]),
        (("objectives", 0, "evidence_checkpoint_ids"), ["missing"]),
        (("checkpoints", 1, "hint_ids"), ["missing"]),
        (("hints", 0, "checkpoint_ids"), ["missing"]),
        (("hints", 0, "checkpoint_ids"), ["predict-note"]),
        (("hints", 0, "checkpoint_ids"), ["modify-note"]),
        (("checkpoints", 1, "artifact_ids"), ["request-builder", "missing"]),
        (("checkpoints", 1, "baseline_evidence_artifact_id"), "request-builder"),
        (("checkpoints", 3, "modification_checkpoint_id"), "predict-note"),
        (("checkpoints", 2, "evaluation_rule_id"), "prediction"),
        (("checkpoints", 5, "schedule", "anchor_checkpoint_id"), "verify-note"),
        (("checkpoints", 6, "ordinal"), 1),
        (("checkpoints", 6, "schedule", "delay_days"), 1),
        (("tutor_policy", "available_after_checkpoint_id"), "modify-note"),
        (("completion_policy", "core_checkpoint_ids"), ["predict-note"] * 4),
        (("completion_policy", "transfer_checkpoint_ids"), []),
        (("completion_policy", "retrieval_checkpoint_ids"), ["revisit-day-7", "revisit-day-1"]),
        (("explanations", 0, "checkpoint_id"), "missing"),
        (("explanations", 0, "checkpoint_id"), "modify-note"),
        (("explanations", 1, "checkpoint_id"), "verify-note"),
        (("misconceptions", 0, "indicator", "checkpoint_id"), "predict-note"),
        (("misconceptions", 0, "indicator", "value"), "flat"),
        (("private", "evaluation", "rules", "retrieval-1", "answer"), "missing"),
        (("private", "evaluation", "rules", "retrieval-1", "explanation_id"), "core-explanation"),
        (
            ("private", "evaluation", "rules", "retrieval-1", "explanation_id"),
            "retrieval-2-explanation",
        ),
    ],
)
def test_reference_and_policy_integrity(path, value):
    with pytest.raises(ValueError):
        validate_lesson_spec(changed(path, value))


@pytest.mark.parametrize(
    "operation",
    [
        "swap",
        "missing",
        "extra",
        "nested-transfer",
        "self-slug",
        "self-version",
        "rule-kind",
        "unused-rule",
    ],
)
def test_topology_and_rule_binding(operation):
    document = deepcopy(NOTES)
    if operation == "swap":
        document["checkpoints"][0:2] = reversed(document["checkpoints"][0:2])
    elif operation == "missing":
        document["checkpoints"].pop()
    elif operation == "extra":
        document["checkpoints"].append(deepcopy(document["checkpoints"][0]))
    elif operation == "nested-transfer":
        document["entry_mode"] = "transfer_only"
    elif operation == "self-slug":
        document["checkpoints"][4]["target_version"]["lesson_id"] = document["lesson_id"]
    elif operation == "self-version":
        document["checkpoints"][4]["target_version"]["version_id"] = document["version_id"]
    elif operation == "rule-kind":
        document["private"]["evaluation"]["rules"]["prediction"] = {"kind": "verified_repair"}
    else:
        document["private"]["evaluation"]["rules"]["extra"] = {"kind": "verified_repair"}
    with pytest.raises(ValueError):
        validate_lesson_spec(document)


@pytest.mark.parametrize(
    "path,value",
    [
        (("checkpoints", 0, "type"), "execute_python"),
        (("private", "evaluation", "rules", "prediction", "kind"), "expression"),
        (("private", "runtime_binding", "template_id"), "uploaded-python"),
        (("private", "runtime_binding", "revision"), "1.0.1"),
        (("private", "evaluation", "policy_id"), "custom-evaluator"),
        (("private", "evaluation", "revision"), "1.0.1"),
        (("private", "evaluation", "rules", "prediction", "answer"), "saved"),
        (("private", "evaluation", "rules", "prediction", "gate"), "correct_answer"),
        (
            ("private", "evaluation", "rules", "investigation", "expected_required_path"),
            "/metadata/priority",
        ),
        (
            ("private", "evaluation", "rules", "investigation", "required_artifact_ids"),
            ["request-builder", "receiver-schema", "missing"],
        ),
        (("private", "evaluation", "rules", "modification", "correct_value"), "body"),
        (("private", "evaluation", "rules", "modification", "allowed_values"), ["body", "flat"]),
        (("private", "verification", "fixture", "id"), "empty-tasks-v1"),
        (("private", "verification", "fixture", "initial_mapping"), "content"),
        (("scenario", "input_values", "content"), "Creator override"),
        (("scenario", "artifacts", 0, "content"), "print('arbitrary program')"),
        (("scenario", "artifacts", 1, "content"), "class NoteCreate: pass"),
        (("scenario", "artifacts", 0, "language"), "javascript"),
        (("checkpoints", 2, "change_type"), "nest_payload_field"),
        (("checkpoints", 1, "baseline_profile_id"), "repair"),
        (("checkpoints", 3, "profile_id"), "initial_failure"),
        (("private", "verification", "profiles", "initial_failure", "http_status"), 201),
        (
            ("private", "verification", "profiles", "initial_failure", "validation_codes"),
            ["missing:metadata", "extra_forbidden:priority"],
        ),
        (("private", "verification", "profiles", "repair", "response_shape"), "saved_task"),
        (
            ("private", "verification", "profiles", "repair", "stored_values", "content"),
            "Wrong value",
        ),
        (("private", "verification", "profiles", "repair", "row_count"), 0),
        (
            (
                "private",
                "verification",
                "profiles",
                "repair",
                "require_response_row_identity_match",
            ),
            False,
        ),
        (("private", "verification", "timeout_seconds"), 11),
        (("private", "verification", "timeout_seconds"), 0),
    ],
)
def test_technical_configuration_is_owned_by_supported_templates(path, value):
    with pytest.raises(ValueError):
        validate_lesson_spec(changed(path, value))


@pytest.mark.parametrize("profile", ["initial_failure", "repair"])
@pytest.mark.parametrize(
    "checks",
    [
        [],
        ["http_status"] * 5,
        ["http_status", "api_response", "validation", "row_count"],
        ["http_status", "api_response", "validation", "row_count", "invented"],
    ],
)
def test_five_verification_checks_cannot_be_removed_or_replaced(profile, checks):
    with pytest.raises(ValueError):
        validate_lesson_spec(
            changed(("private", "verification", "profiles", profile, "required_checks"), checks)
        )


@pytest.mark.parametrize(
    "path,value",
    [
        (("checkpoints", 0, "reasoning_required"), 1),
        (("checkpoints", 2, "explanation_required"), 0),
        (("checkpoints", 5, "ordinal"), True),
        (("checkpoints", 5, "schedule", "delay_days"), True),
        (("private", "verification", "profiles", "initial_failure", "row_count"), False),
        (
            (
                "private",
                "verification",
                "profiles",
                "repair",
                "require_response_row_identity_match",
            ),
            1,
        ),
        (("hints", 0, "level"), True),
        (("hints", 0, "level"), "1"),
        (("tutor_policy", "max_requests_per_core_session"), "3"),
        (("private", "verification", "timeout_seconds"), "10"),
        (("private", "verification", "timeout_seconds"), 10.0),
        (("checkpoints", 5, "question", "payload"), {"value": 1.0}),
    ],
)
def test_types_are_not_coerced(path, value):
    with pytest.raises(ValueError):
        validate_lesson_spec(changed(path, value))


@pytest.mark.parametrize(
    "text",
    [
        "",
        " \n\t",
        "<script>alert(1)</script>",
        '<img src="x">',
        "https://example.test",
        "javascript:alert(1)",
        "bad\x00text",
    ],
)
def test_plain_text_is_required_without_html_urls_or_controls(text):
    with pytest.raises(ValueError):
        validate_lesson_spec(changed(("summary",), text))


@pytest.mark.parametrize(
    "path,limit",
    [
        (("title",), 120),
        (("summary",), 600),
        (("hints", 0, "text"), 4000),
        (("checkpoints", 5, "question", "schema_code"), 8000),
    ],
)
def test_text_limits(path, limit):
    with pytest.raises(ValidationError) as failure:
        validate_lesson_spec(changed(path, "x" * (limit + 1)))
    assert any(error["type"] == "string_too_long" for error in failure.value.errors())
    text = "x" * limit
    if path[-1] == "schema_code":
        original = path_value(NOTES, path)
        text = original + "\n#" + "x" * (limit - len(original) - 2)
    assert (
        path_value(validate_lesson_spec(changed(path, text)).model_dump(mode="json"), path) == text
    )


@pytest.mark.parametrize(
    "path,count",
    [
        (("objectives",), 0),
        (("objectives",), 4),
        (("hints",), 4),
        (("misconceptions",), 9),
        (("scenario", "artifacts"), 1),
        (("scenario", "artifacts"), 3),
        (("checkpoints", 0, "choices"), 2),
        (("checkpoints", 2, "choices"), 3),
        (("checkpoints", 5, "question", "options"), 4),
    ],
)
def test_collection_cardinality_limits(path, count):
    original = path_value(NOTES, path)
    values = [deepcopy(original[index % len(original)]) for index in range(count)]
    for index, item in enumerate(values):
        if path != ("checkpoints", 0, "choices"):
            item["id"] = f"item-{index}"
    with pytest.raises(ValidationError) as failure:
        validate_lesson_spec(changed(path, values))
    assert any(error["type"] in {"too_short", "too_long"} for error in failure.value.errors())


def test_transfer_only_can_have_no_optional_guidance_or_explanations():
    document = deepcopy(TASKS)
    document["hints"] = document["explanations"] = document["misconceptions"] = []
    for cp in document["checkpoints"]:
        cp["hint_ids"] = []
    assert validate_lesson_spec(document).hints == ()


def test_reference_integrity_does_not_require_objectives_to_claim_prediction_as_evidence():
    document = deepcopy(NOTES)
    document["objectives"].append(
        {
            "id": "second-goal",
            "statement": "Observe a committed save.",
            "evidence_checkpoint_ids": ["verify-note"],
        }
    )
    with pytest.raises(ValueError, match="same objective"):
        validate_lesson_spec(document)
    document["checkpoints"][3]["objective_ids"].append("second-goal")
    assert len(validate_lesson_spec(document).objectives) == 2


def test_template_families_cannot_be_swapped_by_changing_only_the_binding(definition):
    binding = definition["private"]["runtime_binding"]
    binding["template_id"] = (
        "tasks-nested-v1" if binding["template_id"] == "notes-v1" else "notes-v1"
    )
    with pytest.raises(ValueError, match="template"):
        validate_lesson_spec(definition)


def test_wire_byte_limit_is_utf8_and_checked_before_parsing():
    raw = json.dumps(NOTES, ensure_ascii=False)
    exact = raw + " " * (MAX_DEFINITION_BYTES - len(raw.encode("utf-8")))
    assert validate_lesson_spec(exact).lesson_id == NOTES["lesson_id"]
    with pytest.raises(ValueError, match="65536"):
        validate_lesson_spec(exact + " ")
    with pytest.raises(ValueError, match="65536"):
        validate_lesson_spec("é" * (MAX_DEFINITION_BYTES // 2 + 1))
    with pytest.raises(ValueError):
        validate_lesson_spec(b"\xff")


@pytest.mark.parametrize("suffix", ['"spec_version":"1.0.0"', '"private":{}'])
def test_duplicate_json_properties_are_rejected_even_with_identical_values(suffix):
    raw = json.dumps(NOTES)
    with pytest.raises(ValueError, match="Duplicate JSON"):
        validate_lesson_spec(raw[:-1] + "," + suffix + "}")


def test_duplicate_nested_json_properties_and_nonascii_keys_are_rejected():
    raw = json.dumps(NOTES).replace(
        '"timeout_seconds": 10', '"timeout_seconds": 10, "timeout_seconds": 10'
    )
    with pytest.raises(ValueError, match="Duplicate JSON"):
        validate_lesson_spec(raw)
    with pytest.raises(ValueError, match="ASCII"):
        validate_lesson_spec(changed(("checkpoints", 5, "question", "payload"), {"café": "value"}))


def test_object_byte_budget_applies_to_combined_bounded_fields():
    document = deepcopy(NOTES)
    # Individually bounded authored fields can still exceed the document budget.
    for index in range(18):
        document["explanations"].append(
            {
                "id": f"extra-{index}",
                "title": "More context",
                "text": "é" * 4000,
                "checkpoint_id": "verify-note",
                "release_event": "core_verification_passed",
            }
        )
    with pytest.raises(ValueError, match="65536"):
        validate_lesson_spec(document)


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1.0", "1e1"])
def test_noninteger_json_numbers_rejected(literal):
    raw = json.dumps(NOTES).replace('"timeout_seconds": 10', '"timeout_seconds": ' + literal)
    with pytest.raises(ValueError):
        validate_lesson_spec(raw)


@pytest.mark.parametrize(
    "schema",
    [
        "import os",
        "print('code')",
        "class Thing(BaseModel):\n    item: str = open('file')",
        "class Thing(BaseModel):\n    def run(self): pass",
        "@decorator\nclass Thing(BaseModel):\n    item: str",
        "class Thing(BaseModel):\n    item: factory()",
        "class Thing(BaseModel):\n    __class__: str",
    ],
)
def test_retrieval_schema_is_declarative_display_data_not_executable_content(schema):
    with pytest.raises(ValueError):
        validate_lesson_spec(changed(("checkpoints", 5, "question", "schema_code"), schema))


@pytest.mark.parametrize(
    "schema",
    [
        "class Thing(BaseModel):\n    items: list[str]\n    counts: dict[str, int]",
        "class Thing(BaseModel):\n    label: str | None\n    count: int\n"
        "    active: bool\n    ratio: float",
        "class Thing(BaseModel):\n    status: Literal[1, 2, 3]",
    ],
)
def test_declarative_display_schema_variants_are_accepted_without_execution(schema):
    result = validate_lesson_spec(changed(("checkpoints", 5, "question", "schema_code"), schema))
    assert result.model_dump(mode="json")["checkpoints"][5]["question"]["schema_code"] == schema


@pytest.mark.parametrize(
    "schema",
    [
        "class Broken(",
        "\n\n".join(f"class Thing{i}(BaseModel):\n    item: str" for i in range(9)),
        "class Thing(BaseModel):\n" + "\n".join(f"    item{i}: str" for i in range(33)),
        "class Thing(BaseModel):\n    item: str\n    item: int",
        "class Thing(BaseModel):\n    item: str\n\nclass Thing(BaseModel):\n    count: int",
        "class Thing(BaseModel, metaclass=object):\n    item: str",
        "class Thing(Other):\n    item: str",
        "class Thing(BaseModel):\n    item: Unknown",
        "class Thing(BaseModel):\n    item: list[str, int]",
        "class Thing(BaseModel):\n    item: dict[str]",
        "class Thing(BaseModel):\n    item: Literal[1.0]",
        "class Thing(BaseModel):\n    item: Literal[0,1,2,3,4,5,6,7,8]",
    ],
)
def test_display_schema_grammar_and_resource_limits(schema):
    with pytest.raises(ValueError):
        validate_lesson_spec(changed(("checkpoints", 5, "question", "schema_code"), schema))


def test_nested_json_is_bounded_and_immutable():
    payload = {"flag": True, "count": 1, "none": None, "nested": {"items": ["text", 2]}}
    result = validate_lesson_spec(changed(("checkpoints", 5, "question", "payload"), payload))
    cp = result.checkpoints[5]
    assert isinstance(cp, RetrievalCheckpoint)
    assert result.model_dump(mode="json")["checkpoints"][5]["question"]["payload"] == payload
    payload["nested"]["items"].append("Mutating input must not change the definition")
    assert result.model_dump(mode="json")["checkpoints"][5]["question"]["payload"]["nested"][
        "items"
    ] == ["text", 2]
    with pytest.raises(TypeError):
        cp.question.payload["injected"] = "bad"
    with pytest.raises(TypeError):
        cp.question.payload["nested"]["items"] = ()
    with pytest.raises(ValidationError):
        result.title = "Changed"
    with pytest.raises(TypeError):
        result.private.evaluation.rules["prediction"] = ChoiceRule(
            kind="single_choice", answer="a", explanation_id="x"
        )
    for _ in range(40):
        payload = {"nested": payload}
    with pytest.raises(ValueError, match="nesting"):
        validate_lesson_spec(changed(("checkpoints", 5, "question", "payload"), payload))


def test_unicode_and_digest_values_are_not_canonicalized_or_rehashed():
    document = changed(("title",), "Cafe\u0301")
    document["content_sha256"] = "0" * 64
    result = validate_lesson_spec(document)
    assert result.title == "Cafe\u0301"
    assert result.content_sha256 == "0" * 64


def test_initial_projection_cannot_serialize_private_or_unreleased_content(definition):
    definition["explanations"][0]["text"] = "PRIVATE EXPLANATION SENTINEL"
    definition["hints"][0]["text"] = "UNRELEASED HINT SENTINEL"
    result = validate_lesson_spec(definition)
    public = initial_learner_projection(result).model_dump(mode="json")
    assert set(public) == {
        "definition_format",
        "spec_version",
        "lesson_id",
        "version_id",
        "version",
        "title",
        "summary",
        "objectives",
        "scenario",
        "prediction",
    }
    forbidden = {
        "private",
        "answer",
        "content_sha256",
        "evaluation_rule_id",
        "target_version",
        "hints",
        "explanations",
        "misconceptions",
        "question",
    }

    def check(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(value)
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    check(public)
    encoded = json.dumps(public)
    assert "PRIVATE EXPLANATION SENTINEL" not in encoded
    assert "UNRELEASED HINT SENTINEL" not in encoded
    assert result.content_sha256 not in encoded
    assert "private" in result.model_dump(mode="json")  # Trusted serialization is separate.
    assert "PRIVATE EXPLANATION SENTINEL" not in repr(result)
    public_schema = type(initial_learner_projection(result)).model_json_schema()
    assert not {"PrivateDefinition", "ChoiceRule", "VerificationPolicy"}.intersection(
        public_schema.get("$defs", {})
    )
