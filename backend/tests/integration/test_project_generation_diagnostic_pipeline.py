"""Categorical pipeline receipts with deterministic fakes and disposable databases."""

import json
import logging
from uuid import UUID, uuid4

import pytest

from app.ai.project_generation_diagnostics import (
    notify_project_provider_request,
    notify_project_provider_response,
)
from app.core.errors import ApplicationError
from tests.integration.test_github_projects import SHA
from tests.integration.test_github_projects import project as project  # noqa: F401
from tests.integration.test_live_ai_http import api as api  # noqa: F401
from tests.integration.test_project_learning_persistence import count, prepare, setup_http

CANARY = "private-generation-canary-never-log"


def collect():
    events = []

    def observer(*args):
        events.append(args)

    return events, observer


def stages(events):
    return [(event[1], event[2]) for event in events]


def assert_private_receipts(events):
    assert events
    attempt_ids = set()
    for identifier, stage, reason, initiated, response_received in events:
        identifier = UUID(identifier)
        assert identifier.version == 4
        attempt_ids.add(identifier)
        assert isinstance(stage, str) and isinstance(reason, str)
        assert type(initiated) is bool and type(response_received) is bool
    assert len(attempt_ids) == 1
    assert CANARY not in repr(events)


def provider_wrapper(project, monkeypatch, transform):
    original = project.ai.complete

    def complete(**kwargs):
        callback = kwargs.get("on_transport_attempt")
        if callback is not None:
            callback()
        # Synthetic wire notifications only: no HTTP request is made.
        notify_project_provider_request()
        notify_project_provider_response(200)
        value = original(**kwargs)
        value.request_id = CANARY
        value.error_code = None
        return transform(value)

    monkeypatch.setattr(project.ai, "complete", complete)


def test_success_receipts_cover_validation_committed_persistence_and_release(project, monkeypatch):
    project.client.file_body = f"# {CANARY}\ndef greeting():\n    return 'hello'"
    project.ai.claim = f"Inspect this function. {CANARY}"
    identity, _ = prepare(project)
    provider_wrapper(project, monkeypatch, lambda value: value)
    events, observer = collect()

    result = project.service.learning_path(
        project.owner, identity, SHA, diagnostic_observer=observer
    )

    assert result.status == "ready" and count(project) == 1
    assert stages(events) == [
        ("generation", "started"),
        ("provider", "transport_entered"),
        ("provider_request", "initiated"),
        ("provider_request", "response_received"),
        ("provider_http", "success"),
        ("provider", "success"),
        ("response_parsing", "passed"),
        ("schema_validation", "passed"),
        ("citation_validation", "passed"),
        ("provenance_validation", "passed"),
        ("snapshot_validation", "passed"),
        ("persistence", "started"),
        ("persistence", "committed"),
        ("release", "passed"),
    ]
    assert_private_receipts(events)
    assert events[0][3:] == (False, False)
    assert events[1][3:] == (False, False)
    assert all(event[3] for event in events[2:])
    assert all(event[4] for event in events[3:])


@pytest.mark.parametrize(
    "stage",
    [
        "response_parsing",
        "schema_validation",
        "citation_validation",
        "provenance_validation",
        "snapshot_validation",
    ],
)
def test_rejected_validation_stage_is_precise_and_never_saves(project, monkeypatch, stage):
    identity, _ = prepare(project)

    def change(value):
        if stage == "response_parsing":
            value.text = "{" + CANARY
        elif stage == "schema_validation":
            payload = json.loads(value.text)
            payload["unexpected"] = CANARY
            value.text = json.dumps(payload)
        elif stage == "citation_validation":
            payload = json.loads(value.text)
            payload["steps"][0]["reference_ids"] = ["f" * 64]
            value.text = json.dumps(payload)
        elif stage == "provenance_validation":
            value.provider_id = CANARY
        return value

    provider_wrapper(project, monkeypatch, change)
    if stage == "snapshot_validation":

        def reject(*args):
            raise ValueError(CANARY)

        monkeypatch.setattr("app.services.github_projects.validate_learning_path", reject)
    events, observer = collect()

    result = project.service.learning_path(
        project.owner, identity, SHA, diagnostic_observer=observer
    )

    assert result.status == "unavailable" and count(project) == 0
    assert stages(events)[-1] == (stage, "rejected")
    assert not any(event[1] == "persistence" for event in events)
    assert_private_receipts(events)


def test_duplicate_citations_are_rejected_at_citation_validation(project, monkeypatch):
    identity, _ = prepare(project)

    def duplicate(value):
        payload = json.loads(value.text)
        reference = payload["steps"][0]["reference_ids"][0]
        payload["steps"][0]["reference_ids"] = [reference, reference]
        value.text = json.dumps(payload)
        return value

    provider_wrapper(project, monkeypatch, duplicate)
    events, observer = collect()
    result = project.service.learning_path(
        project.owner, identity, SHA, diagnostic_observer=observer
    )
    assert result.status == "unavailable" and count(project) == 0
    assert stages(events)[-1] == ("citation_validation", "rejected")
    assert not any(event[1] == "persistence" for event in events)
    assert_private_receipts(events)


def test_unexpected_provider_exception_reports_only_internal_error(project, monkeypatch):
    identity, _ = prepare(project)

    def fail(**kwargs):
        raise RuntimeError(CANARY)

    monkeypatch.setattr(project.ai, "complete", fail)
    events, observer = collect()
    with pytest.raises(RuntimeError):
        project.service.learning_path(project.owner, identity, SHA, diagnostic_observer=observer)
    assert count(project) == 0
    assert stages(events) == [("generation", "started"), ("provider", "internal_error")]
    assert_private_receipts(events)


@pytest.mark.parametrize(
    ("status", "error_code", "reason"),
    [
        ("transport_error", "authentication_error", "authentication"),
        ("rate_limited", "rate_limited", "quota"),
        ("timeout", "timeout", "timeout"),
        ("transport_error", "transient_error", "transport"),
        ("refusal", None, "provider_rejection"),
        ("unavailable", "configuration_missing", "availability"),
        ("transport_error", "invalid_request", "request_rejected"),
        ("transport_error", "request_too_large", "bounds_rejected"),
        ("transport_error", "token_limit", "bounds_rejected"),
        ("transport_error", "response_too_large", "bounds_rejected"),
        ("transport_error", "invalid_response", "invalid_response"),
        ("unavailable", "accounting_unavailable", "accounting"),
    ],
)
def test_provider_failure_categories_preserve_unavailable_contract(
    project, monkeypatch, status, error_code, reason
):
    identity, _ = prepare(project)

    def fail(value):
        value.status = status
        value.error_code = error_code
        value.text = None
        return value

    provider_wrapper(project, monkeypatch, fail)
    events, observer = collect()

    result = project.service.learning_path(
        project.owner, identity, SHA, diagnostic_observer=observer
    )

    assert result.status == "unavailable" and result.content is None and count(project) == 0
    assert stages(events)[-1] == ("provider", reason)
    assert not any(event[1] == "response_parsing" for event in events)
    assert_private_receipts(events)


def test_persistence_failure_keeps_original_503_and_never_reports_committed(project, monkeypatch):
    identity, _ = prepare(project)
    provider_wrapper(project, monkeypatch, lambda value: value)

    def fail(*args, **kwargs):
        raise ApplicationError("dependency_unavailable", CANARY, 503)

    monkeypatch.setattr(project.service.repository, "save_learning_path", fail)
    events, observer = collect()
    with pytest.raises(ApplicationError) as error:
        project.service.learning_path(project.owner, identity, SHA, diagnostic_observer=observer)

    assert error.value.status_code == 503 and count(project) == 0
    assert stages(events)[-2:] == [("persistence", "started"), ("persistence", "failed")]
    assert ("persistence", "committed") not in stages(events)
    assert_private_receipts(events)


def test_postcommit_authorization_failure_preserves_error_and_saved_history(project, monkeypatch):
    identity, _ = prepare(project)
    provider_wrapper(project, monkeypatch, lambda value: value)
    save = project.service.repository.save_learning_path

    def save_then_revoke(*args, **kwargs):
        save(*args, **kwargs)
        project.client.revoked = True

    monkeypatch.setattr(project.service.repository, "save_learning_path", save_then_revoke)
    events, observer = collect()
    with pytest.raises(ApplicationError):
        project.service.learning_path(project.owner, identity, SHA, diagnostic_observer=observer)

    assert count(project) == 1
    assert stages(events)[-2:] == [("persistence", "committed"), ("release", "failed")]
    assert_private_receipts(events)


def test_foreign_owner_cannot_start_generation_or_obtain_generation_receipts(project):
    identity, _ = prepare(project)
    events, observer = collect()
    with pytest.raises(ApplicationError) as error:
        project.service.learning_path(uuid4(), identity, SHA, diagnostic_observer=observer)

    assert error.value.status_code == 404
    assert not events and not project.ai.calls and count(project) == 0


def test_failing_observer_cannot_prevent_validation_or_persistence(project):
    identity, _ = prepare(project)

    def failing(*args):
        raise RuntimeError(CANARY)

    result = project.service.learning_path(
        project.owner, identity, SHA, diagnostic_observer=failing
    )
    assert result.status == "ready" and count(project) == 1
    project.ai.invalid = True
    rejected = project.service.learning_path(
        project.owner, identity, SHA, diagnostic_observer=failing
    )
    assert rejected.status == "unavailable" and count(project) == 1


class RecordingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def test_http_logs_categorical_receipts_without_adding_public_fields(api):
    github, ai, path = setup_http(api)
    ai.claim = f"Inspect this function. {CANARY}"
    handler = RecordingHandler()
    api.app.state.logger.addHandler(handler)
    try:
        generated = api.client.post(
            path, json={"commit_sha": SHA}, headers={"X-Request-ID": CANARY}
        )
        assert generated.status_code == 200 and generated.json()["status"] == "ready"
        assert set(generated.json()) == {
            "status",
            "content",
            "snapshot_digest",
            "commit_sha",
            "source",
            "grading",
            "execution_status",
            "can_complete_lesson",
            "id",
            "generation",
        }
        assert "diagnostic" not in json.dumps(api.app.openapi()).lower()
        records = [record for record in handler.records if hasattr(record, "generation_stage")]
        assert records
        assert {record.generation_stage for record in records} >= {
            "generation",
            "provider",
            "response_parsing",
            "schema_validation",
            "citation_validation",
            "provenance_validation",
            "snapshot_validation",
            "persistence",
            "release",
        }
        assert all(CANARY not in repr(vars(record)) for record in records)
    finally:
        api.app.state.logger.removeHandler(handler)
        github.close()


def test_http_unauthorized_and_foreign_sessions_never_emit_generation_receipts(api, project):
    identity, _ = prepare(project)
    api.app.state.github_projects = project.service
    path = f"/api/v1/projects/github/repositories/{identity}/learning-path"
    handler = RecordingHandler()
    api.app.state.logger.addHandler(handler)
    try:
        response = api.client.post(path, json={"commit_sha": SHA})
        assert response.status_code == 404
        api.client.headers.pop("Authorization")
        response = api.client.post(path, json={"commit_sha": SHA})
        assert response.status_code == 401
        assert not project.ai.calls
        assert not any(hasattr(record, "generation_stage") for record in handler.records)
    finally:
        api.app.state.logger.removeHandler(handler)
