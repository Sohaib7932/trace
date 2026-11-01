"""Internal candidate-gate results, never publication authority or learner DTOs."""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, StrictBool, model_validator

from app.domain.lesson_spec.fields import CheckCode, Digest, Items, No, Value, plain_text
from app.schemas.lesson_composition import CompositionIdentity

CHECK_CODES = frozenset({"http_status", "api_response", "validation", "row_count", "stored_values"})
type ValidationStageName = Literal["integrity", "structure", "configuration", "runtime"]
type CandidateValidationStatus = Literal["invalid", "runtime_failed", "unavailable", "validated"]
STAGES: tuple[ValidationStageName, ...] = ("integrity", "structure", "configuration", "runtime")


class CandidateValidationCode(StrEnum):
    CANDIDATE_SCHEMA_INVALID = "candidate_schema_invalid"
    CANDIDATE_STATE_INVALID = "candidate_state_invalid"
    CANDIDATE_DIGEST_INVALID = "candidate_digest_invalid"
    CANDIDATE_DIGEST_MISMATCH = "candidate_digest_mismatch"
    CANDIDATE_BYTES_MISMATCH = "candidate_bytes_mismatch"
    CANDIDATE_IDENTITY_MISMATCH = "candidate_identity_mismatch"
    CANDIDATE_METADATA_MISMATCH = "candidate_metadata_mismatch"
    STRUCTURE_INVALID = "structure_invalid"
    TRANSFER_TARGET_UNAVAILABLE = "transfer_target_unavailable"
    TRANSFER_TARGET_MISMATCH = "transfer_target_mismatch"
    TRUSTED_CONTEXT_INVALID = "trusted_context_invalid"
    TRUSTED_CONFIGURATION_CHANGED = "trusted_configuration_changed"
    COMPOSITION_MISMATCH = "composition_mismatch"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    RUNTIME_TIMEOUT = "runtime_timeout"
    RUNTIME_EXCEPTION = "runtime_exception"
    RUNTIME_EXECUTION_FAILED = "runtime_execution_failed"
    RUNTIME_EVIDENCE_FAILED = "runtime_evidence_failed"
    RUNTIME_REPORT_INVALID = "runtime_report_invalid"


class RuntimeEvidenceCheck(Value):
    code: CheckCode
    passed: StrictBool


class RuntimeProfileEvidence(Value):
    profile: Literal["baseline", "repair"]
    checks: Items[RuntimeEvidenceCheck] = Field(min_length=5, max_length=5)
    evaluation_matched: StrictBool

    @model_validator(mode="after")
    def all_categories(self) -> Self:
        if {check.code for check in self.checks} != CHECK_CODES:
            raise ValueError("Every runtime profile requires all five distinct evidence categories")
        return self


class RuntimeValidationReport(Value):
    status: Literal["passed", "failed", "unavailable"]
    code: CandidateValidationCode | None
    performed: StrictBool
    completed: StrictBool
    profiles: Items[RuntimeProfileEvidence] = Field(default=(), max_length=2)

    @model_validator(mode="after")
    def honest_runtime_outcome(self) -> Self:
        names = [profile.profile for profile in self.profiles]
        if len(names) != len(set(names)):
            raise ValueError("Runtime profile outcomes must be unique")
        if self.completed and (not self.performed or set(names) != {"baseline", "repair"}):
            raise ValueError("Completed runtime validation requires both executed profiles")
        if self.profiles and not self.performed:
            raise ValueError("Runtime evidence requires an executed observation")
        if self.status == "passed":
            if (
                not self.completed
                or self.code is not None
                or not all(
                    profile.evaluation_matched and all(check.passed for check in profile.checks)
                    for profile in self.profiles
                )
            ):
                raise ValueError("Runtime success requires complete matching evidence")
        elif self.code is None:
            raise ValueError("Unsuccessful runtime validation requires a failure code")
        if self.status == "unavailable" and self.completed:
            raise ValueError("Unavailable runtime validation cannot claim completion")
        return self


class ValidationStageResult(Value):
    stage: ValidationStageName
    status: Literal["passed", "failed", "unavailable", "skipped"]
    code: CandidateValidationCode | None = None

    @model_validator(mode="after")
    def explicit_stage_failure(self) -> Self:
        if (self.status in {"failed", "unavailable"}) != (self.code is not None):
            raise ValueError("Only a failed or unavailable stage has a failure code")
        return self


class CandidateValidationResult(Value):
    """This gate's outcome; even successful candidates remain ineligible for release."""

    validation_policy_version: Literal["1.0.0"] = "1.0.0"
    identity: CompositionIdentity | None
    content_sha256: Digest | None = Field(repr=False)
    status: CandidateValidationStatus
    code: CandidateValidationCode | None
    summary: Annotated[str, Field(min_length=1, max_length=200), AfterValidator(plain_text)]
    stages: Items[ValidationStageResult] = Field(min_length=4, max_length=4)
    runtime_verification_performed: StrictBool = False
    runtime_verification_completed: StrictBool = False
    runtime_evidence: Items[RuntimeProfileEvidence] = Field(default=(), max_length=2, repr=False)
    release_eligible: No = False

    @model_validator(mode="after")
    def fail_closed_outcome(self) -> Self:
        if tuple(stage.stage for stage in self.stages) != STAGES:
            raise ValueError("Validation stages must follow the complete fixed gate order")
        if self.status == "validated":
            if self.identity is None or self.content_sha256 is None or self.code is not None:
                raise ValueError("Successful validation requires identity and a verified digest")
            if any(stage.status != "passed" for stage in self.stages):
                raise ValueError("Successful validation cannot skip a required stage")
            RuntimeValidationReport(
                status="passed",
                code=None,
                performed=self.runtime_verification_performed,
                completed=self.runtime_verification_completed,
                profiles=self.runtime_evidence,
            )
        elif self.code is None or all(stage.status == "passed" for stage in self.stages):
            raise ValueError("Unsuccessful validation requires an explicit failing stage and code")
        if self.runtime_verification_completed and not self.runtime_verification_performed:
            raise ValueError("Runtime completion requires execution")
        return self
