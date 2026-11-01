"""Offline inputs over independently authored blueprint candidates, not fixture definitions."""

import json
from datetime import UTC, datetime
from uuid import uuid4

from app.blueprints.candidates import notes_blueprint_candidate, tasks_blueprint_candidate
from app.domain.accounts import Account
from app.schemas.generation import GenerationCompletion, GenerationRequest
from app.schemas.lesson_composition import CompositionIdentity

NOW = datetime(2026, 11, 1, tzinfo=UTC)


def inputs(family="tasks-nested-v1", *, generation_origin="mock"):
    envelope = notes_blueprint_candidate() if family == "notes-v1" else tasks_blueprint_candidate()
    source = envelope.trusted_blueprint()
    definition = source.definition
    request = GenerationRequest.model_validate(
        {
            "contract_version": "1.0.0",
            "template_family": family,
            "permitted_narrative_variants": ["default-narrative"],
            "requested_objective_slots": [o.id for o in definition.objectives],
            "requested_misconception_slots": [m.id for m in definition.misconceptions],
            "approved_prediction_wording": {
                c.id: [{"key": "default", "label": c.label}]
                for c in definition.checkpoints[0].choices
            },
            "allowed_instructional_facts": ["request-receiver-contract", "independent-readback"],
            "learner_evidence": None,
        }
    )
    copy = {
        "contract_version": "1.0.0",
        "title": definition.title,
        "description": definition.summary,
        "context_variant": "default-narrative",
        "objectives": [{"slot_key": o.id, "statement": o.statement} for o in definition.objectives],
        "scenario_narrative": definition.scenario.context,
        "prediction": {
            "prompt": definition.checkpoints[0].prompt,
            "choice_wording": {
                "rejected": "default",
                "saved": "default",
                "server_error": "default",
            },
        },
        "investigation_prompt": definition.checkpoints[1].prompt,
        "modification_instructions": definition.checkpoints[2].prompt,
        "hints": dict(
            zip(
                ["orient", "compare", "investigate_evidence"],
                [h.text for h in definition.hints],
                strict=True,
            )
        ),
        "explanations": {
            "concept": "The receiving contract determines the required shape.",
            "evidence": "Compare HTTP observations with independent readback.",
        },
        "misconceptions": [
            {"slot_key": m.id, "statement": m.statement, "suggested_feedback": m.suggested_feedback}
            for m in definition.misconceptions
        ],
    }
    completion = GenerationCompletion.model_validate(
        {
            "status": "success",
            "raw_json": json.dumps(copy),
            "transport": {
                "source": "transport",
                "provider": {"provider_id": "offline-transport-double", "request_id": None},
                "model": {"requested_model_id": None, "returned_model_id": None},
            },
        }
    )
    return dict(
        generation_request_id=str(uuid4()),
        key=str(uuid4()),
        request=request,
        completion=completion,
        blueprint=source,
        identity=CompositionIdentity(
            lesson_id=definition.lesson_id, version_id=str(uuid4()), version="1.2.0"
        ),
        transfer_target=tasks_blueprint_candidate().trusted_blueprint()
        if family == "notes-v1"
        else None,
        generation_origin=generation_origin,
    )


def admin(identifier=None):
    return Account(identifier or uuid4(), NOW, "active", ("admin",))
