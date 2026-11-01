"""Pure composition of admitted copy into a complete server-owned blueprint.

Only the listed assignments below may change blueprint data. The working JSON
tree is a fresh copy of a revalidated blueprint; generated dictionaries are never
merged into it. Every structural identifier and all private configuration remain
blueprint-owned. Finalization validates the whole definition and its full digest.

The core explanation composition rule preserves the complete trusted factual text
verbatim first, then appends '\n\nConcept framing:\n' and the generated concept,
then '\n\nEvidence framing:\n' and generated evidence. Existing Prose bounds apply:
overflow is rejected, never truncated. Retrieval explanations are never rewritten.

There is no registered production blueprint or caller in this milestone. These
interfaces are internal; they neither persist, publish, execute nor expose lessons.
"""

from app.domain.lesson_spec import validate_lesson_spec
from app.domain.lesson_spec.canonical import canonical_bytes, finalize_definition
from app.domain.lesson_spec.fields import Outcome, TransferCheckpoint
from app.schemas.generation import GenerationRequest
from app.schemas.generation_admission import AdmissionAccepted
from app.schemas.lesson_composition import (
    ComposedLessonCandidate,
    CompositionIdentity,
    CompositionMetadata,
    TransferDigestStatus,
    TrustedLessonBlueprint,
)


def _bound_wording(
    request: GenerationRequest, accepted: AdmissionAccepted, blueprint: TrustedLessonBlueprint
) -> dict[Outcome, str]:
    content = accepted.content
    if not request.template_family == accepted.template_family == blueprint.template_family:
        raise ValueError("Composition template families must match")
    if (
        request.contract_version != accepted.contract_version
        or content.contract_version != request.contract_version
    ):
        raise ValueError("Composition contract versions must match")
    if content.context_variant not in request.permitted_narrative_variants:
        raise ValueError("Composition context variant is not permitted by the original request")
    objectives = {item.slot_key for item in content.objectives}
    if objectives != set(request.requested_objective_slots) or not objectives <= {
        item.id for item in blueprint.definition.objectives
    }:
        raise ValueError(
            "Composition objective slots must match the original request and blueprint"
        )
    misconceptions = {item.slot_key for item in content.misconceptions}
    if misconceptions != set(request.requested_misconception_slots) or not misconceptions <= {
        item.id for item in blueprint.definition.misconceptions
    }:
        raise ValueError("Composition misconception slots must match the request and blueprint")
    choices = content.prediction.choice_wording
    approved = request.approved_prediction_wording
    options = {
        "rejected": approved.rejected,
        "saved": approved.saved,
        "server_error": approved.server_error,
    }
    keys: dict[Outcome, str] = {
        "rejected": choices.rejected,
        "saved": choices.saved,
        "server_error": choices.server_error,
    }
    labels: dict[Outcome, str] = {}
    for outcome, key in keys.items():
        matches = [item.label for item in options[outcome] if item.key == key]
        if len(matches) != 1:
            raise ValueError("Composition wording key is not approved for its outcome slot")
        labels[outcome] = matches[0]
    return labels


def _transfer_digest_status(
    blueprint: TrustedLessonBlueprint, target: TrustedLessonBlueprint | None
) -> TransferDigestStatus:
    references = [
        cp.target_version
        for cp in blueprint.definition.checkpoints
        if isinstance(cp, TransferCheckpoint)
    ]
    if not references:
        if target is not None:
            raise ValueError("This blueprint has no transfer target to verify")
        return "not_applicable"
    if target is None:
        return "unavailable"
    verified_target = TrustedLessonBlueprint(
        template_family=target.template_family, definition=target.definition
    )
    if len(references) != 1 or references[0] != verified_target.reference():
        raise ValueError("Trusted transfer target does not match the pinned identity and digest")
    return "verified"


def compose_lesson_spec(
    request: GenerationRequest,
    accepted_content: AdmissionAccepted,
    trusted_blueprint: TrustedLessonBlueprint,
    identity: CompositionIdentity,
    *,
    trusted_transfer_target: TrustedLessonBlueprint | None = None,
) -> ComposedLessonCandidate:
    """Compose a deterministic, digest-verified but runtime-unverified candidate.

    The caller must retain the original server brief and reserve identities. An
    AdmissionAccepted object alone is not evidence of request binding or release
    eligibility; it and the blueprint are revalidated here. Missing transfer
    target definitions are recorded as unavailable; references remain unchanged.
    """
    if not isinstance(request, GenerationRequest) or not isinstance(identity, CompositionIdentity):
        raise ValueError("Composition requires a server-built request and explicit identity")
    if not isinstance(accepted_content, AdmissionAccepted):
        raise ValueError("Composition requires successfully admitted educational copy")
    if not isinstance(trusted_blueprint, TrustedLessonBlueprint):
        raise ValueError("Composition requires a complete trusted blueprint")
    if trusted_transfer_target is not None and not isinstance(
        trusted_transfer_target, TrustedLessonBlueprint
    ):
        raise ValueError("Transfer target must be a complete trusted blueprint")
    request = GenerationRequest.model_validate(request.model_dump(mode="json"), strict=True)
    accepted = AdmissionAccepted.model_validate(
        accepted_content.model_dump(mode="json"), strict=True
    )
    identity = CompositionIdentity.model_validate(identity.model_dump(mode="json"), strict=True)
    blueprint = TrustedLessonBlueprint(
        template_family=trusted_blueprint.template_family, definition=trusted_blueprint.definition
    )
    labels = _bound_wording(request, accepted, blueprint)
    transfer_status = _transfer_digest_status(blueprint, trusted_transfer_target)
    content = accepted.content

    # Fresh, validated server data. Only explicit allowed leaf assignments follow.
    payload = blueprint.definition.model_dump(mode="json")
    payload["lesson_id"] = identity.lesson_id
    payload["version_id"] = identity.version_id
    payload["version"] = identity.version
    payload["title"] = content.title
    payload["summary"] = content.description
    payload["scenario"]["context"] = content.scenario_narrative
    statements = {item.slot_key: item.statement for item in content.objectives}
    for objective in payload["objectives"]:
        if objective["id"] in statements:
            objective["statement"] = statements[objective["id"]]
    payload["checkpoints"][0]["prompt"] = content.prediction.prompt
    for choice in payload["checkpoints"][0]["choices"]:
        choice["label"] = labels[choice["id"]]
    payload["checkpoints"][1]["prompt"] = content.investigation_prompt
    payload["checkpoints"][2]["prompt"] = content.modification_instructions
    hint_copy = {
        1: content.hints.orient,
        2: content.hints.compare,
        3: content.hints.investigate_evidence,
    }
    for hint in payload["hints"]:
        hint["text"] = hint_copy[hint["level"]]
    for explanation in payload["explanations"]:
        if explanation["release_event"] == "core_verification_passed":
            explanation["text"] = (
                explanation["text"]
                + "\n\nConcept framing:\n"
                + content.explanations.concept
                + "\n\nEvidence framing:\n"
                + content.explanations.evidence
            )
    misconceptions_by_id = {item.slot_key: item for item in content.misconceptions}
    for misconception in payload["misconceptions"]:
        generated = misconceptions_by_id.get(misconception["id"])
        if generated is not None:
            misconception["statement"] = generated.statement
            misconception["suggested_feedback"] = generated.suggested_feedback

    # The old digest is only a format-valid placeholder until finalization.
    draft = validate_lesson_spec(payload)
    definition = finalize_definition(draft)
    return ComposedLessonCandidate(
        definition=definition,
        canonical_digest=definition.content_sha256,
        canonical_definition_bytes=canonical_bytes(definition),
        metadata=CompositionMetadata(
            contract_version=request.contract_version,
            admission_policy_version=accepted.admission_policy_version,
            template_family=blueprint.template_family,
            context_variant=content.context_variant,
            blueprint=blueprint.reference(),
            blueprint_runtime_revision=blueprint.definition.private.runtime_binding.revision,
            transfer_target_digest_status=transfer_status,
        ),
    )
