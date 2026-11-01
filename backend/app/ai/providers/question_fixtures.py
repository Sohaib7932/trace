"""Fixed educational-copy fixtures only; no answers, code or runtime definition.

Local copy IDs match the public Phase 1.1 examples. The default narrative and
wording keys are test fixture references, not a production capability registry.
"""

from types import MappingProxyType

from app.schemas.generation import (
    ExplanationCopy,
    GeneratedChallengeContent,
    MisconceptionCopy,
    ObjectiveCopy,
    PredictionChoiceWording,
    PredictionCopy,
    ProgressiveHints,
)


def _fixture(
    *, title: str, objective_slot: str, objective: str, narrative: str, concept: str
) -> GeneratedChallengeContent:
    return GeneratedChallengeContent(
        contract_version="1.0.0",
        title=title,
        description=(
            "Follow a request from sender to receiving schema. Compare observed evidence "
            "before changing its shape."
        ),
        context_variant="default-narrative",
        objectives=(ObjectiveCopy(slot_key=objective_slot, statement=objective),),
        scenario_narrative=narrative,
        prediction=PredictionCopy(
            prompt="Which outcome do you expect from the displayed request and receiving schema?",
            choice_wording=PredictionChoiceWording(
                rejected="default", saved="default", server_error="default"
            ),
        ),
        investigation_prompt=(
            "Compare outgoing fields with the receiving requirements and describe the mismatch."
        ),
        modification_instructions=(
            "Use one of the supplied mapping choices, then inspect verification evidence."
        ),
        hints=ProgressiveHints(
            orient="Follow the request data from the sender to the receiver.",
            compare="Compare the outgoing field names and structure with the receiving contract.",
            investigate_evidence=(
                "Compare the response with an independent read of committed state."
            ),
        ),
        explanations=ExplanationCopy(
            concept=concept,
            evidence=(
                "An observed response and an independent read provide different pieces of evidence."
            ),
        ),
        misconceptions=(
            MisconceptionCopy(
                slot_key="presence-implies-validity",
                statement=(
                    "The presence of a value alone does not establish that its shape is valid."
                ),
                suggested_feedback=(
                    "Compare the outgoing structure with the receiving contract "
                    "before drawing a conclusion."
                ),
            ),
        ),
    )


COPY_FIXTURES = MappingProxyType(
    {
        "notes-v1": _fixture(
            title="Trace a note request",
            objective_slot="trace-contract",
            objective="Trace a request field through a receiving contract and compare evidence.",
            narrative=(
                "A note-taking application sends a new note to its API. Inspect the supplied "
                "sender and receiving schema before predicting what the API will observe."
            ),
            concept="A receiving contract determines which request fields are accepted.",
        ),
        "tasks-nested-v1": _fixture(
            title="Trace a nested task request",
            objective_slot="trace-nesting",
            objective=(
                "Trace nested request structure through a receiving contract and compare evidence."
            ),
            narrative=(
                "A task application sends a task with a priority value. Inspect how the sender "
                "organizes that value and how the receiving schema describes its nested structure."
            ),
            concept="A receiving contract describes structure as well as field names.",
        ),
    }
)
