"""Immutable value types for the V1 definition; no transport or execution code."""

import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StrictBool,
    StrictInt,
)


def plain_text(value: str) -> str:
    if not value.strip():
        raise ValueError("Text must be nonblank")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise ValueError("Control characters are not supported")
    if re.search(r"<\s*[a-zA-Z!/?][^>]*>", value):
        raise ValueError("HTML is not supported")
    if re.search(
        r"\b[a-z][a-z0-9+.-]*://|\b(?:mailto|javascript|data):(?=\S)|\bwww\.|(?<!:)//[a-z]",
        value,
        re.I,
    ):
        raise ValueError("URLs are not supported")
    return value  # Validation never strips, normalizes or canonicalizes authored text.


def array(value: object) -> object:
    if not isinstance(value, (list, tuple)):
        raise ValueError("Expected an array")
    return tuple(value)


def integer(value: object) -> object:
    if type(value) is not int:
        raise ValueError("Expected an integer, not a boolean or coercible value")
    return value


def boolean(value: object) -> object:
    if type(value) is not bool:
        raise ValueError("Expected a boolean")
    return value


type Items[T] = Annotated[tuple[T, ...], BeforeValidator(array)]
type Prose = Annotated[str, Field(min_length=1, max_length=4000), AfterValidator(plain_text)]
type SourceText = Annotated[str, Field(min_length=1, max_length=8000), AfterValidator(plain_text)]
type Title = Annotated[str, Field(min_length=1, max_length=120), AfterValidator(plain_text)]
type Summary = Annotated[str, Field(min_length=1, max_length=600), AfterValidator(plain_text)]
type LocalId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,63}$", max_length=64)]
type LessonId = Annotated[str, Field(pattern=r"^[a-z0-9-]{1,80}$", max_length=80)]
type Version = Annotated[
    str, Field(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$", max_length=32)
]
type VersionId = Annotated[
    str,
    Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        min_length=36,
        max_length=36,
    ),
]
type Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)]
type Yes = Annotated[Literal[True], BeforeValidator(boolean)]
type No = Annotated[Literal[False], BeforeValidator(boolean)]
type Outcome = Literal["rejected", "saved", "server_error"]
type MappingValue = Literal["body", "content", "flat", "nested"]
type CheckCode = Literal["http_status", "api_response", "validation", "row_count", "stored_values"]
type ValidationCode = Literal[
    "missing:content", "extra_forbidden:body", "missing:metadata", "extra_forbidden:priority"
]


class Value(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
        validate_default=True,
    )


class NoteInputs(Value):
    title: Literal["Trace verification note"]
    content: Literal["Understanding request validation"]


class TaskInputs(Value):
    title: Literal["Prepare the product demo"]
    priority: Literal["high"]


type FixtureInputs = NoteInputs | TaskInputs


class SourceArtifact(Value):
    id: LocalId
    label: Prose
    language: Literal["python"]
    content: SourceText


class Scenario(Value):
    context: Prose
    input_values: FixtureInputs
    initial_state_description: Prose
    artifacts: Items[SourceArtifact] = Field(min_length=2, max_length=2)


class Objective(Value):
    id: LocalId
    statement: Prose
    evidence_checkpoint_ids: Items[LocalId] = Field(min_length=1, max_length=7)


class Choice(Value):
    id: LocalId
    label: Prose


class OutcomeChoice(Value):
    # server_error is a fixed legacy choice, not a generic local identifier.
    id: Outcome
    label: Prose


class Checkpoint(Value):
    id: LocalId
    title: Prose
    prompt: Prose
    objective_ids: Items[LocalId] = Field(min_length=1, max_length=3)
    depends_on: Items[LocalId] = Field(max_length=1)
    hint_ids: Items[LocalId] = Field(max_length=3)
    evaluation_rule_id: LocalId


class PredictionCheckpoint(Checkpoint):
    type: Literal["prediction"]
    choices: Items[OutcomeChoice] = Field(min_length=3, max_length=3)
    reasoning_required: Yes


class InvestigationCheckpoint(Checkpoint):
    type: Literal["investigation"]
    artifact_ids: Items[LocalId] = Field(min_length=2, max_length=2)
    baseline_profile_id: Literal["initial_failure"]
    baseline_evidence_artifact_id: LocalId


class ModificationCheckpoint(Checkpoint):
    type: Literal["modification"]
    change_type: Literal["rename_payload_field", "nest_payload_field"]
    choices: Items[Choice] = Field(min_length=2, max_length=2)
    explanation_required: No


class VerificationCheckpoint(Checkpoint):
    type: Literal["verification"]
    modification_checkpoint_id: LocalId
    profile_id: Literal["repair"]


class VersionReference(Value):
    lesson_id: LessonId
    version_id: VersionId
    version: Version
    content_sha256: Digest = Field(repr=False)


class TransferCheckpoint(Checkpoint):
    type: Literal["transfer"]
    target_version: VersionReference


class Schedule(Value):
    anchor_checkpoint_id: LocalId
    delay_days: Annotated[Literal[1, 7], BeforeValidator(integer)]


def frozen_map[K, V](value: Mapping[K, V]) -> Mapping[K, V]:
    return MappingProxyType(dict(value))


def json_value(value: object) -> object:
    """Thaw display data for serialization, not canonical bytes or a digest."""
    if isinstance(value, Mapping):
        return {key: json_value(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [json_value(child) for child in value]
    return value


type DisplayValue = (
    Prose
    | StrictBool
    | StrictInt
    | None
    | Items[DisplayValue]
    | Annotated[Mapping[str, DisplayValue], AfterValidator(frozen_map), PlainSerializer(json_value)]
)
type DisplayObject = Annotated[
    Mapping[str, DisplayValue],
    AfterValidator(frozen_map),
    PlainSerializer(json_value),
]


class RetrievalQuestion(Value):
    id: LocalId
    title: Prose
    prompt: Prose
    payload: DisplayObject
    schema_code: SourceText
    options: Items[Choice] = Field(min_length=3, max_length=3)


class RetrievalCheckpoint(Checkpoint):
    type: Literal["retrieval"]
    ordinal: Annotated[Literal[1, 2], BeforeValidator(integer)]
    schedule: Schedule
    question: RetrievalQuestion
    feedback_after: Literal["saved_response"]


type CheckpointDefinition = Annotated[
    PredictionCheckpoint
    | InvestigationCheckpoint
    | ModificationCheckpoint
    | VerificationCheckpoint
    | TransferCheckpoint
    | RetrievalCheckpoint,
    Field(discriminator="type"),
]


class Hint(Value):
    id: LocalId
    level: Annotated[StrictInt, Field(ge=1, le=3)]
    text: Prose
    checkpoint_ids: Items[LocalId] = Field(min_length=1, max_length=3)


class Explanation(Value):
    id: LocalId
    title: Prose
    text: Prose
    checkpoint_id: LocalId
    release_event: Literal["core_verification_passed", "retrieval_response_saved"]


class MappingIndicator(Value):
    kind: Literal["mapping_selected"]
    checkpoint_id: LocalId
    value: MappingValue


class Misconception(Value):
    id: LocalId
    statement: Prose
    indicator: MappingIndicator
    suggested_feedback: Prose


class CompletionPolicy(Value):
    core_checkpoint_ids: Items[LocalId] = Field(min_length=4, max_length=4)
    transfer_checkpoint_ids: Items[LocalId] = Field(max_length=1)
    retrieval_checkpoint_ids: Items[LocalId] = Field(max_length=2)


class TutorPolicy(Value):
    mode: Literal["authored_only"]
    max_requests_per_core_session: Annotated[Literal[3], BeforeValidator(integer)]
    available_after_checkpoint_id: LocalId


class RuntimeBinding(Value):
    template_id: Literal["notes-v1", "tasks-nested-v1"]
    revision: Literal["1.0.0"]


class OutcomeRule(Value):
    kind: Literal["outcome_diagnostic"]
    answer: Outcome
    gate: Literal["valid_submission"]


class TraceRule(Value):
    kind: Literal["field_trace"]
    expected_outgoing_field: Literal["body", "priority"]
    expected_required_path: Literal["/content", "/metadata/priority"]
    required_artifact_ids: Items[LocalId] = Field(min_length=3, max_length=3)


class MappingRule(Value):
    kind: Literal["allowed_mapping"]
    allowed_values: Items[MappingValue] = Field(min_length=2, max_length=2)
    correct_value: MappingValue


class RepairRule(Value):
    kind: Literal["verified_repair"]


class TransferRule(Value):
    kind: Literal["linked_session_completion"]


class ChoiceRule(Value):
    kind: Literal["single_choice"]
    answer: LocalId
    explanation_id: LocalId


type EvaluationRule = Annotated[
    OutcomeRule | TraceRule | MappingRule | RepairRule | TransferRule | ChoiceRule,
    Field(discriminator="kind"),
]


class EvaluationPolicy(Value):
    policy_id: Literal["payload-contract-v1"]
    revision: Literal["1.0.0"]
    rules: Annotated[
        Mapping[LocalId, EvaluationRule],
        AfterValidator(frozen_map),
        PlainSerializer(dict, return_type=dict[str, EvaluationRule]),
    ] = Field(min_length=4, max_length=7)


class Fixture(Value):
    id: LocalId
    input_values: FixtureInputs
    initial_mapping: MappingValue


class EmptyValues(Value):
    pass


class BaselineProfile(Value):
    purpose: Literal["baseline"]
    http_status: Annotated[Literal[422], BeforeValidator(integer)]
    response_shape: Literal["validation_errors"]
    validation_codes: Items[ValidationCode] = Field(min_length=2, max_length=2)
    row_count: Annotated[Literal[0], BeforeValidator(integer)]
    stored_values: EmptyValues
    require_response_row_identity_match: No
    required_checks: Items[CheckCode] = Field(min_length=5, max_length=5)


class RepairProfile(Value):
    purpose: Literal["repair"]
    http_status: Annotated[Literal[201], BeforeValidator(integer)]
    response_shape: Literal["saved_note", "saved_task"]
    validation_codes: Items[ValidationCode] = Field(max_length=0)
    row_count: Annotated[Literal[1], BeforeValidator(integer)]
    stored_values: FixtureInputs
    require_response_row_identity_match: Yes
    required_checks: Items[CheckCode] = Field(min_length=5, max_length=5)


class Profiles(Value):
    initial_failure: BaselineProfile
    repair: RepairProfile


class VerificationPolicy(Value):
    timeout_seconds: Annotated[StrictInt, Field(ge=1, le=10)]
    fixture: Fixture
    profiles: Profiles


class PrivateDefinition(Value):
    runtime_binding: RuntimeBinding
    evaluation: EvaluationPolicy = Field(repr=False)
    verification: VerificationPolicy = Field(repr=False)
