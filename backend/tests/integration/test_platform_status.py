"""Operator status is read-only, categorical/aggregate and never a live provider probe."""

import json
from unittest.mock import patch

from app.core.accounting_settings import AccountingSettings
from scripts import platform_status
from tests.integration.test_knowledge_archive import archive as archive  # noqa: F401
from tests.integration.test_knowledge_archive import publish_corpus


def test_status_reports_missing_publication_without_identity_or_provider_claims(archive):
    report = platform_status.collect_status(archive.database, AccountingSettings(_env_file=None))
    assert report["schema_current"] is True and report["database"] == "reachable"
    assert report["provider_availability"] == "not_probed" and report["usage"] is None
    assert report["knowledge"]["available"] is False
    assert report["knowledge"]["issues"] == ["missing_review"]
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
    assert report["knowledge"]["revocation_events"] == 0
    assert report["knowledge"]["archived_embedding_indexes"] == 0
    assert report["usage"]["provider_attempts"] == 0
    raw = json.dumps(report)
    assert "original_json" not in raw and "quote" not in raw and "subject_hash" not in raw


def test_status_configuration_errors_are_sanitized_and_never_echo_credentials(capsys):
    with patch.object(
        platform_status, "Settings", side_effect=ValueError("private-monitor-canary")
    ):
        assert platform_status.main() == 1
    captured = capsys.readouterr()
    assert "private-monitor-canary" not in captured.out + captured.err
    assert json.loads(captured.out)["error_code"] == "operator_status_unavailable"
