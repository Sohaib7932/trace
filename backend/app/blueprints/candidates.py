"""Complete Notes/Tasks definitions proposed for independent human review.

These are newly authored version 1.1.0 candidates, not replacements for seeded
legacy 1.0.0 definitions. No test fixture is imported, no definition is registered,
and no approval is implied by schema/digest/runtime validation. The only executable
exercise bindings remain Trace's existing notes-v1 and tasks-nested-v1 adapters.
"""

import json
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, field_validator, model_validator

from app.domain.learning import NOTE_CONTENT, NOTE_TITLE
from app.domain.lesson_spec import LessonSpecV1, validate_lesson_spec
from app.domain.lesson_spec.canonical import canonical_bytes, finalize_definition
from app.domain.lesson_spec.fields import No, Value
from app.domain.lesson_spec.templates import NOTES, TASKS, Template
from app.domain.retrieval import QUESTIONS
from app.domain.transfer import TASK_PRIORITY, TASK_TITLE, TRANSFER_ID
from app.schemas.generation import TemplateFamily
from app.schemas.lesson_composition import TrustedLessonBlueprint

BLUEPRINT_CANDIDATE_VERSION = "1.1.0"
NOTES_LESSON_ID = "fastapi-payload-mismatch"
CORE_IDS = ("predict-request", "investigate-contract", "modify-request", "verify-save")
HINT_IDS = ("hint-orient", "hint-compare", "hint-evidence")
EVIDENCE_CATEGORIES = ("http_status", "api_response", "validation", "row_count", "stored_values")


class BlueprintCandidate(Value):
    """Review envelope, deliberately separate from trusted composition input."""

    template_family: TemplateFamily
    definition: LessonSpecV1 = Field(repr=False)
    review_status: Literal["pending"] = "pending"
    production_approved: No = False
    release_eligible: No = False

    @field_validator("definition", mode="before")
    @classmethod
    def validated_snapshot(cls, value: object) -> LessonSpecV1:
        if not isinstance(value, LessonSpecV1):
            raise ValueError("A blueprint candidate requires a validated definition")
        return validate_lesson_spec(canonical_bytes(value))

    @model_validator(mode="after")
    def complete_composition_shape(self) -> "BlueprintCandidate":
        self.trusted_blueprint()
        return self

    def trusted_blueprint(self) -> TrustedLessonBlueprint:
        """Validate server-owned fields for testing/composition, never approve release."""
        return TrustedLessonBlueprint(
            template_family=self.template_family, definition=self.definition
        )


def candidate_version_id(lesson_id: str) -> str:
    """A stable proposed identity; this function does not allocate a published version."""
    return str(uuid5(NAMESPACE_URL, f"trace:blueprint-candidate:{lesson_id}:1.1.0"))


def _core_checkpoint(
    kind: str, index: int, objective: str, *, title: str, prompt: str, **specific: object
) -> dict[str, object]:
    return {
        "id": CORE_IDS[index],
        "type": kind,
        "title": title,
        "prompt": prompt,
        "objective_ids": [objective],
        "depends_on": [] if index == 0 else [CORE_IDS[index - 1]],
        "hint_ids": [] if index == 0 else list(HINT_IDS),
        "evaluation_rule_id": f"rule-{kind}",
        **specific,
    }


def _definition(
    family: TemplateFamily, *, transfer_target: TrustedLessonBlueprint | None = None
) -> LessonSpecV1:
    notes = family == "notes-v1"
    template: Template = NOTES if notes else TASKS
    objective = "trace-contract" if notes else "trace-nesting"
    lesson_id = NOTES_LESSON_ID if notes else TRANSFER_ID
    inputs = (
        {"title": NOTE_TITLE, "content": NOTE_CONTENT}
        if notes
        else {"title": TASK_TITLE, "priority": TASK_PRIORITY}
    )
    checkpoints = [
        _core_checkpoint(
            "prediction",
            0,
            objective,
            title="Predict the unchanged request",
            prompt="Predict the outcome of the shown request before changing its mapping.",
            choices=[
                {"id": "rejected", "label": "The receiving contract rejects the request."},
                {"id": "saved", "label": "The request saves a row successfully."},
                {"id": "server_error", "label": "The service has an infrastructure failure."},
            ],
            reasoning_required=True,
        ),
        _core_checkpoint(
            "investigation",
            1,
            objective,
            title="Trace the receiving contract",
            prompt=(
                "Compare the sender and receiver with the observed initial validation evidence. "
                "Identify the outgoing field and its required receiving location."
            ),
            artifact_ids=["request-builder", "receiver-schema"],
            baseline_profile_id="initial_failure",
            baseline_evidence_artifact_id="observed-initial-validation",
        ),
        _core_checkpoint(
            "modification",
            2,
            objective,
            title="Choose a request mapping",
            prompt="Choose the bounded mapping change you want Trace to verify.",
            change_type=template.change_type,
            choices=[
                {"id": template.initial, "label": "Keep the original request mapping."},
                {"id": template.correct, "label": "Match the receiving contract's field location."},
            ],
            explanation_required=False,
        ),
        _core_checkpoint(
            "verification",
            3,
            objective,
            title="Verify the committed result",
            prompt=(
                "Use the observed HTTP response, validation and independent database readback "
                "to assess the mapping."
            ),
            modification_checkpoint_id=CORE_IDS[2],
            profile_id="repair",
        ),
    ]
    rules: dict[str, object] = {
        "rule-prediction": {
            "kind": "outcome_diagnostic",
            "answer": "rejected",
            "gate": "valid_submission",
        },
        "rule-investigation": {
            "kind": "field_trace",
            "expected_outgoing_field": template.outgoing_field,
            "expected_required_path": template.required_path,
            "required_artifact_ids": [
                "request-builder",
                "receiver-schema",
                "observed-initial-validation",
            ],
        },
        "rule-modification": {
            "kind": "allowed_mapping",
            "allowed_values": [template.initial, template.correct],
            "correct_value": template.correct,
        },
        "rule-verification": {"kind": "verified_repair"},
    }
    explanation = (
        "The receiver requires content and forbids the outgoing body field. The unchanged "
        "request produces HTTP 422 with missing content and extra body validation errors, "
        "and saves no note. A content mapping succeeds only when HTTP 201, valid response "
        "data, no validation errors and one independently read row agree, including row identity."
        if notes
        else "The receiver requires metadata containing priority and forbids a flat "
        "priority field. "
        "The unchanged request produces HTTP 422 with missing metadata and extra priority "
        "validation errors, and saves no task. A nested mapping succeeds only when HTTP 201, "
        "the response metadata and one independently read task agree, including row identity."
    )
    explanations: list[dict[str, object]] = [
        {
            "id": "explain-core",
            "title": "What the runtime evidence establishes",
            "text": explanation,
            "checkpoint_id": CORE_IDS[3],
            "release_event": "core_verification_passed",
        }
    ]
    transfer_ids: list[str] = []
    retrieval_ids: list[str] = []
    if notes:
        if transfer_target is None:
            raise ValueError("Notes candidate requires its complete pinned Tasks candidate")
        transfer_ids = ["transfer-contract"]
        checkpoints.append(
            {
                "id": transfer_ids[0],
                "type": "transfer",
                "title": "Transfer the contract diagnosis",
                "prompt": "Apply the same request-contract reasoning to the nested Tasks lesson.",
                "objective_ids": [objective],
                "depends_on": [CORE_IDS[3]],
                "hint_ids": [],
                "evaluation_rule_id": "rule-transfer",
                "target_version": transfer_target.reference().model_dump(mode="json"),
            }
        )
        rules["rule-transfer"] = {"kind": "linked_session_completion"}
        for ordinal, question in enumerate(QUESTIONS, 1):
            delay = (1, 7)[ordinal - 1]
            checkpoint_id = f"revisit-day-{delay}"
            retrieval_ids.append(checkpoint_id)
            explanation_id = f"explain-revisit-{ordinal}"
            checkpoints.append(
                {
                    "id": checkpoint_id,
                    "type": "retrieval",
                    "title": question.title,
                    "prompt": "Recall the contract concept using this new bounded example.",
                    "objective_ids": [objective],
                    "depends_on": transfer_ids,
                    "hint_ids": [],
                    "evaluation_rule_id": f"rule-retrieval-{ordinal}",
                    "ordinal": ordinal,
                    "schedule": {"anchor_checkpoint_id": transfer_ids[0], "delay_days": delay},
                    "question": {
                        "id": question.id,
                        "title": question.title,
                        "prompt": question.prompt,
                        "payload": json.loads(question.payload),
                        "schema_code": question.schema_code,
                        "options": [
                            {"id": key, "label": label}
                            for key, label in zip("abc", question.options, strict=True)
                        ],
                    },
                    "feedback_after": "saved_response",
                }
            )
            explanations.append(
                {
                    "id": explanation_id,
                    "title": "Feedback after your saved response",
                    "text": question.explanation,
                    "checkpoint_id": checkpoint_id,
                    "release_event": "retrieval_response_saved",
                }
            )
            rules[f"rule-retrieval-{ordinal}"] = {
                "kind": "single_choice",
                "answer": question.answer,
                "explanation_id": explanation_id,
            }
    payload = {
        "spec_version": "1.0.0",
        "lesson_id": lesson_id,
        "version_id": candidate_version_id(lesson_id),
        "version": BLUEPRINT_CANDIDATE_VERSION,
        "entry_mode": "catalog" if notes else "transfer_only",
        "title": "Follow a note through its request contract"
        if notes
        else "Trace the nested task contract",
        "summary": (
            "Diagnose a bounded FastAPI request mismatch and verify the committed result."
            if notes
            else "Transfer request-contract reasoning to a nested FastAPI payload."
        ),
        "objectives": [
            {
                "id": objective,
                "statement": (
                    "Trace a value from the outgoing JSON field into the receiving contract "
                    "and verify a committed save."
                    if notes
                    else "Trace a value's JSON nesting into the receiving model and verify "
                    "a committed task."
                ),
                "evidence_checkpoint_ids": [checkpoint["id"] for checkpoint in checkpoints],
            }
        ],
        "scenario": {
            "context": (
                "A notes request contains the intended text but no note is saved. Inspect "
                "the sender, "
                "receiver and actual validation evidence before selecting a mapping change."
                if notes
                else "A task request contains a title and priority but no task is saved. "
                "Inspect the JSON "
                "levels and nested receiver before selecting a mapping change."
            ),
            "input_values": inputs,
            "initial_state_description": (
                "This isolated verification run begins without stored exercise rows."
            ),
            "artifacts": [
                {
                    "id": "request-builder",
                    "label": "The unchanged outgoing request",
                    "language": "python",
                    "content": template.request_source,
                },
                {
                    "id": "receiver-schema",
                    "label": "The actual receiving model contract",
                    "language": "python",
                    "content": template.receiver_source,
                },
            ],
        },
        "checkpoints": checkpoints,
        "hints": [
            {"id": key, "level": level, "text": text, "checkpoint_ids": list(CORE_IDS[1:])}
            for level, (key, text) in enumerate(
                zip(
                    HINT_IDS,
                    (
                        "Trace the request data from its sender into its receiving model.",
                        "Compare each outgoing field location with the required "
                        "receiving location.",
                        "Use the missing and extra validation fields before investigating "
                        "database code.",
                    ),
                    strict=True,
                ),
                1,
            )
        ],
        "explanations": explanations,
        "misconceptions": [
            {
                "id": "presence-implies-validity",
                "statement": (
                    "Containing the intended value alone means a request satisfies its contract."
                ),
                "indicator": {
                    "kind": "mapping_selected",
                    "checkpoint_id": CORE_IDS[2],
                    "value": template.initial,
                },
                "suggested_feedback": (
                    "Compare both the value and its receiving field location; presence alone "
                    "is insufficient."
                ),
            }
        ],
        "completion_policy": {
            "core_checkpoint_ids": list(CORE_IDS),
            "transfer_checkpoint_ids": transfer_ids,
            "retrieval_checkpoint_ids": retrieval_ids,
        },
        "tutor_policy": {
            "mode": "authored_only",
            "max_requests_per_core_session": 3,
            "available_after_checkpoint_id": CORE_IDS[0],
        },
        "private": {
            "runtime_binding": {"template_id": family, "revision": "1.0.0"},
            "evaluation": {"policy_id": "payload-contract-v1", "revision": "1.0.0", "rules": rules},
            "verification": {
                "timeout_seconds": 10,
                "fixture": {
                    "id": template.fixture_id,
                    "input_values": inputs,
                    "initial_mapping": template.initial,
                },
                "profiles": {
                    "initial_failure": {
                        "purpose": "baseline",
                        "http_status": 422,
                        "response_shape": "validation_errors",
                        "validation_codes": list(template.validation_codes),
                        "row_count": 0,
                        "stored_values": {},
                        "require_response_row_identity_match": False,
                        "required_checks": list(EVIDENCE_CATEGORIES),
                    },
                    "repair": {
                        "purpose": "repair",
                        "http_status": 201,
                        "response_shape": template.response_shape,
                        "validation_codes": [],
                        "row_count": 1,
                        "stored_values": inputs,
                        "require_response_row_identity_match": True,
                        "required_checks": list(EVIDENCE_CATEGORIES),
                    },
                },
            },
        },
        "content_sha256": "0" * 64,
    }
    return finalize_definition(payload)


def tasks_blueprint_candidate() -> BlueprintCandidate:
    """Author the complete transfer-only Tasks candidate, without registering it."""
    return BlueprintCandidate(
        template_family="tasks-nested-v1", definition=_definition("tasks-nested-v1")
    )


def notes_blueprint_candidate() -> BlueprintCandidate:
    """Author Notes after finalizing the complete exact Tasks transfer dependency."""
    target = tasks_blueprint_candidate().trusted_blueprint()
    return BlueprintCandidate(
        template_family="notes-v1", definition=_definition("notes-v1", transfer_target=target)
    )
