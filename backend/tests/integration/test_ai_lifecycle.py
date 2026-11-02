"""Internal AI dependencies share lifespan ownership without adding public routes."""

import json
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.ai.providers.fake import FakeTutorProvider
from app.ai.resources import AIResourceError
from app.api.dependencies import (
    get_ai_client,
    get_ai_resources,
    get_candidate_lifecycle_service,
    get_internal_tutor_provider,
    get_lesson_assistant_service,
    get_question_generator,
    get_support_service,
    get_tutor_provider,
)
from app.core.ai_settings import AIClientSettings
from app.core.errors import ApplicationError
from app.db import models as m
from app.db.session import Database
from app.main import create_app
from app.schemas.support import SupportQuestion
from tests.integration.test_learning import post, predict, start
from tests.unit.test_ai_resources import ClosingTransport


def ai_settings(mode="mock"):
    return AIClientSettings(_env_file=None, mode=mode)


def app_request(app):
    return Request({"type": "http", "app": app, "headers": []})


def test_dependencies_reuse_one_client_and_existing_learner_tutor_stays_fake(settings, database):
    transport = ClosingTransport()
    app = create_app(
        settings, database, ai_settings=ai_settings(), ai_transport_factory=lambda: transport
    )
    with TestClient(app) as client:
        resources = get_ai_resources(app_request(app))
        assert get_ai_resources(app_request(app)) is resources
        assert get_ai_client(resources) is resources.client
        assert get_question_generator(resources) is resources.question_generator
        assert get_internal_tutor_provider(resources) is resources.tutor_provider
        assert get_lesson_assistant_service(resources) is resources.lesson_assistant
        assert get_support_service(resources) is resources.support
        assert isinstance(get_tutor_provider(settings), FakeTutorProvider)
        for _ in range(2):
            result = get_ai_client(resources).complete(
                capability="generation", instructions="Fixture", data={}
            )
            assert result.status == "success"
        assert resources.client.usage_snapshot()[0].attempts == 2
        support = get_support_service(resources).answer(
            SupportQuestion(question="How do I sign in?")
        )
        assert support.status == "unavailable" and len(transport.calls) == 2
        lifecycle = get_candidate_lifecycle_service(app_request(app), database)
        assert lifecycle.repository.database is database
        assert client.get("/api/v1/health/live").status_code == 200
        with database.session() as session:
            assert session.scalars(select(m.Learner)).all() == []
            assert session.scalars(select(m.GeneratedCandidate)).all() == []
    assert transport.closed_count == 1 and resources.client.closed
    with pytest.raises(ApplicationError) as exc:
        get_ai_resources(app_request(app))
    assert exc.value.status_code == 503


def test_default_disabled_app_constructs_no_transport_or_fake_fallback(settings, database):
    calls = []
    app = create_app(
        settings,
        database,
        ai_settings=ai_settings("disabled"),
        ai_transport_factory=lambda: calls.append(True),
    )
    with TestClient(app):
        resource = get_ai_resources(app_request(app))
        result = resource.client.complete(capability="support", instructions="Fixture", data={})
        assert (
            result.status == "unavailable"
            and result.error_code == "disabled"
            and result.text is None
        )
        assert resource.client.transport is None and not calls
    assert resource.client.closed


def test_repeated_lifespans_build_fresh_resources_and_close_each_once(settings, database):
    transports = []

    def factory():
        transport = ClosingTransport()
        transports.append(transport)
        return transport

    app = create_app(settings, database, ai_settings=ai_settings(), ai_transport_factory=factory)
    with TestClient(app):
        first = get_ai_resources(app_request(app))
        first.client.complete(capability="generation", instructions="Fixture", data={})
    with TestClient(app):
        second = get_ai_resources(app_request(app))
        assert second is not first and second.client is not first.client
        assert second.client.usage_snapshot() == () and not second.client.closed
    assert first.client.closed and second.client.closed
    assert [transport.closed_count for transport in transports] == [1, 1]


def test_distinct_applications_do_not_share_ai_clients_or_counters(settings, database):
    first = create_app(
        settings, database, ai_settings=ai_settings(), ai_transport_factory=ClosingTransport
    )
    second = create_app(
        settings, database, ai_settings=ai_settings(), ai_transport_factory=ClosingTransport
    )
    with TestClient(first), TestClient(second):
        one, two = get_ai_resources(app_request(first)), get_ai_resources(app_request(second))
        one.client.complete(capability="tutor", instructions="Fixture", data={})
        assert one.client is not two.client and two.client.usage_snapshot() == ()


@pytest.mark.parametrize("failure", ["factory", "binding", "missing_factory"])
def test_startup_failure_disposes_owned_database_and_closes_allocated_transport(settings, failure):
    database = Database(settings)
    transport = ClosingTransport()

    def factory():
        if failure == "factory":
            raise RuntimeError("private-startup-key-sentinel")
        return transport

    app = create_app(
        settings,
        ai_settings=ai_settings(),
        ai_transport_factory=None if failure == "missing_factory" else factory,
    )
    with (
        patch("app.main.Database", return_value=database),
        patch.object(database, "dispose", wraps=database.dispose) as dispose,
        patch(
            "app.ai.resources.BoundedTutorProvider", side_effect=RuntimeError("private-binding-key")
        )
        if failure == "binding"
        else nullcontext(),
    ):
        with pytest.raises(AIResourceError) as exc, TestClient(app):
            pass
        assert str(exc.value) == "AI resources are unavailable."
        dispose.assert_called_once()
    assert transport.closed_count == (1 if failure == "binding" else 0)


def test_transport_cleanup_failure_still_disposes_owned_database(settings, capsys, caplog):
    database = Database(settings)
    transport = ClosingTransport(fail_close=True)
    app = create_app(settings, ai_settings=ai_settings(), ai_transport_factory=lambda: transport)
    with (
        patch("app.main.Database", return_value=database),
        patch.object(database, "dispose", wraps=database.dispose) as dispose,
    ):
        with pytest.raises(AIResourceError) as exc, TestClient(app) as client:
            assert client.get("/api/v1/health/live").status_code == 200
        dispose.assert_called_once()
    assert str(exc.value) == "AI resources are unavailable." and transport.closed_count == 1
    assert "private-credential" not in caplog.text + capsys.readouterr().err


def test_application_does_not_dispose_a_caller_owned_database(settings, database):
    app = create_app(settings, database)
    with patch.object(database, "dispose", wraps=database.dispose) as dispose:
        with TestClient(app):
            pass
        dispose.assert_not_called()


def test_process_ai_configuration_is_separate_and_no_credentials_are_loaded(
    settings, database, monkeypatch
):
    monkeypatch.setenv("TRACE_LLM_MODE", "disabled")
    monkeypatch.setenv("TRACE_LLM_CREDENTIAL_ENV_VAR", "TEAM_AI_KEY")
    monkeypatch.setenv("TEAM_AI_KEY", "private-credential-unused-sentinel")
    app = create_app(settings, database)
    with TestClient(app):
        resources = get_ai_resources(app_request(app))
        assert resources.settings.credential_env_var == "TEAM_AI_KEY"
        assert resources.client.transport is None
        assert "private-credential" not in repr(resources.settings)


def test_mock_mode_from_environment_still_requires_explicit_factory(
    settings, database, monkeypatch
):
    monkeypatch.setenv("TRACE_LLM_MODE", "mock")
    app = create_app(settings, database)
    with pytest.raises(AIResourceError), TestClient(app):
        pass


def test_public_api_schema_and_existing_fixture_hint_behavior_are_unchanged(learner):
    baseline = json.loads((Path(__file__).resolve().parents[2] / "openapi.json").read_text())
    assert learner.app.openapi() == baseline
    assert len(baseline["paths"]) == 21
    session = start(learner)
    assert predict(learner, session).status_code == 201
    response = post(learner, f"/sessions/{session}/hints", {})
    assert response.status_code == 201 and response.json()["provider"] == "fake"
    assert learner.app.state.ai_resources.settings.mode == "disabled"
