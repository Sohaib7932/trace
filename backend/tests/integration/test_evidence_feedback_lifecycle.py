"""Internal feedback shares application resources without changing learner APIs."""

import json
from pathlib import Path
from unittest.mock import patch

from fastapi import Request
from fastapi.testclient import TestClient

from app.ai.providers.fake import FakeTutorProvider
from app.ai.providers.mock_transport import MockAITransport
from app.api.dependencies import (
    get_ai_resources,
    get_evidence_feedback_service,
    get_tutor_provider,
)
from app.core.ai_settings import AIClientSettings
from app.db.learning import SqlLearningRepository
from app.main import create_app
from app.schemas.ai_client import TransportCompletion
from tests.unit.test_evidence_feedback_providers import feedback_request


def app_request(app):
    return Request({"type": "http", "app": app, "headers": []})


def test_internal_feedback_dependency_reuses_app_provider_and_existing_repository(
    settings, database
):
    transport = MockAITransport([TransportCompletion(text="fixture", cost_microusd=0)])
    app = create_app(
        settings,
        database,
        ai_settings=AIClientSettings(_env_file=None, mode="mock"),
        ai_transport_factory=lambda: transport,
    )
    with TestClient(app):
        request = app_request(app)
        resources = get_ai_resources(request)
        repository = SqlLearningRepository(database)
        with patch("app.api.dependencies.EvidenceFeedbackService") as service:
            assert (
                get_evidence_feedback_service(request, repository, resources)
                is service.return_value
            )
            service.assert_called_once_with(
                repository, resources.evidence_feedback_provider, app.state.clock
            )
        assert resources.evidence_feedback_provider.client is resources.client
        assert isinstance(get_tutor_provider(settings), FakeTutorProvider)
        assert not transport.calls
        expected = json.loads((Path(__file__).resolve().parents[2] / "openapi.json").read_text())
        assert app.openapi() == expected
        assert len(expected["paths"]) == 31
        assert (
            sum(not path.startswith("/api/v1/admin/knowledge/") for path in expected["paths"]) == 24
        )
        assert "/api/v1/sessions/{session_id}/feedback" in expected["paths"]
    assert resources.client.closed


def test_disabled_lifespan_does_not_construct_transport_or_select_a_fake(settings, database):
    calls = []
    app = create_app(
        settings,
        database,
        ai_settings=AIClientSettings(_env_file=None),
        ai_transport_factory=lambda: calls.append(True),
    )
    with TestClient(app):
        resources = get_ai_resources(app_request(app))
        result = resources.evidence_feedback_provider.explain(feedback_request())
        assert result.status == "unavailable" and result.source == "none"
        assert result.error_code == "disabled" and not calls
        assert resources.client.transport is None and not resources.client.usage_snapshot()
    assert resources.client.closed


def test_repeated_lifespans_get_new_feedback_adapters_and_dispose_old_client(settings, database):
    app = create_app(
        settings,
        database,
        ai_settings=AIClientSettings(_env_file=None),
    )
    with TestClient(app):
        first = get_ai_resources(app_request(app))
        first_provider = first.evidence_feedback_provider
        assert get_ai_resources(app_request(app)).evidence_feedback_provider is first_provider
    assert first.client.closed
    with TestClient(app):
        second = get_ai_resources(app_request(app))
        assert second is not first
        assert second.evidence_feedback_provider is not first_provider
        assert second.evidence_feedback_provider.client is second.client
        assert second.client.usage_snapshot() == ()
        assert first_provider.explain(feedback_request()).error_code == "disabled"
    assert second.client.closed
