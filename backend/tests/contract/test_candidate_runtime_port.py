"""Runtime port and fail-closed evidence contract, without learner workflows."""

from typing import get_type_hints

import pytest
from pydantic import ValidationError

from app.repositories.candidate_validation import CandidateRuntime
from app.schemas.candidate_validation import (
    CHECK_CODES,
    RuntimeEvidenceCheck,
    RuntimeProfileEvidence,
    RuntimeValidationReport,
)
from app.verification.candidate_runtime import IsolatedCandidateRuntime


def complete_profile(name):
    return RuntimeProfileEvidence(
        profile=name,
        evaluation_matched=True,
        checks=tuple(RuntimeEvidenceCheck(code=code, passed=True) for code in sorted(CHECK_CODES)),
    )


def test_isolated_runtime_satisfies_the_existing_candidate_execution_port():
    runtime: CandidateRuntime = IsolatedCandidateRuntime()
    assert get_type_hints(runtime.validate) == get_type_hints(CandidateRuntime.validate)
    assert not hasattr(runtime, "verify")
    assert not hasattr(runtime, "repository")


@pytest.mark.parametrize("missing", sorted(CHECK_CODES))
def test_a_required_evidence_category_cannot_be_skipped(missing):
    with pytest.raises(ValidationError):
        RuntimeProfileEvidence(
            profile="repair",
            evaluation_matched=True,
            checks=tuple(
                RuntimeEvidenceCheck(code=code, passed=True)
                for code in CHECK_CODES
                if code != missing
            ),
        )


def test_a_successful_runtime_report_requires_both_profiles_and_real_execution():
    data = {
        "status": "passed",
        "code": None,
        "performed": True,
        "completed": True,
        "profiles": (complete_profile("baseline"), complete_profile("repair")),
    }
    assert RuntimeValidationReport.model_validate(data).status == "passed"
    for changes in [
        {"performed": False},
        {"completed": False},
        {"profiles": (complete_profile("baseline"),)},
        {"profiles": (complete_profile("repair"), complete_profile("repair"))},
    ]:
        with pytest.raises(ValidationError):
            RuntimeValidationReport.model_validate({**data, **changes})


def test_a_successful_profile_cannot_mask_an_unmatched_evaluation_or_check():
    baseline = complete_profile("baseline")
    for profile in [
        RuntimeProfileEvidence(
            profile="repair", checks=complete_profile("repair").checks, evaluation_matched=False
        ),
        RuntimeProfileEvidence(
            profile="repair",
            evaluation_matched=True,
            checks=tuple(
                RuntimeEvidenceCheck(code=code, passed=code != "stored_values")
                for code in sorted(CHECK_CODES)
            ),
        ),
    ]:
        with pytest.raises(ValidationError):
            RuntimeValidationReport(
                status="passed",
                code=None,
                performed=True,
                completed=True,
                profiles=(baseline, profile),
            )
