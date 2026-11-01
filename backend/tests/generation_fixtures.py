"""Contract data only, not a QuestionGenerator implementation or prompt builder."""

import json
from pathlib import Path

EXAMPLES = (
    Path(__file__).resolve().parents[2] / "docs/architecture/examples/lesson-specification-v1.json"
)


def reference_definition(family="notes-v1"):
    versions = json.loads(EXAMPLES.read_text(encoding="utf-8"))["lesson_versions"]
    return next(
        row for row in versions if row["private"]["runtime_binding"]["template_id"] == family
    )


def content_data(family="notes-v1"):
    reference = reference_definition(family)
    return {
        "contract_version": "1.0.0",
        "title": reference["title"],
        "description": reference["summary"],
        # Test server-issued keys, not a new production capability registry.
        "context_variant": "default-narrative",
        "objectives": [
            {"slot_key": item["id"], "statement": item["statement"]}
            for item in reference["objectives"]
        ],
        "scenario_narrative": reference["scenario"]["context"],
        "prediction": {
            "prompt": reference["checkpoints"][0]["prompt"],
            "choice_wording": {
                "rejected": "default",
                "saved": "default",
                "server_error": "default",
            },
        },
        "investigation_prompt": reference["checkpoints"][1]["prompt"],
        "modification_instructions": reference["checkpoints"][2]["prompt"],
        "hints": dict(
            zip(
                ["orient", "compare", "investigate_evidence"],
                [item["text"] for item in reference["hints"]],
                strict=True,
            )
        ),
        "explanations": {
            "concept": "The receiving contract determines which request shape is accepted.",
            "evidence": (
                "Compare the observed response with an independent read of committed state."
            ),
        },
        "misconceptions": [
            {
                "slot_key": item["id"],
                "statement": item["statement"],
                "suggested_feedback": item["suggested_feedback"],
            }
            for item in reference["misconceptions"]
        ],
    }


def evidence_data():
    return {
        "prediction_count": 3,
        "correct_prediction_count": 1,
        "modification_attempt_count": 5,
        "hint_request_count": 2,
        "hints_delivered_count": 1,
        "retrieval_answer_count": 2,
        "correct_retrieval_answer_count": 1,
        "verification_error_count": 1,
    }


def request_data(family="notes-v1"):
    reference = reference_definition(family)
    facts = ["request-receiver-contract", "validation-before-persistence", "independent-readback"]
    if family == "tasks-nested-v1":
        facts.append("nested-receiver-shape")
    return {
        "contract_version": "1.0.0",
        "template_family": family,
        "permitted_narrative_variants": ["default-narrative"],
        "requested_objective_slots": [item["id"] for item in reference["objectives"]],
        "requested_misconception_slots": [item["id"] for item in reference["misconceptions"]],
        "approved_prediction_wording": {
            option["id"]: [{"key": "default", "label": option["label"]}]
            for option in reference["checkpoints"][0]["choices"]
        },
        "allowed_instructional_facts": facts,
        "learner_evidence": evidence_data(),
    }


def completion_data(status="success", raw_json=None):
    return {
        "status": status,
        "raw_json": json.dumps(content_data())
        if raw_json is None and status == "success"
        else raw_json,
        "transport": {
            "source": "transport",
            "provider": {"provider_id": "test-transport", "request_id": None},
            "model": {"requested_model_id": "test-model", "returned_model_id": None},
        },
    }
