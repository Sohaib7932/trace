"""Test-only candidate contexts and runtime-port data; no production registration."""

from app.schemas.candidate_validation import (
    CHECK_CODES,
    RuntimeEvidenceCheck,
    RuntimeProfileEvidence,
    RuntimeValidationReport,
)
from app.services.lesson_composition import compose_lesson_spec
from tests.composition_fixtures import admitted_case, blueprint, composition_identity


def validation_case(family="notes-v1", *, with_target=True):
    request, accepted = admitted_case(family)
    source = blueprint(family)
    identity = composition_identity(family)
    target = blueprint("tasks-nested-v1") if family == "notes-v1" and with_target else None
    candidate = compose_lesson_spec(
        request,
        accepted,
        source,
        identity,
        trusted_transfer_target=target,
    )
    return {
        "candidate": candidate,
        "request": request,
        "accepted_content": accepted,
        "trusted_blueprint": source,
        "identity": identity,
        "trusted_transfer_target": target,
    }


def candidate_payload(candidate):
    """Preserve the strict internal bytes/model types while varying hostile input."""
    return {
        "state": candidate.state,
        "release_eligible": candidate.release_eligible,
        "definition": candidate.definition,
        "canonical_digest": candidate.canonical_digest,
        "canonical_definition_bytes": candidate.canonical_definition_bytes,
        "metadata": candidate.metadata.model_dump(mode="json"),
    }


def passing_runtime_report():
    return RuntimeValidationReport(
        status="passed",
        code=None,
        performed=True,
        completed=True,
        profiles=tuple(
            RuntimeProfileEvidence(
                profile=profile,
                evaluation_matched=True,
                checks=tuple(
                    RuntimeEvidenceCheck(code=code, passed=True) for code in sorted(CHECK_CODES)
                ),
            )
            for profile in ("baseline", "repair")
        ),
    )
