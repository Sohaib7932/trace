"""Explicitly test-only complete blueprints; never a production registry.

The unchanged design examples supply test structure/private fixtures only. Their
hypothetical identities and digests are replaced here, the Tasks digest is
finalized first, and the Notes test fixture is explicitly pinned to that target.
No application module imports these helpers or the documentation bundle.
"""

from app.domain.lesson_spec.canonical import finalize_definition
from app.schemas.generation import (
    GeneratedChallengeContent,
    GenerationCompletion,
    GenerationRequest,
)
from app.schemas.generation_admission import AdmissionAccepted
from app.schemas.lesson_composition import CompositionIdentity, TrustedLessonBlueprint
from app.services.challenge_content_admission import ChallengeContentAdmission
from tests.generation_fixtures import (
    completion_data,
    content_data,
    reference_definition,
    request_data,
)

FAMILIES = ("notes-v1", "tasks-nested-v1")


def test_definition(family="notes-v1"):
    """Build fresh fixture values; never trust an example's supplied digest."""
    tasks = reference_definition("tasks-nested-v1")
    tasks["lesson_id"] = "test-blueprint-nested-tasks"
    tasks["version_id"] = "20000000-0000-4000-8000-000000000002"
    tasks["version"] = "0.1.0"
    tasks["content_sha256"] = "0" * 64
    target = finalize_definition(tasks)
    if family == "tasks-nested-v1":
        return target
    if family != "notes-v1":
        raise ValueError("Unknown test fixture family")
    notes = reference_definition("notes-v1")
    notes["lesson_id"] = "test-blueprint-notes"
    notes["version_id"] = "20000000-0000-4000-8000-000000000001"
    notes["version"] = "0.1.0"
    notes["content_sha256"] = "0" * 64
    notes["checkpoints"][4]["target_version"] = {
        "lesson_id": target.lesson_id,
        "version_id": target.version_id,
        "version": target.version,
        "content_sha256": target.content_sha256,
    }
    return finalize_definition(notes)


# Prevent pytest collecting this imported fixture helper as a test case.
test_definition.__test__ = False


def blueprint(family="notes-v1"):
    return TrustedLessonBlueprint(template_family=family, definition=test_definition(family))


def composition_identity(family="notes-v1", **changes):
    data = {
        "lesson_id": "generated-notes-fixture"
        if family == "notes-v1"
        else "generated-tasks-fixture",
        "version_id": (
            "30000000-0000-4000-8000-000000000003"
            if family == "notes-v1"
            else "30000000-0000-4000-8000-000000000004"
        ),
        "version": "1.0.0",
    }
    data.update(changes)
    return CompositionIdentity.model_validate(data)


def admitted_case(family="notes-v1", *, without_misconception=False):
    """Admit deliberately changed copy through the real Phase 2.2 boundary."""
    request = request_data(family)
    request["permitted_narrative_variants"] = ["fixture-context-amber"]
    labels = {
        "rejected": "The receiving contract rejects the request.",
        "saved": "The request is saved successfully.",
        "server_error": "The server fails while handling the request.",
    }
    for outcome, options in request["approved_prediction_wording"].items():
        options.append({"key": "alternate", "label": labels[outcome]})
    content = content_data(family)
    content["title"] = "Investigate the receiving contract"
    content["description"] = (
        "Compare supplied source artifacts before examining independent evidence."
    )
    content["context_variant"] = "fixture-context-amber"
    content["scenario_narrative"] = (
        "A practice application sends a request whose observed behavior needs investigation."
    )
    content["objectives"][0]["statement"] = (
        "Explain the receiving contract using the supplied evidence."
    )
    content["prediction"]["prompt"] = (
        "Which outcome do you expect before investigating the supplied artifacts?"
    )
    content["prediction"]["choice_wording"] = dict.fromkeys(labels, "alternate")
    content["investigation_prompt"] = (
        "Inspect the sender and receiver and describe the relevant contract."
    )
    content["modification_instructions"] = (
        "Select a supplied correction and examine its independent verification evidence."
    )
    content["hints"] = {
        "orient": "Locate the sending request and its receiving contract.",
        "compare": "Compare the supplied fields and their structure.",
        "investigate_evidence": (
            "Read the response and independent committed-state evidence separately."
        ),
    }
    content["explanations"] = {
        "concept": "Compare the supplied structure with the receiving contract.",
        "evidence": "Use independent observations to explain the result.",
    }
    content["misconceptions"][0]["statement"] = (
        "A present value still needs the required receiving structure."
    )
    content["misconceptions"][0]["suggested_feedback"] = (
        "Check the receiving shape before relying on value presence."
    )
    if without_misconception:
        request["requested_misconception_slots"] = []
        content["misconceptions"] = []
    brief = GenerationRequest.model_validate(request)
    body = GeneratedChallengeContent.model_validate(content)
    transport = completion_data()
    transport["raw_json"] = body.model_dump_json()
    result = ChallengeContentAdmission().admit(
        brief, GenerationCompletion.model_validate(transport)
    )
    assert isinstance(result, AdmissionAccepted)
    return brief, result
