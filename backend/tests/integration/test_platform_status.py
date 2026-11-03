"""Operator status is read-only, categorical/aggregate and never a live provider probe."""

import json
import os
from unittest.mock import patch
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import event

from app.core.accounting_settings import AccountingSettings
from app.core.ai_settings import GEMINI_MODEL, AIClientSettings
from app.core.settings import Settings
from app.support.knowledge import ReviewedSupportKnowledge
from scripts import platform_status
from tests.integration.test_knowledge_archive import archive as archive  # noqa: F401
from tests.integration.test_knowledge_archive import publish_corpus


def test_status_reports_missing_publication_without_identity_or_provider_claims(archive):
    report = platform_status.collect_status(archive.database, AccountingSettings(_env_file=None))
    assert report["schema_current"] is True and report["database"] == "reachable"
    assert report["provider_availability"] == "not_probed" and report["usage"] is None
    assert report["knowledge"]["available"] is False
    assert report["knowledge"]["issues"] == ["missing_review"]
    assert report["configuration_scope"] == "current_cli_process"
    assert report["running_application_configuration"] == "unknown"
    assert report["knowledge"]["backend"] == "database_archive"
    assert report["knowledge"]["revision_count"] == 0
    assert report["knowledge"]["publication_count"] == 0
    assert report["knowledge"]["current_revision_states"] == {}
    raw = json.dumps(report)
    assert str(archive.admin.account.id) not in raw and str(archive.learner.account.id) not in raw


def test_status_reports_published_knowledge_and_safe_cumulative_usage(archive):
    publish_corpus(archive)
    report = platform_status.collect_status(
        archive.database,
        AccountingSettings(_env_file=None, mode="durable", scope="synthetic-monitor"),
    )
    assert report["knowledge"]["available"] is True
    assert report["knowledge"]["source_count"] == 9
    assert report["knowledge"]["passage_count"] == 19
    assert report["knowledge"]["digests_valid"] is True
    assert report["knowledge"]["current_revision_states"] == {"published": 9}
    assert report["knowledge"]["revision_count"] == 9
    assert report["knowledge"]["publication_count"] == 1
    assert report["configured_knowledge_backend"] == "database_archive"
    assert report["configured_support"]["available"] is True
    assert report["knowledge"]["revocation_events"] == 0
    assert report["knowledge"]["archived_embedding_indexes"] == 0
    assert report["usage"]["provider_attempts"] == 0
    raw = json.dumps(report)
    assert "original_json" not in raw and "quote" not in raw and "subject_hash" not in raw


def test_status_configuration_errors_are_sanitized_and_never_echo_credentials(capsys):
    with patch.object(
        platform_status, "Settings", side_effect=ValueError("private-monitor-canary")
    ):
        assert platform_status.main([]) == 1
    captured = capsys.readouterr()
    assert "private-monitor-canary" not in captured.out + captured.err
    assert json.loads(captured.out)["error_code"] == "operator_status_unavailable"


def live_settings():
    return AIClientSettings(
        _env_file=None,
        mode="gemini_free",
        provider_id="gemini",
        generation_model_id=GEMINI_MODEL,
        conversational_model_id=GEMINI_MODEL,
        credential_env_var="GEMINI_API_KEY",
        free_tier_project_confirmed=True,
    )


def test_development_gemini_reports_eligible_package_independently_of_empty_archive(archive):
    report = platform_status.collect_status(
        archive.database,
        AccountingSettings(_env_file=None),
        ai=live_settings(),
        clock=lambda: archive.now[0],
    )
    assert report["configured_knowledge_backend"] == "reviewed_package"
    assert report["configured_support"] == {
        "available": True,
        "source_count": 9,
        "passage_count": 19,
        "issues": [],
        "digests_valid": True,
    }
    assert report["knowledge"]["available"] is False
    assert report["knowledge"]["revision_count"] == 0


@pytest.mark.parametrize("mode", ["disabled", "mock"])
def test_non_gemini_development_reports_empty_configured_knowledge(archive, mode):
    report = platform_status.collect_status(
        archive.database,
        AccountingSettings(_env_file=None),
        ai=AIClientSettings(_env_file=None, mode=mode),
    )
    assert report["configured_knowledge_backend"] == "empty"
    assert report["configured_support"]["available"] is False
    assert report["configured_support"]["digests_valid"] is None
    assert report["configured_support"]["issues"] == ["ai_mode_not_enabled"]


def test_durable_gemini_never_reports_package_fallback_for_empty_archive(archive):
    report = platform_status.collect_status(
        archive.database,
        AccountingSettings(_env_file=None, mode="durable", scope="synthetic-monitor"),
        ai=live_settings(),
        clock=lambda: archive.now[0],
    )
    assert report["configured_knowledge_backend"] == "database_archive"
    assert report["configured_support"]["available"] is False
    assert report["configured_support"]["issues"] == ["missing_review"]


def test_production_always_reports_database_knowledge(archive):
    settings = Settings(
        _env_file=None,
        environment="production",
        database_url="postgresql+psycopg://runtime@db.example.invalid/trace?sslmode=verify-full",
        database_schema="trace",
        cors_origins=("https://app.example.invalid",),
        supabase_url="https://auth.example.invalid",
        supabase_issuer="https://auth.example.invalid/auth/v1",
        supabase_jwks_url="https://auth.example.invalid/auth/v1/.well-known/jwks.json",
    )
    report = platform_status.collect_status(
        archive.database, AccountingSettings(_env_file=None), settings=settings, ai=live_settings()
    )
    assert report["configured_knowledge_backend"] == "database_archive"
    assert report["configured_support"]["available"] is False


@pytest.mark.parametrize("adopt,state", [(False, "validated"), (True, "approved")])
def test_status_distinguishes_unpublished_from_empty_archive(archive, adopt, state):
    archive.service.import_reviewed_corpus(
        key=str(uuid4()), actor=archive.admin, adopt_existing_review=adopt
    )
    report = platform_status.collect_status(
        archive.database, AccountingSettings(_env_file=None), clock=lambda: archive.now[0]
    )
    assert report["knowledge"]["archived_source_count"] == 9
    assert report["knowledge"]["revision_count"] == 9
    assert report["knowledge"]["current_revision_states"] == {state: 9}
    assert report["knowledge"]["publication_count"] == 0
    assert report["knowledge"]["available"] is False
    assert report["knowledge"]["digests_valid"] is None


def test_package_diagnostic_reuses_exact_eligibility_and_sanitizes_load_failure(archive):
    knowledge = ReviewedSupportKnowledge(
        clock=lambda: archive.now[0],
        loader=lambda: (_ for _ in ()).throw(ValueError("private-package-canary")),
    )
    with patch.object(platform_status, "ReviewedSupportKnowledge", return_value=knowledge):
        report = platform_status.collect_status(
            archive.database,
            AccountingSettings(_env_file=None),
            ai=live_settings(),
            clock=lambda: archive.now[0],
        )
    assert report["configured_support"]["available"] is False
    assert report["configured_support"]["digests_valid"] is None
    assert "private-package-canary" not in json.dumps(report)


def test_status_does_not_create_archive_rows_or_receipts(archive):
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(archive.database.engine, "before_cursor_execute", capture)
    try:
        for _ in range(2):
            report = platform_status.collect_status(
                archive.database,
                AccountingSettings(_env_file=None),
                ai=live_settings(),
                clock=lambda: archive.now[0],
            )
    finally:
        event.remove(archive.database.engine, "before_cursor_execute", capture)
    assert report["knowledge"]["revision_count"] == 0
    assert report["knowledge"]["release_receipts"] == 0
    assert statements and set(statements) == {"SELECT"}


@pytest.mark.parametrize("durable", [False, True])
def test_explicit_launcher_profile_reports_actual_config_and_restores_environment(
    archive, settings, monkeypatch, capsys, durable
):
    canary = "synthetic-private-profile-key"
    monkeypatch.setattr("app.core.ai_activation.private_gemini_key", lambda **_: SecretStr(canary))
    monkeypatch.setattr(platform_status, "Settings", lambda: settings)
    monkeypatch.setattr(platform_status, "Database", lambda _: archive.database)
    monkeypatch.setenv("TRACE_LLM_MODE", "mock")
    if durable:
        monkeypatch.setenv("TRACE_ACCOUNTING_MODE", "durable")
        monkeypatch.setenv("TRACE_ACCOUNTING_SCOPE", "synthetic-profile")
    before = dict(os.environ)
    assert platform_status.main(["--gemini-profile", "--confirm-free-tier-project"]) == 0
    captured = capsys.readouterr()
    assert canary not in captured.out + captured.err
    report = json.loads(captured.out)
    assert report["text_mode"] == "gemini_free"
    assert report["configuration_profile"] == "approved_gemini_launcher"
    assert report["configured_knowledge_backend"] == (
        "database_archive" if durable else "reviewed_package"
    )
    assert report["provider_availability"] == "not_probed"
    assert report["running_application_configuration"] == "unknown"
    assert dict(os.environ) == before


def test_default_cli_does_not_load_gemini_credentials(archive, settings, monkeypatch, capsys):
    monkeypatch.setattr(
        "app.core.ai_activation.private_gemini_key",
        lambda **_: pytest.fail("Default status must not read a provider credential"),
    )
    monkeypatch.setattr(platform_status, "Settings", lambda: settings)
    monkeypatch.setattr(platform_status, "Database", lambda _: archive.database)
    monkeypatch.setenv("TRACE_LLM_MODE", "disabled")
    assert platform_status.main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["configuration_profile"] == "ambient_cli"
    assert report["text_mode"] == "disabled"
    assert report["configured_knowledge_backend"] == "empty"


def test_profile_requires_confirmation_before_reading_credentials(monkeypatch, capsys):
    monkeypatch.setattr(
        "app.core.ai_activation.private_gemini_key",
        lambda **_: pytest.fail("Missing confirmation must not read a credential"),
    )
    before = dict(os.environ)
    assert platform_status.main(["--gemini-profile"]) == 1
    assert json.loads(capsys.readouterr().out)["error_code"] == "operator_status_unavailable"
    assert dict(os.environ) == before


@pytest.mark.parametrize("failure_stage", ["key", "database"])
def test_profile_failures_are_sanitized_and_restore_environment(
    settings, monkeypatch, capsys, failure_stage
):
    canary = "synthetic-private-profile-exception"

    def key(**_):
        if failure_stage == "key":
            raise ValueError(canary)
        return SecretStr(canary)

    monkeypatch.setattr("app.core.ai_activation.private_gemini_key", key)
    monkeypatch.setattr(platform_status, "Settings", lambda: settings)
    monkeypatch.setattr(
        platform_status, "Database", lambda _: (_ for _ in ()).throw(ValueError(canary))
    )
    before = dict(os.environ)
    assert platform_status.main(["--gemini-profile", "--confirm-free-tier-project"]) == 1
    captured = capsys.readouterr()
    assert canary not in captured.out + captured.err
    assert json.loads(captured.out)["error_code"] == "operator_status_unavailable"
    assert dict(os.environ) == before


@pytest.mark.parametrize(
    "arguments",
    [["--unknown", "private-cli-canary"], ["--confirm-free-tier-project"]],
)
def test_profile_cli_rejects_invalid_arguments_without_echoing_them(capsys, arguments):
    with pytest.raises(SystemExit) as error:
        platform_status.main(arguments)
    assert error.value.code == 2
    assert "private-cli-canary" not in str(capsys.readouterr())
