"""Internal generation -> admission -> composition -> persisted runtime validation.

No public generation endpoint, release decision, lesson registration or assignment.
The application-owned orchestrator serializes local retries before provider work;
database uniqueness/transactions remain authoritative across processes.
"""

from threading import RLock
from uuid import UUID

from app.ai.question_generator import QuestionGenerator
from app.domain.learning import LearningError
from app.domain.lesson_spec.canonical import canonical_bytes
from app.schemas.candidate_lifecycle import CandidateHistory, json_digest
from app.schemas.generation import GenerationRequest
from app.schemas.lesson_composition import CompositionIdentity, TrustedLessonBlueprint
from app.services.candidate_lifecycle import CandidateLifecycleService


def request_from_blueprint(blueprint: TrustedLessonBlueprint) -> GenerationRequest:
    """Derive copy slots/wording only from a validated server-owned definition."""
    trusted = TrustedLessonBlueprint(
        template_family=blueprint.template_family, definition=blueprint.definition
    )
    definition = trusted.definition
    prediction = definition.checkpoints[0]
    # Both supported V1 topologies begin with a prediction checkpoint.
    if prediction.type != "prediction":
        raise LearningError("generation_rejected", "Blueprint lacks its prediction checkpoint.")
    facts = ["request-receiver-contract", "validation-before-persistence", "independent-readback"]
    if trusted.template_family == "tasks-nested-v1":
        facts.append("nested-receiver-shape")
    return GenerationRequest.model_validate(
        {
            "contract_version": "1.0.0",
            "template_family": trusted.template_family,
            "permitted_narrative_variants": ["default-narrative"],
            "requested_objective_slots": [item.id for item in definition.objectives],
            "requested_misconception_slots": [item.id for item in definition.misconceptions],
            "approved_prediction_wording": {
                choice.id: [{"key": "blueprint-wording", "label": choice.label}]
                for choice in prediction.choices
            },
            "allowed_instructional_facts": facts,
        }
    )


class CandidateGenerationService:
    def __init__(self, generator: QuestionGenerator, lifecycle: CandidateLifecycleService) -> None:
        self.generator, self.lifecycle = generator, lifecycle
        self._lock = RLock()

    def generate_and_validate(
        self,
        *,
        generation_request_id: str,
        creation_key: str,
        validation_key: str,
        request: GenerationRequest,
        blueprint: TrustedLessonBlueprint,
        identity: CompositionIdentity,
        transfer_target: TrustedLessonBlueprint | None = None,
    ) -> CandidateHistory:
        for identifier in (generation_request_id, creation_key, validation_key):
            UUID(identifier)
        request = GenerationRequest.model_validate_json(request.model_dump_json(warnings=False))
        blueprint = TrustedLessonBlueprint(
            template_family=blueprint.template_family, definition=blueprint.definition
        )
        identity = CompositionIdentity.model_validate(identity.model_dump(warnings=False))
        if transfer_target is not None:
            transfer_target = TrustedLessonBlueprint(
                template_family=transfer_target.template_family,
                definition=transfer_target.definition,
            )
        with self._lock:
            with self.lifecycle.repository.read() as store:
                history = store.by_creation_key(creation_key)
                occupied = store.get(identity.version_id)
            if history is not None:
                snapshot = history.snapshot
                target_json = (
                    canonical_bytes(transfer_target.definition).decode()
                    if transfer_target
                    else None
                )
                if (
                    snapshot.generation_request_id != generation_request_id
                    or snapshot.identity != identity
                    or snapshot.request_sha256 != json_digest(request.model_dump(mode="json"))
                    or snapshot.source_blueprint != blueprint.reference()
                    or snapshot.transfer_target_json != target_json
                ):
                    raise LearningError("conflict", "The generation key belongs to another input.")
            else:
                if occupied is not None:
                    raise LearningError("conflict", "The candidate identity is already reserved.")
                # No database transaction is held during the provider call.
                completion = self.generator.generate(request)
                producer = completion.transport.provider.provider_id
                if producer not in {"gemini", "mock", "fake-question-generator-test-fixture"}:
                    raise LearningError("generation_rejected", "Unapproved generation provenance.")
                history = self.lifecycle.create(
                    generation_request_id=generation_request_id,
                    key=creation_key,
                    request=request,
                    completion=completion,
                    blueprint=blueprint,
                    identity=identity,
                    transfer_target=transfer_target,
                    generation_origin="provider" if producer == "gemini" else "mock",
                )
            already_validated = any(
                event.operation_key == validation_key for event in history.events
            )
            if history.state in {"composed", "validation_unavailable"} and not already_validated:
                self.lifecycle.validate(
                    history.snapshot.id, key=validation_key, expected_revision=history.revision
                )
                history = self.lifecycle.get(history.snapshot.id)
            return history
