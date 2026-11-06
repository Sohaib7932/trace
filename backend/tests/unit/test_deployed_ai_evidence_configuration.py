"""Default production evidence cannot initialize an original SQLite database."""

from unittest.mock import patch

import pytest

from scripts import ai_acceptance_evidence as evidence


@pytest.mark.parametrize(
    "environment,url",
    [
        (None, None),
        ("development", "sqlite+pysqlite:///private-original.db"),
        ("production", "sqlite+pysqlite:///private-original.db"),
    ],
)
def test_missing_or_sqlite_configuration_is_rejected_before_database_initialization(
    monkeypatch, environment, url
):
    if environment is not None:
        monkeypatch.setenv("TRACE_ENVIRONMENT", environment)
    if url is not None:
        monkeypatch.setenv("TRACE_DATABASE_URL", url)
    with (
        patch.object(
            evidence, "Database", side_effect=AssertionError("Do not open any database")
        ) as database,
        pytest.raises(evidence.EvidenceError) as error,
    ):
        evidence.from_environment()
    database.assert_not_called()
    assert error.value.code == "evidence_configuration_required"
    assert "private-original" not in str(error.value)


def test_proof_output_rejects_unapproved_models_private_fields_and_noninteger_usage():
    from pydantic import ValidationError

    for values in (
        {"requested_model_id": "private-model-canary"},
        {"owner": "private-account-canary"},
        {"input_tokens": True},
        {"recorded_cost_microusd": 1},
    ):
        with pytest.raises(ValidationError) as error:
            evidence.VerifiedEvidence.model_validate(
                {"input_tokens": 1, "output_tokens": 2, **values}
            )
        assert "private-model-canary" not in str(error.value)
        assert "private-account-canary" not in str(error.value)


def test_unexpected_internal_error_category_cannot_escape_as_private_report_text():
    error = evidence.EvidenceError("private-provider-error-canary")
    assert error.code == "evidence_unavailable"
    assert "private-provider-error-canary" not in str(error)
