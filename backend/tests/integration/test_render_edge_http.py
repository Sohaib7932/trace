"""Actual Trace routes behind an explicitly simulated Render public edge.

The simulator models documented public-edge XFP normalization. It is not live
Render evidence and does not authenticate private peers. Production settings are
validated; databases and asymmetric signing keys are disposable fixtures only.
"""

from dataclasses import dataclass
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.auth.jwt import JwtVerifier
from app.core.accounting_settings import AccountingSettings
from app.core.ai_settings import AIClientSettings
from app.core.render_edge_middleware import RawSocketCaptureMiddleware
from app.core.render_edge_settings import RenderEdgeSettings
from app.core.settings import Settings
from app.db.learning import SqlLearningRepository
from app.main import create_app
from app.services.catalog import seed_first_lesson, seed_transfer_lesson
from app.services.identity import COOKIE_NAME
from tests.auth_fixtures import KeysFixture, SigningFixture, auth_settings

HOST = "trace-fixture.onrender.com"
SITE = "https://frontend.example.invalid"
PEERS = ("10.90.0.11", "10.91.0.12", "10.92.0.13")


class SimulatedRenderPublicEdge:
    """No real edge claim: vary untrusted peers and normalize public HTTPS XFP."""

    def __init__(self, app, *, normalize=True):
        # Keep the launcher's narrow fixture allowlist. Our changing peers do
        # not match it; Uvicorn must not promote either scheme or client IP.
        self.trace = app
        self.app = RawSocketCaptureMiddleware(
            ProxyHeadersMiddleware(self.observe_application_scope, trusted_hosts=["127.0.0.1/32"])
        )
        self.peer = PEERS[0]
        self.normalize = normalize
        self.last_scope = None

    async def observe_application_scope(self, scope, receive, send):
        # The real raw-socket wrapper deliberately clones the incoming scope.
        # Observe its actual downstream copy, never the pre-capture dictionary.
        if scope["type"] == "http":
            self.last_scope = scope
        await self.trace(scope, receive, send)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope = dict(scope)
            scope["scheme"] = "http"
            scope["client"] = (self.peer, 49152)
            if self.normalize:
                scope["headers"] = [
                    (name, value)
                    for name, value in scope["headers"]
                    if name.lower() != b"x-forwarded-proto"
                ] + [(b"x-forwarded-proto", b"https")]
        await self.app(scope, receive, send)


def production_settings(settings):
    values = auth_settings(settings).model_dump()
    values.update(
        environment="production",
        database_url=SecretStr(
            "postgresql+psycopg://fixture:synthetic@db.example.invalid/fixture?sslmode=verify-full"
        ),
        database_schema="trace",
        cors_origins=(SITE,),
        cookie_secure=True,
        allow_insecure_local_cookies=False,
    )
    return Settings(_env_file=None, **values)


def edge_settings(*, enabled=True):
    return RenderEdgeSettings(
        _env_file=None,
        mode="enabled" if enabled else "disabled",
        hostname=HOST,
        trusted_private_perimeter_confirmed=True,
        render="true",
        render_service_type="web",
        render_service_id="srv-fixture",
        render_external_hostname=HOST,
    )


@dataclass
class Integration:
    app: object
    hop: SimulatedRenderPublicEdge
    signers: tuple

    def headers(self, user=0):
        result = {"Origin": SITE, "X-Trace-Client": "learning-web"}
        if user is not None:
            result["Authorization"] = "Bearer " + self.signers[user].token()
        return result

    def connection(self):
        return TestClient(self.hop, base_url="https://" + HOST)


@pytest.fixture
def integration(settings, database):
    config = production_settings(settings)
    signers = SigningFixture(), SigningFixture(kid="second-user")
    verifier = JwtVerifier(config, KeysFixture(*signers))
    repository = SqlLearningRepository(database)
    seed_first_lesson(repository)
    seed_transfer_lesson(repository)
    app = create_app(
        config,
        database,
        jwt_verifier=verifier,
        ai_settings=AIClientSettings(_env_file=None, mode="disabled"),
        accounting_settings=AccountingSettings(
            _env_file=None, mode="durable", scope="render-edge-integration"
        ),
        render_edge_settings=edge_settings(),
    )
    yield Integration(app, SimulatedRenderPublicEdge(app), signers)
    verifier.close()


def post(client, path, body, *, key=None):
    return client.post(
        "/api/v1" + path, json=body, headers={"Idempotency-Key": key or str(uuid4())}
    )


def assert_cors(response):
    assert response.headers["access-control-allow-origin"] == SITE
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "origin" in response.headers.get("vary", "").lower()


def test_36_consecutive_real_preflights_survive_changing_internal_peers(integration):
    targets = (
        ("/api/v1/account/me", "GET"),
        ("/api/v1/custom-lessons/languages", "GET"),
        ("/api/v1/custom-lessons/requests", "POST"),
    )
    observed_pairs = set()
    with integration.connection() as client:
        for index in range(36):
            integration.hop.peer = PEERS[(index // len(targets)) % len(PEERS)]
            path, method = targets[index % len(targets)]
            response = client.options(
                path,
                headers={
                    "Origin": SITE,
                    "Access-Control-Request-Method": method,
                    "Access-Control-Request-Headers": "authorization,content-type,idempotency-key",
                    # Synthetic caller-controlled headers: the simulated edge
                    # explicitly replaces XFP, exactly as its documented model.
                    "X-Forwarded-Proto": "http,https",
                    "X-Forwarded-For": "203.0.113.99",
                },
            )
            assert response.status_code == 200
            assert_cors(response)
            assert integration.hop.last_scope["client"] == (integration.hop.peer, 49152)
            assert integration.hop.last_scope["scheme"] == "https"
            observed_pairs.add((path, integration.hop.peer))
    assert len(observed_pairs) == len(targets) * len(PEERS)


@pytest.mark.parametrize("peer", PEERS)
def test_real_account_catalog_and_custom_languages_with_no_client_ip_promotion(integration, peer):
    integration.hop.peer = peer
    with integration.connection() as client:
        client.headers.update(integration.headers())
        client.headers["X-Forwarded-For"] = "203.0.113.99"
        response = client.get("/api/v1/account/me")
        assert response.status_code == 200
        assert response.json()["roles"] == ["learner"]
        assert response.headers["cache-control"] == "no-store"
        assert_cors(response)
        assert integration.hop.last_scope["client"] == (peer, 49152)
        for lesson in ("fastapi-payload-mismatch", "fastapi-nested-payload-transfer"):
            response = client.get("/api/v1/lessons/" + lesson)
            assert response.status_code == 200
            assert response.json()["version"] == "1.0.0"
        assert client.get("/api/v1/custom-lessons/languages").status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [("X-Forwarded-Proto", "http")],
        [("X-Forwarded-Proto", "https,http")],
        [("X-Forwarded-Proto", "https,https")],
        [("X-Forwarded-Proto", "HTTPS")],
        [("X-Forwarded-Proto", " https")],
        [("X-Forwarded-Proto", "https"), ("x-forwarded-proto", "https")],
    ],
)
def test_direct_missing_malformed_duplicate_scheme_is_rejected_with_cors(integration, headers):
    integration.hop.normalize = False
    with integration.connection() as client:
        response = client.get("/api/v1/account/me", headers=[("Origin", SITE), *headers])
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "https_required"
        assert response.headers["cache-control"] == "no-store"
        assert_cors(response)


def test_default_strict_profile_ignores_spoofed_scheme(settings, database):
    config = production_settings(settings)
    app = create_app(
        config,
        database,
        ai_settings=AIClientSettings(_env_file=None, mode="disabled"),
        accounting_settings=AccountingSettings(
            _env_file=None, mode="durable", scope="strict-edge-integration"
        ),
        render_edge_settings=edge_settings(enabled=False),
    )
    direct = SimulatedRenderPublicEdge(app, normalize=False)
    with TestClient(direct, base_url="https://" + HOST) as client:
        response = client.get(
            "/api/v1/account/me",
            headers={"Origin": SITE, "X-Forwarded-Proto": "https"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "https_required"
        assert direct.last_scope["scheme"] == "http"
        assert direct.last_scope["client"] == (PEERS[0], 49152)


def test_raw_loopback_health_probe_preserves_route_contract_without_scheme_promotion(integration):
    integration.hop.normalize = False
    integration.hop.peer = "127.0.0.1"
    with integration.connection() as client:
        for path in ("live", "ready"):
            response = client.get("/api/v1/health/" + path)
            assert response.status_code == 200
            assert integration.hop.last_scope["scheme"] == "http"
            assert client.head("/api/v1/health/" + path).status_code == 405
        assert client.get("/api/v1/account/me").status_code == 400


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Forwarded-For": "127.0.0.1"},
        {"Forwarded": "for=127.0.0.1;proto=https"},
    ],
)
def test_forwarded_loopback_cannot_create_raw_health_probe_exception(integration, headers):
    integration.hop.normalize = False
    with integration.connection() as client:
        response = client.get("/api/v1/health/live", headers=headers)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "https_required"


@pytest.mark.parametrize("credential", [{"Authorization": "Bearer invalid"}, {"Cookie": "x=y"}])
def test_loopback_health_transport_exception_is_credential_free(integration, credential):
    integration.hop.normalize = False
    integration.hop.peer = "127.0.0.1"
    with integration.connection() as client:
        response = client.get("/api/v1/health/live", headers=credential)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "https_required"


def test_supabase_authentication_ownership_and_origin_are_preserved(integration):
    with integration.connection() as client:
        missing = client.get("/api/v1/account/me", headers={"Origin": SITE})
        assert missing.status_code == 401
        assert_cors(missing)
        invalid = client.get(
            "/api/v1/account/me", headers={"Origin": SITE, "Authorization": "Bearer invalid"}
        )
        assert invalid.status_code == 401
        assert_cors(invalid)
        client.headers.update(integration.headers(0))
        created = post(
            client, "/sessions", {"lesson_id": "fastapi-payload-mismatch", "version": "1.0.0"}
        )
        assert created.status_code == 201
        session = created.json()["id"]
        client.headers.update(integration.headers(1))
        hidden = client.get(f"/api/v1/sessions/{session}/progress")
        assert hidden.status_code == 404
        assert_cors(hidden)
        client.headers["Origin"] = "https://attacker.example.invalid"
        denied = post(
            client, "/sessions", {"lesson_id": "fastapi-payload-mismatch", "version": "1.0.0"}
        )
        assert denied.status_code == 403
        assert "access-control-allow-origin" not in denied.headers


def test_guest_secure_cookie_claim_and_invalid_bearer_no_fallback(integration):
    with integration.connection() as client:
        client.headers.update(integration.headers(user=None))
        anonymous = post(client, "/learners/anonymous", {})
        assert anonymous.status_code == 200 and client.cookies.get(COOKIE_NAME)
        cookie = anonymous.headers["set-cookie"].lower()
        assert "httponly" in cookie and "secure" in cookie
        assert "path=/api/v1" in cookie and "samesite=lax" in cookie
        assert client.get("/api/v1/learners/me").status_code == 200
        client.headers["Authorization"] = "Bearer invalid"
        assert client.get("/api/v1/learners/me").status_code == 401
        client.headers.update(integration.headers())
        account = client.get("/api/v1/account/me")
        assert account.status_code == 200 and account.json()["anonymous_history_available"] is True
        assert post(client, "/account/claim-anonymous", {}).status_code == 200
        assert client.get("/api/v1/account/me/learner").status_code == 200


def test_real_notes_execution_verification_and_idempotent_readback(integration, database):
    with integration.connection() as client:
        client.headers.update(integration.headers())
        key = str(uuid4())
        body = {"lesson_id": "fastapi-payload-mismatch", "version": "1.0.0"}
        created = post(client, "/sessions", body, key=key)
        assert created.status_code == 201
        session = created.json()["id"]
        assert post(client, "/sessions", body, key=key).json()["id"] == session
        predicted = post(
            client,
            f"/sessions/{session}/prediction",
            {"selected_answer": "rejected", "reasoning": "The payload names differ."},
        )
        assert predicted.status_code == 201
        wrong = post(
            client,
            f"/sessions/{session}/attempts",
            {"change_type": "rename_payload_field", "field_name": "body"},
        )
        assert wrong.status_code == 201
        failed = post(client, f"/sessions/{session}/attempts/{wrong.json()['id']}/verify", {})
        assert failed.status_code == 200 and failed.json()["status"] == "failed"
        corrected = post(
            client,
            f"/sessions/{session}/attempts",
            {"change_type": "rename_payload_field", "field_name": "content"},
        )
        assert corrected.status_code == 201
        verify_key = str(uuid4())
        path = f"/sessions/{session}/attempts/{corrected.json()['id']}/verify"
        verified = post(client, path, {}, key=verify_key)
        assert verified.status_code == 200 and verified.json()["status"] == "passed"
        assert all(check["matched"] for check in verified.json()["checks"])
        assert post(client, path, {}, key=verify_key).json() == verified.json()
        progress = client.get(f"/api/v1/sessions/{session}/progress")
        assert progress.status_code == 200 and progress.json()["session"]["state"] == "completed"
        assert len(progress.json()["attempts"]) == 2
        assert client.get("/api/v1/learners/me/journey").status_code == 200
    with database.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
