import asyncio
import io
import json
from typing import Annotated
from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from app.ai.interface import TutorProvider
from app.ai.providers.fake import FakeTutorProvider
from app.api.dependencies import get_database, get_settings, get_tutor_provider
from app.core.settings import Settings
from app.db.session import Database
from app.main import create_app
from app.schemas.tutoring import HintRequest, TutorMessage


def test_application_starts_router_and_openapi_are_mounted(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200 and response.json() == {"status": "alive"}
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]) == {
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/api/v1/learners/anonymous",
        "/api/v1/learners/me",
        "/api/v1/learners/me/revoke",
        "/api/v1/lessons/{lesson_id}",
        "/api/v1/sessions",
        "/api/v1/sessions/{session_id}",
        "/api/v1/sessions/{session_id}/abandon",
        "/api/v1/sessions/{session_id}/prediction",
        "/api/v1/sessions/{session_id}/attempts",
        "/api/v1/sessions/{session_id}/hints",
        "/api/v1/sessions/{session_id}/attempts/{attempt_id}/verify",
        "/api/v1/sessions/{session_id}/verifications",
        "/api/v1/sessions/{session_id}/progress",
        "/api/v1/learners/me/journey",
        "/api/v1/retrievals/{checkpoint_id}",
        "/api/v1/retrievals/{checkpoint_id}/attempts",
        "/api/v1/account/me",
        "/api/v1/account/me/learner",
        "/api/v1/account/claim-anonymous",
    }
    assert schema["paths"]["/api/v1/health/ready"]["get"]["responses"]["503"]


def test_readiness_responds_to_actual_database_failure(
    client: TestClient, database: Database
) -> None:
    assert client.get("/api/v1/health/ready").status_code == 200

    def unavailable(*args: object) -> None:
        raise OperationalError("private/database/path", {}, RuntimeError("private-password"))

    event.listen(database.engine, "before_cursor_execute", unavailable)
    try:
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "dependency_unavailable"
        assert "private" not in response.text
        assert client.get("/api/v1/health/live").status_code == 200
    finally:
        event.remove(database.engine, "before_cursor_execute", unavailable)
    assert client.get("/api/v1/health/ready").status_code == 200


def test_database_dependency_override_is_used(app: FastAPI) -> None:
    other = Database(
        Settings(_env_file=None, database_url=SecretStr("sqlite+pysqlite:///:memory:"))
    )
    app.dependency_overrides[get_database] = lambda: other
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/health/ready").status_code == 503  # No migration.
    finally:
        app.dependency_overrides.clear()
        other.dispose()


def test_factory_disposes_its_own_database(settings: Settings) -> None:
    app = create_app(settings)
    database = Database(settings)
    with (
        patch("app.main.Database", return_value=database),
        patch.object(database, "dispose", wraps=database.dispose) as dispose,
    ):
        with TestClient(app):
            assert app.state.database is database
        dispose.assert_called_once()
    assert app.state.settings is settings


@pytest.mark.parametrize(
    "method,path,status,code",
    [
        ("GET", "/missing/private-token", 404, "not_found"),
        ("POST", "/api/v1/health/live", 405, "method_not_allowed"),
    ],
)
def test_http_errors_use_envelope_and_request_id(
    client: TestClient, method: str, path: str, status: int, code: str
) -> None:
    response = client.request(method, path, headers={"X-Request-ID": "test-correlation"})
    assert response.status_code == status
    assert response.headers["X-Request-ID"] == "test-correlation"
    assert response.json()["error"]["request_id"] == "test-correlation"
    assert response.json()["error"]["code"] == code
    assert "private-token" not in response.text


def test_untrusted_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/api/v1/health/live", headers={"X-Request-ID": "secret " * 20})
    assert len(response.headers["X-Request-ID"]) == 36


def mount_test_hint(app: FastAPI) -> None:
    @app.post("/_test/hint", response_model=TutorMessage)
    def hint(
        request: HintRequest, provider: Annotated[TutorProvider, Depends(get_tutor_provider)]
    ) -> TutorMessage:
        return provider.generate_hint(request)


def test_validated_payload_fake_provider_and_settings_override(app: FastAPI) -> None:
    mount_test_hint(app)
    settings_used: list[str] = []
    fake = FakeTutorProvider()

    def settings_override() -> Settings:
        settings_used.append("test")
        return Settings(_env_file=None, environment="test")

    app.dependency_overrides[get_settings] = settings_override
    with TestClient(app) as client:
        body = {"context": {"scenario": "Field mismatch", "learner_attempt": "body"}, "level": 1}
        response = client.post("/_test/hint", json=body)
        assert response.status_code == 200 and response.json()["source"] == "test_fixture"
        assert settings_used == ["test"]
        app.dependency_overrides[get_tutor_provider] = lambda: fake
        body["level"] = 2
        assert client.post("/_test/hint", json=body).json()["text"] != response.json()["text"]
        body["level"] = "private-password"
        invalid = client.post("/_test/hint", json=body)
        assert invalid.status_code == 422
        assert invalid.json()["error"]["details"][0]["location"] == ["body", "level"]
        assert "private-password" not in invalid.text
    app.dependency_overrides.clear()


def test_cors_is_explicit_and_preflight_has_request_id(client: TestClient) -> None:
    allowed = client.options(
        "/api/v1/health/live",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert allowed.headers["x-request-id"]
    rejected = client.get("/api/v1/health/live", headers={"Origin": "https://foreign.example"})
    assert "access-control-allow-origin" not in rejected.headers


def test_unexpected_error_is_generic_and_cors_is_preserved(app: FastAPI) -> None:
    @app.get("/_test/fail")
    def fail() -> None:
        raise RuntimeError("private-file-path-and-token")

    with TestClient(app) as client:
        response = client.get("/_test/fail", headers={"Origin": "http://localhost:3000"})
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "internal_error"
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
        assert "private" not in response.text


def test_request_body_limit_is_enforced(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.post("/missing", content=b"x" * 65537)
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "request_too_large"


def test_request_deadline(settings: Settings, database: Database) -> None:
    app = create_app(settings.model_copy(update={"request_timeout_seconds": 0.01}), database)

    @app.get("/_test/slow")
    async def slow() -> None:
        await asyncio.sleep(1)

    with TestClient(app) as client:
        response = client.get("/_test/slow")
        assert response.status_code == 504
        assert response.json()["error"]["code"] == "request_timeout"


def test_request_logs_do_not_leak_unknown_paths_queries_or_bodies(app: FastAPI) -> None:
    output = io.StringIO()
    app.state.logger.handlers[0].setStream(output)
    with TestClient(app) as client:
        client.post(
            "/private-path?token=private-query",
            content="private-body",
            headers={"Authorization": "Bearer private-credential"},
        )
    rows = [json.loads(line) for line in output.getvalue().splitlines()]
    assert rows[-1]["route"] is None and rows[-1]["status_code"] == 404
    assert "private" not in output.getvalue()
