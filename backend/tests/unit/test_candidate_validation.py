"""Candidate gate integrity, independent preservation and fail-closed outcomes.

Runtime-port fixtures here only exercise orchestration; the separate runtime
integration tests execute the real isolated Notes/Tasks applications.
"""

import pytest
from pydantic import ValidationError

from app.domain.lesson_spec import validate_lesson_spec
from app.domain.lesson_spec.canonical import canonical_bytes, finalize_definition
from app.schemas.candidate_validation import (
    CHECK_CODES,
    STAGES,
    CandidateValidationCode,
    CandidateValidationResult,
    RuntimeValidationReport,
)
from app.schemas.lesson_composition import CompositionIdentity, TrustedLessonBlueprint
from app.services.candidate_validation import CandidateValidationService
from tests.candidate_validation_fixtures import (
    candidate_payload,
    passing_runtime_report,
    validation_case,
)
from tests.composition_fixtures import blueprint

FAMILIES = ["notes-v1", "tasks-nested-v1"]
UNSET = object()


class ReportingRuntime:
    """Explicit deterministic server-port fixture, not an exercise implementation."""

    def __init__(self, report=None, *, error=None):
        self.report = passing_runtime_report() if report is None and error is None else report
        self.error = error
        self.definitions = []

    def validate(self, definition):
        self.definitions.append(definition)
        if self.error is not None:
            raise self.error
        return self.report


def check(case, *, candidate=UNSET, runtime=UNSET, **context):
    inputs = dict(case)
    if candidate is not UNSET:
        inputs["candidate"] = candidate
    inputs.update(context)
    executor = ReportingRuntime() if runtime is UNSET else runtime
    return CandidateValidationService(runtime=executor).validate(**inputs)


def failure(result, status, code, stage):
    assert result.status == status and result.code == code
    assert result.release_eligible is False
    assert tuple(item.stage for item in result.stages) == STAGES
    failed = next(item for item in result.stages if item.stage == stage)
    assert failed.code == code and failed.status in {"failed", "unavailable"}
    after = result.stages[STAGES.index(stage) + 1 :]
    assert all(item.status == "skipped" for item in after)
    assert 0 < len(result.summary) <= 200
    return result


def changed_definition(case, mutator):
    payload = case["candidate"].definition.model_dump(mode="json")
    mutator(payload)
    definition = finalize_definition(payload)
    candidate = candidate_payload(case["candidate"])
    candidate["definition"] = definition
    candidate["canonical_digest"] = definition.content_sha256
    candidate["canonical_definition_bytes"] = canonical_bytes(definition)
    return candidate


@pytest.mark.parametrize("family", FAMILIES)
def test_complete_matching_candidate_passes_gate_without_becoming_releasable(family):
    case = validation_case(family)
    runtime = ReportingRuntime()
    before = canonical_bytes(case["candidate"].definition)
    result = check(case, runtime=runtime)
    assert result.status == "validated" and result.code is None
    assert result.identity == case["identity"]
    assert result.content_sha256 == case["candidate"].canonical_digest
    assert result.runtime_verification_performed and result.runtime_verification_completed
    assert result.release_eligible is False and not hasattr(result, "published")
    assert [stage.status for stage in result.stages] == ["passed"] * 4
    assert {profile.profile for profile in result.runtime_evidence} == {"baseline", "repair"}
    assert all(
        {item.code for item in profile.checks} == CHECK_CODES for profile in result.runtime_evidence
    )
    assert runtime.definitions == [case["candidate"].definition]
    assert canonical_bytes(case["candidate"].definition) == before
    assert case["candidate"].state == "composed_unverified"
    assert case["candidate"].release_eligible is False


def test_strict_internal_payload_representation_revalidates_before_runtime():
    case = validation_case()
    result = check(case, candidate=candidate_payload(case["candidate"]))
    assert result.status == "validated" and result.release_eligible is False


@pytest.mark.parametrize("value", [None, [], "candidate", 1, True])
def test_untyped_invalid_inputs_return_safe_schema_failure(value):
    runtime = ReportingRuntime()
    result = check(validation_case(), candidate=value, runtime=runtime)
    failure(result, "invalid", "candidate_schema_invalid", "integrity")
    assert not runtime.definitions and not result.runtime_verification_performed


@pytest.mark.parametrize("state", [None, "published", "validated", True])
def test_incorrect_candidate_state_never_reaches_runtime(state):
    case = validation_case()
    data = candidate_payload(case["candidate"])
    data["state"] = state
    runtime = ReportingRuntime()
    failure(
        check(case, candidate=data, runtime=runtime),
        "invalid",
        "candidate_state_invalid",
        "integrity",
    )
    assert not runtime.definitions


def test_missing_candidate_state_is_not_inferred_from_defaults():
    case = validation_case()
    data = candidate_payload(case["candidate"])
    del data["state"]
    failure(check(case, candidate=data), "invalid", "candidate_state_invalid", "integrity")


@pytest.mark.parametrize("digest", [None, "", "not-a-digest", "A" * 64, "a" * 63, 1])
def test_missing_or_malformed_candidate_digest_is_rejected(digest):
    case = validation_case()
    data = candidate_payload(case["candidate"])
    data["canonical_digest"] = digest
    failure(check(case, candidate=data), "invalid", "candidate_digest_invalid", "integrity")


def test_missing_digest_property_is_rejected():
    case = validation_case()
    data = candidate_payload(case["candidate"])
    del data["canonical_digest"]
    failure(check(case, candidate=data), "invalid", "candidate_digest_invalid", "integrity")


def test_changed_educational_content_with_stale_digest_is_not_trusted():
    case = validation_case()
    payload = case["candidate"].definition.model_dump(mode="json")
    payload["title"] = "Changed copy with a stale digest"
    data = candidate_payload(case["candidate"])
    data["definition"] = validate_lesson_spec(payload)
    failure(check(case, candidate=data), "invalid", "candidate_digest_mismatch", "integrity")


def test_well_formed_but_wrong_supplied_digest_is_recomputed():
    case = validation_case()
    data = candidate_payload(case["candidate"])
    data["canonical_digest"] = "0" * 64
    failure(check(case, candidate=data), "invalid", "candidate_digest_mismatch", "integrity")


def test_canonical_definition_bytes_are_checked_against_the_definition():
    case = validation_case()
    data = candidate_payload(case["candidate"])
    data["canonical_definition_bytes"] += b" "
    failure(check(case, candidate=data), "invalid", "candidate_bytes_mismatch", "integrity")


@pytest.mark.parametrize(
    "field,value",
    [
        ("lesson_id", "different-server-reservation"),
        ("version_id", "30000000-0000-4000-8000-000000000099"),
        ("version", "9.0.0"),
    ],
)
def test_candidate_identity_must_equal_the_independent_server_reservation(field, value):
    case = validation_case()
    expected = case["identity"].model_dump(mode="json")
    expected[field] = value
    identity = CompositionIdentity.model_validate(expected)
    failure(check(case, identity=identity), "invalid", "candidate_identity_mismatch", "integrity")


@pytest.mark.parametrize(
    "kind", ["artifact", "checkpoint_dependency", "checkpoint_reference", "version"]
)
def test_authoritative_schema_rejects_invalid_components_relationships_and_versions(kind):
    case = validation_case()
    data = candidate_payload(case["candidate"])
    definition = case["candidate"].definition.model_dump(mode="json")
    if kind == "artifact":
        definition["checkpoints"][1]["artifact_ids"][0] = "missing-artifact"
    elif kind == "checkpoint_dependency":
        definition["checkpoints"][1]["depends_on"] = ["missing-checkpoint"]
    elif kind == "checkpoint_reference":
        definition["hints"][0]["checkpoint_ids"] = ["missing-checkpoint"]
    else:
        definition["spec_version"] = "2.0.0"
    data["definition"] = definition
    runtime = ReportingRuntime()
    result = check(case, candidate=data, runtime=runtime)
    failure(result, "invalid", "candidate_schema_invalid", "integrity")
    assert not runtime.definitions


def test_unknown_candidate_fields_are_not_silently_discarded():
    case = validation_case()
    data = candidate_payload(case["candidate"])
    data["private_extension"] = "Sensitive diagnostic sentinel"
    result = failure(
        check(case, candidate=data), "invalid", "candidate_schema_invalid", "integrity"
    )
    assert "Sensitive diagnostic sentinel" not in result.model_dump_json()


def test_missing_target_is_unavailable_even_when_composition_metadata_claims_verified():
    case = validation_case()
    assert case["candidate"].metadata.transfer_target_digest_status == "verified"
    runtime = ReportingRuntime()
    result = check(case, runtime=runtime, trusted_transfer_target=None)
    failure(result, "unavailable", "transfer_target_unavailable", "structure")
    assert not runtime.definitions and not result.runtime_verification_performed


def test_previously_unavailable_target_can_be_verified_when_its_definition_is_supplied():
    case = validation_case(with_target=False)
    assert case["candidate"].metadata.transfer_target_digest_status == "unavailable"
    result = check(case, trusted_transfer_target=blueprint("tasks-nested-v1"))
    assert result.status == "validated"
    assert case["candidate"].metadata.transfer_target_digest_status == "unavailable"


@pytest.mark.parametrize(
    "field,value",
    [
        ("lesson_id", "different-trusted-target"),
        ("version_id", "20000000-0000-4000-8000-000000000099"),
        ("version", "99.0.0"),
        ("title", "A changed trusted target has another digest"),
    ],
)
def test_exact_target_identity_version_and_digest_are_required(field, value):
    case = validation_case()
    target = case["trusted_transfer_target"]
    payload = target.definition.model_dump(mode="json")
    payload[field] = value
    target = TrustedLessonBlueprint(
        template_family="tasks-nested-v1", definition=finalize_definition(payload)
    )
    runtime = ReportingRuntime()
    failure(
        check(case, runtime=runtime, trusted_transfer_target=target),
        "invalid",
        "transfer_target_mismatch",
        "structure",
    )
    assert not runtime.definitions


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("context_variant", "not-requested-context", "composition_mismatch"),
        (
            "blueprint_id",
            "20000000-0000-4000-8000-000000000099",
            "candidate_metadata_mismatch",
        ),
    ],
)
def test_composition_metadata_is_bound_to_the_original_request_and_blueprint(field, value, code):
    case = validation_case()
    data = candidate_payload(case["candidate"])
    if field == "blueprint_id":
        data["metadata"]["blueprint"]["version_id"] = value
    else:
        data["metadata"][field] = value
    failure(check(case, candidate=data), "invalid", code, "configuration")


@pytest.mark.parametrize("kind", ["timeout", "evaluation_order", "verification_checks"])
def test_independent_protected_field_check_rejects_rehashed_configuration_mutations(kind):
    case = validation_case()

    def mutate(payload):
        if kind == "timeout":
            current = payload["private"]["verification"]["timeout_seconds"]
            payload["private"]["verification"]["timeout_seconds"] = current % 10 + 1
        elif kind == "evaluation_order":
            rule = next(
                item
                for item in payload["private"]["evaluation"]["rules"].values()
                if item["kind"] == "allowed_mapping"
            )
            rule["allowed_values"].reverse()
        else:
            payload["private"]["verification"]["profiles"]["repair"]["required_checks"].reverse()

    changed = changed_definition(case, mutate)
    runtime = ReportingRuntime()
    failure(
        check(case, candidate=changed, runtime=runtime),
        "invalid",
        "trusted_configuration_changed",
        "configuration",
    )
    assert not runtime.definitions


def test_trusted_factual_explanation_cannot_be_erased_even_with_a_new_valid_digest():
    case = validation_case()

    def mutate(payload):
        core = next(
            item
            for item in payload["explanations"]
            if item["release_event"] == "core_verification_passed"
        )
        core["text"] = "Generated framing without the trusted factual explanation."

    failure(
        check(case, candidate=changed_definition(case, mutate)),
        "invalid",
        "trusted_configuration_changed",
        "configuration",
    )


@pytest.mark.parametrize("field", ["title", "prediction_wording"])
def test_rehashed_copy_still_must_match_the_original_admitted_composition(field):
    case = validation_case()

    def mutate(payload):
        if field == "title":
            payload["title"] = "Different but structurally valid copy"
        else:
            payload["checkpoints"][0]["choices"][0]["label"] = "Different outcome wording."

    failure(
        check(case, candidate=changed_definition(case, mutate)),
        "invalid",
        "composition_mismatch",
        "configuration",
    )


def test_structurally_sound_candidate_without_a_runtime_remains_unavailable():
    result = check(validation_case(), runtime=None)
    failure(result, "unavailable", "runtime_unavailable", "runtime")
    assert not result.runtime_verification_performed and not result.runtime_verification_completed


@pytest.mark.parametrize("profile", [0, 1])
@pytest.mark.parametrize("category", sorted(CHECK_CODES))
def test_each_failed_runtime_evidence_category_blocks_success(profile, category):
    report = passing_runtime_report().model_dump()
    report["status"] = "failed"
    report["code"] = CandidateValidationCode.RUNTIME_EVIDENCE_FAILED
    next(item for item in report["profiles"][profile]["checks"] if item["code"] == category)[
        "passed"
    ] = False
    runtime = ReportingRuntime(RuntimeValidationReport.model_validate(report))
    result = check(validation_case(), runtime=runtime)
    failure(result, "runtime_failed", "runtime_evidence_failed", "runtime")
    assert result.runtime_verification_performed and result.runtime_verification_completed


@pytest.mark.parametrize(
    "kind", ["missing_profile", "missing_check", "duplicate_check", "unmatched_evaluation"]
)
def test_a_skipped_required_runtime_check_cannot_be_a_successful_report(kind):
    data = passing_runtime_report().model_dump()
    if kind == "missing_profile":
        data["profiles"] = data["profiles"][:1]
    elif kind == "missing_check":
        data["profiles"][1]["checks"] = data["profiles"][1]["checks"][:4]
    elif kind == "duplicate_check":
        data["profiles"][1]["checks"][0]["code"] = data["profiles"][1]["checks"][1]["code"]
    else:
        data["profiles"][1]["evaluation_matched"] = False
    with pytest.raises(ValidationError):
        RuntimeValidationReport.model_validate(data)
    result = check(validation_case(), runtime=ReportingRuntime(data))
    failure(result, "unavailable", "runtime_report_invalid", "runtime")


@pytest.mark.parametrize(
    "error,status,code",
    [
        (TimeoutError("Sensitive diagnostic sentinel"), "unavailable", "runtime_timeout"),
        (RuntimeError("Sensitive diagnostic sentinel"), "runtime_failed", "runtime_exception"),
    ],
)
def test_runtime_exceptions_and_timeout_fail_closed_without_echoing_exception_text(
    error, status, code
):
    result = check(validation_case(), runtime=ReportingRuntime(error=error))
    failure(result, status, code, "runtime")
    assert "Sensitive diagnostic sentinel" not in result.model_dump_json() + repr(result)
    assert not result.runtime_verification_completed


def test_runtime_dependency_unavailability_remains_distinct_from_semantic_rejection():
    report = RuntimeValidationReport(
        status="unavailable",
        code=CandidateValidationCode.RUNTIME_UNAVAILABLE,
        performed=False,
        completed=False,
    )
    result = check(validation_case(), runtime=ReportingRuntime(report))
    failure(result, "unavailable", "runtime_unavailable", "runtime")
    assert not result.runtime_verification_performed


def test_timeout_after_a_completed_baseline_does_not_claim_repair_completion():
    first = passing_runtime_report().profiles[:1]
    report = RuntimeValidationReport(
        status="unavailable",
        code=CandidateValidationCode.RUNTIME_TIMEOUT,
        performed=True,
        completed=False,
        profiles=first,
    )
    result = check(validation_case(), runtime=ReportingRuntime(report))
    failure(result, "unavailable", "runtime_timeout", "runtime")
    assert result.runtime_verification_performed and not result.runtime_verification_completed
    assert len(result.runtime_evidence) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"release_eligible": True},
        {"status": "published"},
        {"published": True},
        {"runtime_verification_performed": False},
        {"runtime_evidence": ()},
    ],
)
def test_result_schema_cannot_turn_partial_validation_into_release_or_publication(changes):
    result = check(validation_case())
    data = result.model_dump()
    assert CandidateValidationResult.model_validate(data) == result
    data.update(changes)
    with pytest.raises(ValidationError):
        CandidateValidationResult.model_validate(data)


def test_successful_result_cannot_skip_a_stage_and_all_nested_values_are_frozen():
    result = check(validation_case())
    data = result.model_dump()
    data["stages"][3]["status"] = "skipped"
    with pytest.raises(ValidationError):
        CandidateValidationResult.model_validate(data)
    for value, field, replacement in [
        (result, "release_eligible", True),
        (result.stages[0], "status", "skipped"),
        (result.runtime_evidence[0].checks[0], "passed", False),
    ]:
        with pytest.raises(ValidationError):
            setattr(value, field, replacement)


def test_diagnostics_and_result_shape_contain_no_private_definition_or_runtime_values():
    case = validation_case()
    result = check(case)
    encoded = result.model_dump_json()
    for private_text in [
        "Trace verification note",
        "Understanding request validation",
        "payload =",
        "Sensitive diagnostic sentinel",
    ]:
        assert private_text not in encoded

    def keys(value):
        if isinstance(value, dict):
            yield from value
            for child in value.values():
                yield from keys(child)
        elif isinstance(value, (tuple, list)):
            for child in value:
                yield from keys(child)

    assert not set(keys(result.model_dump())) & {
        "definition",
        "private",
        "rules",
        "answer",
        "correct_value",
        "expected",
        "actual",
        "response_json",
        "exception",
        "traceback",
        "source_artifacts",
    }
