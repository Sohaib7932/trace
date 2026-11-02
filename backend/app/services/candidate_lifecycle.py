"""Explicit internal candidate lifecycle. Nothing here publishes or assigns lessons.

Entry is a captured generation completion: admission and composition must succeed
before any candidate row exists. Rejected admission creates no invalid-definition
row; later technical rejection receipts are durable audit events. Provider calls
and their job/idempotency orchestration are outside this service. Human review and
source-digest attestation record explicit decisions, never a production registry
entry, learner assignment, or release eligibility.

Provider origin is an explicit assertion by a trusted server caller, never an
inference from a provider name or a public input. Current application mock/disabled
modes produce no live-provider attestation; production approval rejects mock origin.
"""

import hashlib
from typing import Any, Literal, cast
from uuid import uuid4

from app.domain.accounts import Account
from app.domain.clock import Clock, as_utc, utc_now
from app.domain.learning import LearningError
from app.domain.lesson_spec.canonical import canonical_bytes
from app.repositories.candidates import CandidateRepository
from app.schemas.candidate_lifecycle import (
    CandidateAction,
    CandidateEvent,
    CandidateHistory,
    CandidateSnapshot,
    CandidateState,
    json_digest,
)
from app.schemas.candidate_validation import CandidateValidationResult
from app.schemas.generation import GenerationCompletion, GenerationRequest
from app.schemas.generation_admission import AdmissionAccepted
from app.schemas.lesson_composition import CompositionIdentity, TrustedLessonBlueprint
from app.services.candidate_validation import CandidateValidationService
from app.services.challenge_content_admission import ChallengeContentAdmission
from app.services.lesson_composition import compose_lesson_spec


class CandidateLifecycleService:
    def __init__(
        self,
        repository: CandidateRepository,
        validator: CandidateValidationService,
        clock: Clock = utc_now,
    ) -> None:
        self.repository, self.validator, self.clock = repository, validator, clock

    def get(self, candidate_id: str) -> CandidateHistory:
        with self.repository.read() as store:
            result = store.get(candidate_id)
        if result is None:
            raise LearningError("not_found", "Candidate not found.")
        return result

    def create(
        self,
        *,
        generation_request_id: str,
        key: str,
        request: GenerationRequest,
        completion: GenerationCompletion,
        blueprint: TrustedLessonBlueprint,
        identity: CompositionIdentity,
        transfer_target: TrustedLessonBlueprint | None = None,
        generation_origin: Literal["mock", "provider"] = "mock",
    ) -> CandidateHistory:
        # Admission and composition stay authoritative. Raw output is hashed, never retained.
        request = GenerationRequest.model_validate_json(request.model_dump_json(warnings=False))
        completion = GenerationCompletion.model_validate_json(
            completion.model_dump_json(warnings=False)
        )
        if generation_origin == "provider" and (
            completion.transport.provider.provider_id in {"mock", "fake", "unconfigured"}
            or completion.transport.provider.provider_id.startswith(("fake-", "mock-"))
        ):
            raise LearningError("conflict", "Fixture transport cannot attest live provider origin.")
        accepted = ChallengeContentAdmission().admit(request, completion)
        if not isinstance(accepted, AdmissionAccepted):
            raise LearningError("generation_rejected", "Generated content was not admitted.")
        candidate = compose_lesson_spec(
            request,
            accepted,
            blueprint,
            identity,
            trusted_transfer_target=transfer_target,
        )
        values: dict[str, object] = dict(
            id=identity.version_id,
            generation_request_id=generation_request_id,
            creation_key=key,
            created_at=as_utc(self.clock()),
            identity=identity,
            generation_origin=generation_origin,
            source_blueprint=blueprint.reference(),
            request_json=request.model_dump_json(),
            admitted_json=accepted.model_dump_json(),
            blueprint_json=canonical_bytes(blueprint.definition).decode("utf-8"),
            transfer_target_json=(
                canonical_bytes(transfer_target.definition).decode("utf-8")
                if transfer_target is not None
                else None
            ),
            definition_json=candidate.canonical_definition_bytes.decode("utf-8"),
            metadata=candidate.metadata,
            transport=completion.transport,
            raw_output_sha256=hashlib.sha256(
                (completion.raw_json or "").encode("utf-8")
            ).hexdigest(),
            request_sha256=json_digest(request.model_dump(mode="json")),
            admitted_sha256=json_digest(accepted.model_dump(mode="json")),
            composition_sha256="0" * 64,
        )
        # This local draft only calculates a hash; the complete payload is strictly
        # validated immediately below and the unchecked draft is never persisted.
        draft = CandidateSnapshot.model_construct(**cast(dict[str, Any], values))
        values["composition_sha256"] = draft.composition_fingerprint()
        snapshot = CandidateSnapshot.model_validate(values)
        command = json_digest(
            {
                "request_id": generation_request_id,
                "composition": snapshot.composition_sha256,
            }
        )
        with self.repository.write() as store:
            existing = store.by_creation_key(key)
            if existing is not None:
                if existing.events[0].command_sha256 != command:
                    raise LearningError(
                        "conflict", "Creation key belongs to different candidate inputs."
                    )
                return existing
            event = CandidateEvent(
                id=str(uuid4()),
                candidate_id=snapshot.id,
                revision=0,
                operation_key=key,
                command_sha256=command,
                action="created",
                previous_state=None,
                state="composed",
                created_at=snapshot.created_at,
                reason="Admitted content composed with trusted source.",
            )
            store.insert(snapshot, event)
            result = store.get(snapshot.id)
            assert result is not None
            return result

    @staticmethod
    def _prior(history: CandidateHistory, key: str, command: str) -> CandidateEvent | None:
        existing = next((event for event in history.events if event.operation_key == key), None)
        if existing is not None and existing.command_sha256 != command:
            raise LearningError("conflict", "Operation key belongs to another candidate action.")
        return existing

    def validate(self, candidate_id: str, *, key: str, expected_revision: int) -> CandidateEvent:
        command = json_digest({"action": "validation", "expected_revision": expected_revision})
        history = self.get(candidate_id)
        prior = self._prior(history, key, command)
        if prior is not None:
            return prior
        if history.revision != expected_revision or history.state not in {
            "composed",
            "validation_unavailable",
        }:
            raise LearningError(
                "conflict", "Candidate is not available for this validation revision."
            )
        candidate, request, accepted, blueprint, identity, target = history.snapshot.context()
        # This may execute the isolated runtime, and MUST stay outside repository.write().
        receipt = self.validator.validate(
            candidate,
            request,
            accepted,
            blueprint,
            identity,
            trusted_transfer_target=target,
        )
        receipt = CandidateValidationResult.model_validate_json(
            receipt.model_dump_json(warnings=False)
        )
        if receipt.identity != identity or receipt.content_sha256 != candidate.canonical_digest:
            raise LearningError("conflict", "Validation receipt belongs to another candidate.")
        state: CandidateState = (
            "validated"
            if receipt.status == "validated"
            else "validation_unavailable"
            if receipt.status == "unavailable"
            else "rejected"
        )
        event = CandidateEvent(
            id=str(uuid4()),
            candidate_id=candidate_id,
            revision=expected_revision + 1,
            operation_key=key,
            command_sha256=command,
            action="validation",
            previous_state=history.state,
            state=state,
            created_at=as_utc(self.clock()),
            reason=receipt.summary,
            validation=receipt,
        )
        return self._append(event, expected_revision)

    def _append(self, event: CandidateEvent, expected_revision: int) -> CandidateEvent:
        with self.repository.write() as store:
            current = store.get(event.candidate_id)
            if current is None:
                raise LearningError("not_found", "Candidate not found.")
            prior = self._prior(current, event.operation_key, event.command_sha256)
            if prior is not None:
                return prior
            store.append(event, expected_revision)
        return event

    def decide(
        self,
        candidate_id: str,
        *,
        account: Account,
        action: CandidateAction,
        reason: str,
        key: str,
        expected_revision: int,
        reviewed_blueprint_sha256: str | None = None,
    ) -> CandidateEvent:
        account.require_role("admin")
        if action not in {"human_review", "production_approval", "reject"}:
            raise LearningError("invalid_state", "Use an explicit human review decision.")
        command = json_digest(
            {
                "action": action,
                "actor": str(account.id),
                "reason": reason,
                "expected_revision": expected_revision,
                "blueprint": reviewed_blueprint_sha256,
            }
        )
        history = self.get(candidate_id)
        prior = self._prior(history, key, command)
        if prior is not None:
            return prior
        required = "validated" if action == "human_review" else "human_reviewed"
        if history.revision != expected_revision or (
            history.state not in {"validated", "human_reviewed"}
            if action == "reject"
            else history.state != required
        ):
            raise LearningError("conflict", "Candidate review requires the matching prior state.")
        if action == "production_approval" and (
            reviewed_blueprint_sha256 != history.snapshot.source_blueprint.content_sha256
        ):
            raise LearningError(
                "conflict", "Production review must attest the exact source blueprint."
            )
        if action == "production_approval" and history.snapshot.generation_origin == "mock":
            raise LearningError("conflict", "Mock generation cannot receive production approval.")
        state: CandidateState = (
            "human_reviewed"
            if action == "human_review"
            else "production_approved"
            if action == "production_approval"
            else "rejected"
        )
        return self._append(
            CandidateEvent(
                id=str(uuid4()),
                candidate_id=candidate_id,
                revision=expected_revision + 1,
                operation_key=key,
                command_sha256=command,
                action=action,
                previous_state=history.state,
                state=state,
                created_at=as_utc(self.clock()),
                actor_id=str(account.id),
                reason=reason,
                reviewed_blueprint_sha256=reviewed_blueprint_sha256,
            ),
            expected_revision,
        )
