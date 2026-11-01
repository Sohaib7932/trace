"""Independent, internal candidate gate; no learner workflow or release path.

Integrity uses the existing strict definition/canonicalization models, so malformed
structure can fail at the first stage. The reference stage additionally resolves
and verifies pinned transfer dependencies. Configuration checks are independent of
composition: every protected leaf is compared with the server blueprint, including
the trusted factual explanation prefix. Recomposition then checks the original
brief/copy/identity binding; it is not the sole protection of runtime configuration.

Only the injected exercise runtime may execute trusted applications. This service
does not import the application database, verification-session service, or provider.
All results are internal and remain release_eligible=False.
"""

from pydantic import TypeAdapter

from app.domain.lesson_spec import LessonSpecV1, validate_lesson_spec
from app.domain.lesson_spec.canonical import canonical_bytes, verify_digest
from app.domain.lesson_spec.fields import Digest, TransferCheckpoint
from app.repositories.candidate_validation import CandidateRuntime
from app.schemas.candidate_validation import (
    STAGES,
    CandidateValidationResult,
    CandidateValidationStatus,
    RuntimeValidationReport,
    ValidationStageName,
    ValidationStageResult,
)
from app.schemas.candidate_validation import (
    CandidateValidationCode as Code,
)
from app.schemas.generation import GenerationRequest
from app.schemas.generation_admission import AdmissionAccepted
from app.schemas.lesson_composition import (
    ComposedLessonCandidate,
    CompositionIdentity,
    TrustedLessonBlueprint,
)
from app.services.lesson_composition import compose_lesson_spec

_MESSAGES = {
    Code.CANDIDATE_SCHEMA_INVALID: "The candidate does not satisfy the composed-candidate schema.",
    Code.CANDIDATE_STATE_INVALID: "Only an unverified composed candidate can enter this gate.",
    Code.CANDIDATE_DIGEST_INVALID: "The candidate requires well-formed canonical digests.",
    Code.CANDIDATE_DIGEST_MISMATCH: "The candidate content does not match its canonical digest.",
    Code.CANDIDATE_BYTES_MISMATCH: (
        "The candidate snapshot does not match the canonical definition."
    ),
    Code.CANDIDATE_IDENTITY_MISMATCH: (
        "The candidate identity does not match its reserved identity."
    ),
    Code.CANDIDATE_METADATA_MISMATCH: "Composition metadata does not match the trusted context.",
    Code.STRUCTURE_INVALID: "The definition has invalid structure or component references.",
    Code.TRANSFER_TARGET_UNAVAILABLE: "The pinned transfer definition is unavailable.",
    Code.TRANSFER_TARGET_MISMATCH: "The transfer definition does not match its pinned reference.",
    Code.TRUSTED_CONTEXT_INVALID: "Trusted validation context is unavailable or invalid.",
    Code.TRUSTED_CONFIGURATION_CHANGED: "The candidate changed protected blueprint configuration.",
    Code.COMPOSITION_MISMATCH: "The candidate does not match the original admitted composition.",
    Code.RUNTIME_UNAVAILABLE: "The isolated exercise runtime or its evidence is unavailable.",
    Code.RUNTIME_TIMEOUT: "Isolated runtime verification did not finish within its timeout.",
    Code.RUNTIME_EXCEPTION: "The isolated runtime raised an execution error.",
    Code.RUNTIME_EXECUTION_FAILED: "The trusted exercise application did not execute successfully.",
    Code.RUNTIME_EVIDENCE_FAILED: "Observed runtime evidence did not match the trusted profiles.",
    Code.RUNTIME_REPORT_INVALID: "The runtime did not supply a complete valid verification report.",
}
_RUNTIME_CODES = frozenset(
    {
        Code.RUNTIME_UNAVAILABLE,
        Code.RUNTIME_TIMEOUT,
        Code.RUNTIME_EXCEPTION,
        Code.RUNTIME_EXECUTION_FAILED,
        Code.RUNTIME_EVIDENCE_FAILED,
        Code.RUNTIME_REPORT_INVALID,
    }
)


class _Rejected(ValueError):
    def __init__(self, code: Code) -> None:
        self.code = code


def _integrity(candidate: object) -> ComposedLessonCandidate:
    if isinstance(candidate, ComposedLessonCandidate):
        # Preserve typed definition/bytes while rebuilding all envelope metadata.
        data = {
            "state": candidate.state,
            "release_eligible": candidate.release_eligible,
            "definition": candidate.definition,
            "canonical_digest": candidate.canonical_digest,
            "canonical_definition_bytes": candidate.canonical_definition_bytes,
            "metadata": candidate.metadata.model_dump(mode="json"),
        }
    elif isinstance(candidate, dict):
        data = dict(candidate)
    else:
        raise _Rejected(Code.CANDIDATE_SCHEMA_INVALID)
    if data.get("state") != "composed_unverified":
        raise _Rejected(Code.CANDIDATE_STATE_INVALID)
    value = data.get("definition")
    supplied = (
        value.content_sha256
        if isinstance(value, LessonSpecV1)
        else (value.get("content_sha256") if isinstance(value, dict) else None)
    )
    try:
        TypeAdapter(Digest).validate_python(supplied, strict=True)
        TypeAdapter(Digest).validate_python(data.get("canonical_digest"), strict=True)
    except ValueError as exc:
        raise _Rejected(Code.CANDIDATE_DIGEST_INVALID) from exc
    try:
        definition = (
            validate_lesson_spec(canonical_bytes(value))
            if isinstance(value, LessonSpecV1)
            else validate_lesson_spec(value)
        )
    except (ValueError, TypeError, RecursionError) as exc:
        raise _Rejected(Code.CANDIDATE_SCHEMA_INVALID) from exc
    if not verify_digest(definition) or data.get("canonical_digest") != definition.content_sha256:
        raise _Rejected(Code.CANDIDATE_DIGEST_MISMATCH)
    if data.get("canonical_definition_bytes") != canonical_bytes(definition):
        raise _Rejected(Code.CANDIDATE_BYTES_MISMATCH)
    data["definition"] = definition
    try:
        return ComposedLessonCandidate.model_validate(data, strict=True)
    except (ValueError, TypeError, RecursionError) as exc:
        raise _Rejected(Code.CANDIDATE_SCHEMA_INVALID) from exc


def _identity(candidate: ComposedLessonCandidate) -> CompositionIdentity:
    return CompositionIdentity(
        lesson_id=candidate.definition.lesson_id,
        version_id=candidate.definition.version_id,
        version=candidate.definition.version,
    )


def _protected_view(definition: LessonSpecV1) -> dict[str, object]:
    """Remove only authorized copy/identity leaves; retain every structural value."""
    value = definition.model_dump(mode="json")
    for key in ("lesson_id", "version_id", "version", "content_sha256", "title", "summary"):
        del value[key]
    del value["scenario"]["context"]
    for item in value["objectives"]:
        del item["statement"]
    for checkpoint in value["checkpoints"][:3]:
        del checkpoint["prompt"]
        if checkpoint["type"] == "prediction":
            for choice in checkpoint["choices"]:
                del choice["label"]
    for hint in value["hints"]:
        del hint["text"]
    for explanation in value["explanations"]:
        if explanation["release_event"] == "core_verification_passed":
            del explanation["text"]
    for misconception in value["misconceptions"]:
        del misconception["statement"]
        del misconception["suggested_feedback"]
    return value


def _dependencies(
    candidate: ComposedLessonCandidate, target: TrustedLessonBlueprint | None
) -> None:
    validate_lesson_spec(canonical_bytes(candidate.definition))
    pins = [
        cp.target_version
        for cp in candidate.definition.checkpoints
        if isinstance(cp, TransferCheckpoint)
    ]
    if not pins:
        if target is not None:
            raise _Rejected(Code.TRANSFER_TARGET_MISMATCH)
        return
    if target is None:
        raise _Rejected(Code.TRANSFER_TARGET_UNAVAILABLE)
    try:
        checked = TrustedLessonBlueprint(
            template_family=target.template_family, definition=target.definition
        )
    except (ValueError, TypeError, AttributeError) as exc:
        raise _Rejected(Code.TRANSFER_TARGET_MISMATCH) from exc
    if len(pins) != 1 or pins[0] != checked.reference():
        raise _Rejected(Code.TRANSFER_TARGET_MISMATCH)


def _result(
    candidate: ComposedLessonCandidate | None,
    stage: ValidationStageName | None,
    status: CandidateValidationStatus,
    code: Code | None,
    report: RuntimeValidationReport | None = None,
) -> CandidateValidationResult:
    failed_at = STAGES.index(stage) if stage is not None else len(STAGES)
    stages = tuple(
        ValidationStageResult(
            stage=name,
            status="passed"
            if index < failed_at
            else ("unavailable" if status == "unavailable" else "failed")
            if index == failed_at
            else "skipped",
            code=code if index == failed_at else None,
        )
        for index, name in enumerate(STAGES)
    )
    return CandidateValidationResult(
        identity=_identity(candidate) if candidate is not None else None,
        content_sha256=candidate.canonical_digest if candidate is not None else None,
        status=status,
        code=code,
        summary=_MESSAGES[code]
        if code is not None
        else "The candidate passed this validation gate; release remains disabled.",
        stages=stages,
        runtime_verification_performed=report.performed if report else False,
        runtime_verification_completed=report.completed if report else False,
        runtime_evidence=report.profiles if report else (),
    )


class CandidateValidationService:
    def __init__(self, runtime: CandidateRuntime | None = None) -> None:
        self.runtime = runtime

    def validate(
        self,
        candidate: object,
        request: GenerationRequest,
        accepted_content: AdmissionAccepted,
        trusted_blueprint: TrustedLessonBlueprint,
        identity: CompositionIdentity,
        *,
        trusted_transfer_target: TrustedLessonBlueprint | None = None,
    ) -> CandidateValidationResult:
        # A. Fresh complete schema, actual digest, canonical snapshot, explicit identity.
        try:
            checked = _integrity(candidate)
        except _Rejected as exc:
            return _result(None, "integrity", "invalid", exc.code)
        except (ValueError, TypeError, AttributeError, RecursionError):
            return _result(None, "integrity", "invalid", Code.CANDIDATE_SCHEMA_INVALID)
        try:
            expected_identity = CompositionIdentity.model_validate(
                identity.model_dump(mode="json"), strict=True
            )
        except (ValueError, TypeError, AttributeError):
            return _result(checked, "integrity", "unavailable", Code.TRUSTED_CONTEXT_INVALID)
        if _identity(checked) != expected_identity:
            return _result(checked, "integrity", "invalid", Code.CANDIDATE_IDENTITY_MISMATCH)

        # B. Existing local-reference rules plus independently verified dependencies.
        try:
            _dependencies(checked, trusted_transfer_target)
        except _Rejected as exc:
            status: CandidateValidationStatus = (
                "unavailable" if exc.code == Code.TRANSFER_TARGET_UNAVAILABLE else "invalid"
            )
            return _result(checked, "structure", status, exc.code)
        except (ValueError, TypeError):
            return _result(checked, "structure", "invalid", Code.STRUCTURE_INVALID)

        # C. Independent preservation check before reusing composition for provenance.
        try:
            blueprint = TrustedLessonBlueprint(
                template_family=trusted_blueprint.template_family,
                definition=trusted_blueprint.definition,
            )
        except (ValueError, TypeError, AttributeError):
            return _result(checked, "configuration", "unavailable", Code.TRUSTED_CONTEXT_INVALID)
        metadata = checked.metadata
        if (
            metadata.blueprint != blueprint.reference()
            or metadata.template_family != blueprint.template_family
            or metadata.blueprint_runtime_revision
            != blueprint.definition.private.runtime_binding.revision
        ):
            return _result(checked, "configuration", "invalid", Code.CANDIDATE_METADATA_MISMATCH)
        if _protected_view(checked.definition) != _protected_view(blueprint.definition):
            return _result(checked, "configuration", "invalid", Code.TRUSTED_CONFIGURATION_CHANGED)
        fact = next(
            item
            for item in blueprint.definition.explanations
            if item.release_event == "core_verification_passed"
        )
        composed_fact = next(item for item in checked.definition.explanations if item.id == fact.id)
        if not composed_fact.text.startswith(fact.text + "\n\nConcept framing:\n"):
            return _result(checked, "configuration", "invalid", Code.TRUSTED_CONFIGURATION_CHANGED)
        try:
            expected = compose_lesson_spec(
                request,
                accepted_content,
                blueprint,
                expected_identity,
                trusted_transfer_target=trusted_transfer_target,
            )
        except (ValueError, TypeError, AttributeError):
            return _result(checked, "configuration", "unavailable", Code.TRUSTED_CONTEXT_INVALID)
        if (
            checked.canonical_definition_bytes != expected.canonical_definition_bytes
            or metadata.context_variant != expected.metadata.context_variant
            or metadata.contract_version != expected.metadata.contract_version
            or metadata.admission_policy_version != expected.metadata.admission_policy_version
        ):
            return _result(checked, "configuration", "invalid", Code.COMPOSITION_MISMATCH)

        # D. Never synthesize runtime success when an adapter/report is unavailable.
        if self.runtime is None:
            return _result(checked, "runtime", "unavailable", Code.RUNTIME_UNAVAILABLE)
        try:
            observed = self.runtime.validate(checked.definition)
            if not isinstance(observed, RuntimeValidationReport):
                return _result(checked, "runtime", "unavailable", Code.RUNTIME_REPORT_INVALID)
            report = RuntimeValidationReport.model_validate(observed.model_dump(), strict=True)
            if report.code is not None and report.code not in _RUNTIME_CODES:
                return _result(checked, "runtime", "unavailable", Code.RUNTIME_REPORT_INVALID)
        except TimeoutError:
            return _result(checked, "runtime", "unavailable", Code.RUNTIME_TIMEOUT)
        except (ValueError, TypeError):
            return _result(checked, "runtime", "unavailable", Code.RUNTIME_REPORT_INVALID)
        except Exception:
            return _result(checked, "runtime", "runtime_failed", Code.RUNTIME_EXCEPTION)
        if report.status == "passed":
            return _result(checked, None, "validated", None, report)
        return _result(
            checked,
            "runtime",
            "unavailable" if report.status == "unavailable" else "runtime_failed",
            report.code,
            report,
        )
