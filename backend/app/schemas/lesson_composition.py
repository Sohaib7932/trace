"""Server-owned composition inputs and internal candidates, never learner DTOs.

A verified digest establishes self-consistency, not authorship or review authority.
Only trusted server code may provide a blueprint; no registry, API, or production
blueprint is supplied here. Documentation examples belong exclusively in tests.
"""

from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from app.domain.generation_copy import TEMPLATE_COPY_SLOTS
from app.domain.lesson_spec import MAX_DEFINITION_BYTES, LessonSpecV1, validate_lesson_spec
from app.domain.lesson_spec.canonical import canonical_bytes, verify_digest
from app.domain.lesson_spec.fields import (
    Digest,
    LessonId,
    LocalId,
    No,
    Value,
    Version,
    VersionId,
    VersionReference,
)
from app.schemas.generation import ContractVersion, TemplateFamily
from app.schemas.generation_admission import AdmissionPolicyVersion

type TransferDigestStatus = Literal["not_applicable", "verified", "unavailable"]


class CompositionIdentity(Value):
    """Explicit server-reserved identity; allocation/uniqueness is the caller's job."""

    lesson_id: LessonId
    version_id: VersionId
    version: Version


class TrustedLessonBlueprint(Value):
    template_family: TemplateFamily
    definition: LessonSpecV1 = Field(repr=False)

    @field_validator("definition", mode="before")
    @classmethod
    def complete_server_definition(cls, value: object) -> LessonSpecV1:
        if not isinstance(value, LessonSpecV1):
            raise ValueError("Blueprint requires a validated server-owned LessonSpecV1")
        # Canonicalization checks the original typed values before serialization;
        # fresh parsing also avoids trusting Pydantic's existing-instance shortcut.
        return validate_lesson_spec(canonical_bytes(value))

    @model_validator(mode="after")
    def reviewed_destinations(self) -> Self:
        definition = self.definition
        if definition.private.runtime_binding.template_id != self.template_family:
            raise ValueError("Blueprint template family does not match its runtime binding")
        if not verify_digest(definition):
            raise ValueError("Blueprint digest is not verified")
        slots = TEMPLATE_COPY_SLOTS[self.template_family]
        if {item.id for item in definition.objectives} != slots.objectives:
            raise ValueError(
                "Blueprint objective destinations must match the registered copy slots"
            )
        if {item.id for item in definition.misconceptions} != slots.misconceptions:
            raise ValueError(
                "Blueprint misconception destinations must match registered copy slots"
            )
        if {hint.level for hint in definition.hints} != {1, 2, 3}:
            raise ValueError("Blueprint requires exactly three progressive hint destinations")
        core = [
            item
            for item in definition.explanations
            if item.release_event == "core_verification_passed"
        ]
        if len(core) != 1:
            raise ValueError("Blueprint requires exactly one trusted core explanation")
        return self

    def reference(self) -> VersionReference:
        return VersionReference(
            lesson_id=self.definition.lesson_id,
            version_id=self.definition.version_id,
            version=self.definition.version,
            content_sha256=self.definition.content_sha256,
        )


class CompositionMetadata(Value):
    contract_version: ContractVersion
    admission_policy_version: AdmissionPolicyVersion
    template_family: TemplateFamily
    context_variant: LocalId
    blueprint: VersionReference
    blueprint_runtime_revision: Literal["1.0.0"]
    transfer_target_digest_status: TransferDigestStatus


class ComposedLessonCandidate(Value):
    """An internal definition snapshot. Nothing here authorizes release or execution."""

    state: Literal["composed_unverified"] = "composed_unverified"
    release_eligible: No = False
    definition: LessonSpecV1 = Field(repr=False)
    canonical_digest: Digest = Field(repr=False)
    canonical_definition_bytes: Annotated[
        bytes, Field(min_length=1, max_length=MAX_DEFINITION_BYTES)
    ] = Field(repr=False)
    metadata: CompositionMetadata = Field(repr=False)

    @field_validator("definition", mode="before")
    @classmethod
    def fresh_definition(cls, value: object) -> LessonSpecV1:
        if isinstance(value, LessonSpecV1):
            return validate_lesson_spec(canonical_bytes(value))
        return validate_lesson_spec(value)

    @model_validator(mode="after")
    def verified_snapshot(self) -> Self:
        if self.canonical_digest != self.definition.content_sha256 or not verify_digest(
            self.definition
        ):
            raise ValueError("Candidate digest does not match its definition")
        if self.canonical_definition_bytes != canonical_bytes(self.definition):
            raise ValueError("Candidate canonical bytes do not match its definition")
        if self.metadata.template_family != self.definition.private.runtime_binding.template_id:
            raise ValueError("Candidate metadata does not match its template family")
        return self
