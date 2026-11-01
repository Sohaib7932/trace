"""Strict V1 definition validation and a safe initial learner projection.

No hashes are computed or verified, no text is normalized, and no definition is
registered, executed or persisted. Use validate_lesson_spec for untrusted JSON;
unlike a generic JSON decoder it rejects duplicate object properties.
"""

import json
from collections.abc import Hashable, Iterable
from typing import Literal, Self

from pydantic import Field, model_validator

from .fields import (
    CheckpointDefinition,
    ChoiceRule,
    CompletionPolicy,
    Digest,
    Explanation,
    Hint,
    InvestigationCheckpoint,
    Items,
    LessonId,
    LocalId,
    MappingRule,
    Misconception,
    ModificationCheckpoint,
    NoteInputs,
    Objective,
    OutcomeChoice,
    OutcomeRule,
    PredictionCheckpoint,
    PrivateDefinition,
    Prose,
    RepairRule,
    RetrievalCheckpoint,
    Scenario,
    Summary,
    TaskInputs,
    Title,
    TraceRule,
    TransferCheckpoint,
    TransferRule,
    TutorPolicy,
    Value,
    VerificationCheckpoint,
    Version,
    VersionId,
    Yes,
)
from .templates import NOTES, TASKS, Template, validate_display_schema

MAX_DEFINITION_BYTES = 64 * 1024
MAX_JSON_DEPTH = 32
CHECKS = frozenset({"http_status", "api_response", "validation", "row_count", "stored_values"})


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def unique(values: Iterable[Hashable], label: str) -> None:
    items = tuple(values)
    require(len(items) == len(set(items)), f"Duplicate {label}")


def json_tree(value: object, depth: int = 0) -> None:
    require(depth <= MAX_JSON_DEPTH, "Definition exceeds the JSON nesting limit")
    if type(value) in {str, int, bool} or value is None:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            require(
                type(key) is str
                and bool(key.strip())
                and key.isascii()
                and all(32 <= ord(char) < 127 for char in key),
                "JSON property names must be nonblank printable ASCII",
            )
            json_tree(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            json_tree(child, depth + 1)
    else:
        raise ValueError(
            "Only JSON objects, arrays, strings, integers, booleans and null are supported"
        )


def bounded_document(value: object) -> object:
    json_tree(value)
    try:
        size = len(
            json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
                "utf-8"
            )
        )
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("Definition must be valid UTF-8 JSON") from exc
    require(size <= MAX_DEFINITION_BYTES, "Definition exceeds 65536 UTF-8 bytes")
    return value


class LessonSpecV1(Value):
    spec_version: Literal["1.0.0"]
    lesson_id: LessonId
    version_id: VersionId
    version: Version
    entry_mode: Literal["catalog", "transfer_only"]
    title: Title
    summary: Summary
    objectives: Items[Objective] = Field(min_length=1, max_length=3)
    scenario: Scenario
    checkpoints: Items[CheckpointDefinition] = Field(min_length=4, max_length=7, repr=False)
    hints: Items[Hint] = Field(max_length=3, repr=False)
    explanations: Items[Explanation] = Field(repr=False)
    misconceptions: Items[Misconception] = Field(max_length=8, repr=False)
    completion_policy: CompletionPolicy
    tutor_policy: TutorPolicy
    private: PrivateDefinition = Field(repr=False)
    content_sha256: Digest = Field(repr=False)

    @model_validator(mode="before")
    @classmethod
    def bounded(cls, value: object) -> object:
        return bounded_document(value)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        expected: tuple[str, ...] = ("prediction", "investigation", "modification", "verification")
        if self.entry_mode == "catalog":
            expected += ("transfer", "retrieval", "retrieval")
        require(
            tuple(cp.type for cp in self.checkpoints) == expected,
            "Invalid fixed V1 checkpoint topology",
        )
        prediction, investigation, modification, verification = self.checkpoints[:4]
        if not (
            isinstance(prediction, PredictionCheckpoint)
            and isinstance(investigation, InvestigationCheckpoint)
            and isinstance(modification, ModificationCheckpoint)
            and isinstance(verification, VerificationCheckpoint)
        ):
            raise ValueError("Invalid core checkpoint variants")
        unique((cp.id for cp in self.checkpoints), "checkpoint IDs")
        unique((obj.id for obj in self.objectives), "objective IDs")
        unique((artifact.id for artifact in self.scenario.artifacts), "artifact IDs")
        unique((hint.id for hint in self.hints), "hint IDs")
        unique((hint.level for hint in self.hints), "hint levels")
        unique((item.id for item in self.explanations), "explanation IDs")
        unique((item.id for item in self.misconceptions), "misconception IDs")
        unique((cp.evaluation_rule_id for cp in self.checkpoints), "checkpoint rule references")
        checkpoints = {cp.id: cp for cp in self.checkpoints}
        objectives = {obj.id for obj in self.objectives}
        hints = {hint.id: hint for hint in self.hints}
        rules = self.private.evaluation.rules
        require(
            set(rules) == {cp.evaluation_rule_id for cp in self.checkpoints},
            "Rules must be exactly the referenced checkpoint rules",
        )
        kinds = {
            "prediction": OutcomeRule,
            "investigation": TraceRule,
            "modification": MappingRule,
            "verification": RepairRule,
            "transfer": TransferRule,
            "retrieval": ChoiceRule,
        }
        for index, cp in enumerate(self.checkpoints):
            dependencies = () if index == 0 else (self.checkpoints[min(index - 1, 4)].id,)
            require(
                cp.depends_on == dependencies,
                "Checkpoint dependencies must follow fixed V1 topology",
            )
            unique(cp.objective_ids, "checkpoint objective references")
            unique(cp.hint_ids, "checkpoint hint references")
            require(set(cp.objective_ids) <= objectives, "Unknown checkpoint objective reference")
            require(set(cp.hint_ids) <= hints.keys(), "Unknown checkpoint hint reference")
            require(
                isinstance(rules[cp.evaluation_rule_id], kinds[cp.type]),
                "Checkpoint rule kind does not match its checkpoint",
            )
        for obj in self.objectives:
            unique(obj.evidence_checkpoint_ids, "objective evidence references")
            require(
                set(obj.evidence_checkpoint_ids) <= checkpoints.keys(),
                "Unknown objective evidence reference",
            )
            require(
                all(
                    obj.id in checkpoints[key].objective_ids for key in obj.evidence_checkpoint_ids
                ),
                "Objective evidence must reference the same objective",
            )
        allowed_hint_targets = {investigation.id, modification.id, verification.id}
        for hint in self.hints:
            unique(hint.checkpoint_ids, "hint checkpoint references")
            require(
                set(hint.checkpoint_ids) <= allowed_hint_targets,
                "Hints apply only after prediction within the core session",
            )
            require(
                set(hint.checkpoint_ids)
                == {cp.id for cp in self.checkpoints if hint.id in cp.hint_ids},
                "Hint and checkpoint references must agree",
            )
        for cp in self.checkpoints:
            require(
                cp.id in allowed_hint_targets or not cp.hint_ids,
                "Hints cannot reveal prediction, transfer or retrieval answers",
            )
        require(
            self.tutor_policy.available_after_checkpoint_id == prediction.id,
            "Tutor gate must be the prediction checkpoint",
        )
        core_ids = tuple(cp.id for cp in self.checkpoints[:4])
        transfer_ids = tuple(cp.id for cp in self.checkpoints if isinstance(cp, TransferCheckpoint))
        retrieval_ids = tuple(
            cp.id for cp in self.checkpoints if isinstance(cp, RetrievalCheckpoint)
        )
        require(
            self.completion_policy.core_checkpoint_ids == core_ids,
            "Core completion policy must match checkpoint order",
        )
        require(
            self.completion_policy.transfer_checkpoint_ids == transfer_ids,
            "Transfer completion policy must match checkpoints",
        )
        require(
            self.completion_policy.retrieval_checkpoint_ids == retrieval_ids,
            "Retrieval completion policy must match checkpoint order",
        )
        require(
            verification.modification_checkpoint_id == modification.id,
            "Verification must reference this session's modification checkpoint",
        )
        self._template(prediction, investigation, modification)
        self._feedback(modification, verification)
        return self

    def _template(
        self,
        prediction: PredictionCheckpoint,
        investigation: InvestigationCheckpoint,
        modification: ModificationCheckpoint,
    ) -> None:
        template = NOTES if self.private.runtime_binding.template_id == "notes-v1" else TASKS
        expected_inputs = NoteInputs if template is NOTES else TaskInputs
        fixture, profiles = self.private.verification.fixture, self.private.verification.profiles
        require(
            isinstance(self.scenario.input_values, expected_inputs),
            "Scenario inputs do not match the template",
        )
        require(
            self.scenario.input_values == fixture.input_values == profiles.repair.stored_values,
            "Fixture, scenario and expected stored values must match",
        )
        require(
            fixture.id == template.fixture_id and fixture.initial_mapping == template.initial,
            "Fixture identity or initial mapping does not match the template",
        )
        artifacts = {artifact.id: artifact.content for artifact in self.scenario.artifacts}
        require(
            artifacts
            == {
                "request-builder": template.request_source,
                "receiver-schema": template.receiver_source,
            },
            "Source artifacts must match the trusted template exactly",
        )
        require(
            set(investigation.artifact_ids) == artifacts.keys(),
            "Investigation must reference both source artifacts",
        )
        require(
            investigation.baseline_evidence_artifact_id not in artifacts,
            "Baseline evidence is a distinct server-produced artifact",
        )
        prediction_rule = self.private.evaluation.rules[prediction.evaluation_rule_id]
        trace_rule = self.private.evaluation.rules[investigation.evaluation_rule_id]
        mapping_rule = self.private.evaluation.rules[modification.evaluation_rule_id]
        if (
            not isinstance(prediction_rule, OutcomeRule)
            or not isinstance(trace_rule, TraceRule)
            or not isinstance(mapping_rule, MappingRule)
        ):
            raise ValueError("Invalid technical rule variants")
        unique((choice.id for choice in prediction.choices), "prediction choice IDs")
        require(
            {choice.id for choice in prediction.choices} == {"rejected", "saved", "server_error"},
            "Prediction must contain all three outcomes",
        )
        require(prediction_rule.answer == "rejected", "Prediction answer is fixed by the template")
        require(
            trace_rule.expected_outgoing_field == template.outgoing_field
            and trace_rule.expected_required_path == template.required_path,
            "Field trace does not match the template",
        )
        unique(trace_rule.required_artifact_ids, "field trace artifact references")
        require(
            set(trace_rule.required_artifact_ids)
            == set(artifacts) | {investigation.baseline_evidence_artifact_id},
            "Field trace must require sender, receiver and baseline evidence",
        )
        allowed = {template.initial, template.correct}
        unique((choice.id for choice in modification.choices), "modification choice IDs")
        unique(mapping_rule.allowed_values, "allowed mapping values")
        require(
            modification.change_type == template.change_type,
            "Modification kind does not match the template",
        )
        require(
            {choice.id for choice in modification.choices}
            == set(mapping_rule.allowed_values)
            == allowed
            and mapping_rule.correct_value == template.correct,
            "Modification choices and correct mapping are template-owned",
        )
        _profiles(
            template, profiles.initial_failure.validation_codes, profiles.repair.response_shape
        )
        for profile in (profiles.initial_failure, profiles.repair):
            require(
                set(profile.required_checks) == CHECKS,
                "Every verification profile requires all five distinct evidence checks",
            )

    def _feedback(
        self, modification: ModificationCheckpoint, verification: VerificationCheckpoint
    ) -> None:
        checkpoints = {cp.id: cp for cp in self.checkpoints}
        explanations = {item.id: item for item in self.explanations}
        for item in self.explanations:
            require(item.checkpoint_id in checkpoints, "Unknown explanation checkpoint")
            if item.release_event == "core_verification_passed":
                require(
                    item.checkpoint_id == verification.id,
                    "Core explanations release only after this core verification",
                )
            else:
                require(
                    isinstance(checkpoints[item.checkpoint_id], RetrievalCheckpoint),
                    "Retrieval explanations require a retrieval checkpoint",
                )
        for misconception in self.misconceptions:
            require(
                misconception.indicator.checkpoint_id == modification.id
                and misconception.indicator.value in {choice.id for choice in modification.choices},
                "Misconception indicators must reference an allowed mapping in this modification",
            )
        questions = []
        for cp in self.checkpoints:
            if isinstance(cp, TransferCheckpoint):
                require(
                    cp.target_version.lesson_id != self.lesson_id
                    and cp.target_version.version_id != self.version_id,
                    "Transfer cannot reference its own lesson or version",
                )
            if not isinstance(cp, RetrievalCheckpoint):
                continue
            questions.append(cp.question.id)
            expected_ordinal = len(questions)
            transfer = self.checkpoints[4]
            require(
                cp.ordinal == expected_ordinal
                and cp.schedule.delay_days == (1 if expected_ordinal == 1 else 7),
                "Retrieval ordinals and delays must be 1/+1 day and 2/+7 days",
            )
            require(
                cp.schedule.anchor_checkpoint_id == transfer.id, "Retrieval must anchor to transfer"
            )
            unique((option.id for option in cp.question.options), "retrieval option IDs")
            validate_display_schema(cp.question.schema_code)
            rule = self.private.evaluation.rules[cp.evaluation_rule_id]
            if not isinstance(rule, ChoiceRule):
                raise ValueError("Retrieval requires a single-choice rule")
            require(
                rule.answer in {option.id for option in cp.question.options},
                "Retrieval answer must identify an option",
            )
            explanation = explanations.get(rule.explanation_id)
            require(
                explanation is not None
                and explanation.checkpoint_id == cp.id
                and explanation.release_event == "retrieval_response_saved",
                "Retrieval feedback must reference its own saved-response explanation",
            )
        unique(questions, "retrieval question IDs")


def _profiles(template: Template, codes: tuple[str, ...], shape: str) -> None:
    require(
        len(set(codes)) == 2 and set(codes) == set(template.validation_codes),
        "Baseline validation codes must match the template exactly",
    )
    require(shape == template.response_shape, "Repair response shape does not match the template")


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON property")
        result[key] = value
    return result


def _not_integer(value: str) -> object:
    raise ValueError("Only integer JSON numbers are supported")


def validate_lesson_spec(value: object) -> LessonSpecV1:
    """Parse one definition, not the documentation bundle. Digests are syntax-only.

    Raw UTF-8 input is bounded before decoding. Mapping inputs use their compact
    JSON size solely for the byte budget; no normalized/canonical output is made.
    Published target existence, hash verification and authority are later work.
    """
    if isinstance(value, (str, bytes, bytearray)):
        try:
            raw = value.encode("utf-8") if isinstance(value, str) else bytes(value)
            require(len(raw) <= MAX_DEFINITION_BYTES, "Definition exceeds 65536 UTF-8 bytes")
            value = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_object,
                parse_float=_not_integer,
                parse_constant=_not_integer,
            )
        except (UnicodeError, RecursionError, json.JSONDecodeError) as exc:
            raise ValueError("Definition must be valid UTF-8 JSON") from exc
    return LessonSpecV1.model_validate(value, strict=True)


class LearnerObjective(Value):
    id: LocalId
    statement: Prose


class LearnerPrediction(Value):
    id: LocalId
    type: Literal["prediction"] = "prediction"
    title: Prose
    prompt: Prose
    choices: Items[OutcomeChoice]
    reasoning_required: Yes = True


class InitialLearnerLesson(Value):
    definition_format: Literal["lesson_spec_v1"] = "lesson_spec_v1"
    spec_version: Literal["1.0.0"]
    lesson_id: LessonId
    version_id: VersionId
    version: Version
    title: Title
    summary: Summary
    objectives: Items[LearnerObjective]
    scenario: Scenario
    prediction: LearnerPrediction


def initial_learner_projection(definition: LessonSpecV1) -> InitialLearnerLesson:
    """Allowlist the initial view only; no runtime unlock or learner API is added."""
    prediction = definition.checkpoints[0]
    if not isinstance(prediction, PredictionCheckpoint):
        raise ValueError("Expected a validated prediction checkpoint")
    return InitialLearnerLesson(
        spec_version=definition.spec_version,
        lesson_id=definition.lesson_id,
        version_id=definition.version_id,
        version=definition.version,
        title=definition.title,
        summary=definition.summary,
        objectives=tuple(
            LearnerObjective(id=obj.id, statement=obj.statement) for obj in definition.objectives
        ),
        scenario=definition.scenario,
        prediction=LearnerPrediction(
            id=prediction.id,
            title=prediction.title,
            prompt=prediction.prompt,
            choices=prediction.choices,
        ),
    )
