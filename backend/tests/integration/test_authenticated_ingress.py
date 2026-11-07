"""Real RSA workload proof, current app wiring and disposable authentication records."""

import asyncio
import json
from datetime import UTC, datetime
from hashlib import sha256
from threading import Event
from uuid import uuid4

import anyio
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.responses import JSONResponse
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.auth.jwt import JwtVerifier
from app.auth.workload_ingress import (
    AuthenticatedIngressMiddleware,
    IngressConfig,
    IngressFailure,
    WorkloadVerifier,
)
from app.core.accounting_settings import AccountingSettings
from app.core.https_middleware import ProductionHTTPSMiddleware
from app.core.ingress_settings import IngressSettings
from app.db.learning import SqlLearningRepository
from app.main import create_app
from app.services.catalog import seed_first_lesson
from tests.auth_fixtures import KeysFixture, SigningFixture
from tests.integration.test_render_edge_http import SITE, edge_settings, production_settings

NOW = datetime(2026, 11, 7, tzinfo=UTC)
AT = int(NOW.timestamp())
DIGEST = sha256(b"team_fixture\nprj_fixture").hexdigest()
PROOF = "X-Trace-Ingress-Authorization"
MARKER = "X-Trace-Ingress-Verified"
ACCOUNT = "/api/v1/account/me"
HEALTH = "/api/v1/health/live"


class Keys:
    def __init__(self, public):
        self.data = {"keys": [public]}
        self.calls = 0
        self.outage = False

    def fetch(self):
        self.calls += 1
        if self.outage:
            raise RuntimeError("synthetic-private-JWKS-error")
        return self.data


@pytest.fixture(scope="module")
def signing_key():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    public.update(kid="fixture-key", alg="RS256", use="sig")
    return private, public


def token(private, config, *, kid="fixture-key", extra_header=None, **changes):
    claims = {
        "iss": config.issuer,
        "aud": "https://vercel.com/sohaibp11-1003",
        "sub": "owner:sohaibp11-1003:project:trace:environment:production",
        "owner": "sohaibp11-1003",
        "owner_id": "team_fixture",
        "project": "trace",
        "project_id": "prj_fixture",
        "environment": "production",
        "iat": AT,
        "nbf": AT,
        "exp": AT + 7200,
    }
    claims.update(changes)
    return jwt.encode(
        claims, private, algorithm="RS256", headers={"kid": kid, **(extra_header or {})}
    )


@pytest.fixture
def workload(signing_key):
    private, public = signing_key
    keys = Keys(public)
    clock = [NOW]
    mono = [100.0]
    verifier = WorkloadVerifier(
        IngressConfig("team", DIGEST), keys, lambda: clock[0], monotonic=lambda: mono[0]
    )
    try:
        yield verifier, private, keys, clock, mono
    finally:
        verifier.close()


def proof(workload, **changes):
    verifier, private, *_ = workload
    return {PROOF: "Bearer " + token(private, verifier.config, **changes)}


def ingress_settings(mode="verify"):
    return IngressSettings(_env_file=None, mode=mode, identity_sha256=DIGEST)


def accounting():
    return AccountingSettings(_env_file=None, mode="durable", scope="ingress-test")


def transport_client(app, *, scheme="http", peer="10.88.0.4"):
    # Same stock parser, with a known synthetic trusted peer. All tested Render
    # hops are ASGI simulations. Tests never access the production network.
    wrapped = ProxyHeadersMiddleware(app, trusted_hosts="192.0.2.1/32")
    return TestClient(wrapped, base_url=f"{scheme}://testserver", client=(peer, 42100))


def observe(workload, *, required=False, scheme="http", peer="10.88.0.4"):
    async def downstream(scope, receive, send):
        if scope["type"] == "lifespan":
            for phase in ("startup", "shutdown"):
                assert (await receive())["type"] == f"lifespan.{phase}"
                await send({"type": f"lifespan.{phase}.complete"})
            return
        headers = dict(scope["headers"])
        await JSONResponse(
            {
                "scheme": scope["scheme"],
                "peer": scope["client"][0],
                "learner": headers.get(b"authorization", b"").decode(),
                "proof_present": b"x-trace-ingress-authorization" in headers,
            },
            headers={MARKER: "spoofed-downstream-marker", "Cache-Control": "public, max-age=60"},
        )(scope, receive, send)

    middleware = AuthenticatedIngressMiddleware(
        ProductionHTTPSMiddleware(downstream),
        verifier_factory=lambda: workload[0],
        required=required,
    )
    return transport_client(middleware, scheme=scheme, peer=peer)


@pytest.mark.parametrize("peer", ["10.88.0.4", "10.99.0.7", "192.0.2.1"])
def test_proof_establishes_https_and_preserves_stock_client_trust(workload, peer):
    with observe(workload, peer=peer) as client:
        response = client.get(
            ACCOUNT,
            headers={
                **proof(workload),
                "Authorization": "Bearer synthetic-learner",
                "X-Forwarded-For": "203.0.113.4",
            },
        )
    assert response.status_code == 200
    assert response.headers.get_list(MARKER) == ["1"]
    assert response.headers.get_list("Cache-Control") == ["no-store"]
    assert response.json() == {
        "scheme": "https",
        "peer": "203.0.113.4" if peer == "192.0.2.1" else peer,
        "learner": "Bearer synthetic-learner",
        "proof_present": False,
    }


@pytest.mark.parametrize("required", [False, True])
@pytest.mark.parametrize("scheme", ["http", "https"])
def test_missing_proof_follows_mode_and_never_echoes_marker(workload, required, scheme):
    with observe(workload, required=required, scheme=scheme) as client:
        result = client.get(ACCOUNT, headers={"X-Forwarded-Proto": "https"})
    assert result.status_code == (403 if required else 400 if scheme == "http" else 200)
    assert MARKER not in result.headers and workload[2].calls == 0


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Trace-Ingress-Proto": "https"},
        {"X-Trace-Ingress-Client-IP": "127.0.0.1"},
        {MARKER: "1"},
        {PROOF: "Bearer malformed"},
        {PROOF: "Basic aa.bb.cc"},
        {PROOF: "Bearer " + "x" * 16385},
    ],
)
def test_spoof_or_malformed_header_is_rejected_even_over_https(workload, headers):
    with observe(workload, scheme="https") as client:
        result = client.get(ACCOUNT, headers=headers)
    assert result.status_code == 403 and result.json()["error"]["code"] == "ingress_rejected"
    assert MARKER not in result.headers and workload[2].calls == 0


def test_duplicate_and_extra_workload_headers_are_rejected(workload):
    value = proof(workload)[PROOF]
    with observe(workload) as client:
        for headers in (
            [(PROOF, value), (PROOF.lower(), value)],
            [(PROOF, value), ("X-Trace-Ingress-Proto", "https")],
        ):
            result = client.get(ACCOUNT, headers=headers)
            assert result.status_code == 403 and MARKER not in result.headers
    assert workload[2].calls == 0


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://oidc.vercel.com"},
        {"aud": "https://vercel.com/other"},
        {"aud": ["https://vercel.com/sohaibp11-1003"]},
        {"sub": "owner:sohaibp11-1003:project:trace:environment:preview"},
        {"owner": "other"},
        {"owner_id": "team_other"},
        {"project": "other"},
        {"project_id": "prj_other"},
        {"project_id": "prj_fixture\nother"},
        {"environment": "preview"},
        {"environment": "development"},
        {"iat": True},
        {"iat": AT + 1},
        {"nbf": AT + 1},
        {"exp": AT},
        {"exp": AT + 7201},
    ],
)
def test_real_signature_with_wrong_identity_or_time_never_asserts_https(workload, claims):
    with observe(workload) as client:
        result = client.get(ACCOUNT, headers=proof(workload, **claims))
    assert result.status_code == 403 and MARKER not in result.headers


@pytest.mark.parametrize("mode", ["team", "global"])
def test_issuer_is_pinned_to_its_official_jwks_and_verified(mode, signing_key):
    private, public = signing_key
    config = IngressConfig(mode, DIGEST)
    issuer = "https://oidc.vercel.com" + ("/sohaibp11-1003" if mode == "team" else "")
    assert config.issuer == issuer and config.jwks_url == issuer + "/.well-known/jwks"
    verifier = WorkloadVerifier(config, Keys(public), lambda: NOW)
    try:
        assert verifier.verify(token(private, config)).expires_at.timestamp() == AT + 7200
    finally:
        verifier.close()


def test_bad_signature_and_attacker_key_url_cannot_authorize(workload):
    verifier, private, keys, *_ = workload
    forged = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(IngressFailure):
        verifier.verify(token(forged, verifier.config))
    with pytest.raises(IngressFailure):
        verifier.verify(
            token(private, verifier.config, extra_header={"jku": "https://invalid.test"})
        )
    assert keys.calls == 1


def test_jwks_cache_rotation_outage_and_owned_deadline(workload):
    verifier, private, keys, _, mono = workload
    assert verifier.verify(token(private, verifier.config))
    assert keys.calls == 1
    with pytest.raises(IngressFailure):
        verifier.verify(token(private, verifier.config, kid="unknown"))
    assert keys.calls == 1
    mono[0] += 301
    keys.outage = True
    with observe(workload) as client:
        result = client.get(ACCOUNT, headers=proof(workload))
    assert result.status_code == 503 and MARKER not in result.headers
    assert "synthetic-private" not in result.text and keys.calls == 2


def test_worker_slots_survive_cancellation_until_actual_key_fetch_finishes(workload):
    verifier, _, keys, *_ = workload
    entered, release = Event(), Event()
    fetch = keys.fetch

    def hold():
        entered.set()
        assert release.wait(5)
        return fetch()

    keys.fetch = hold
    value = proof(workload)[PROOF][7:]

    async def exercise():
        tasks = [asyncio.create_task(verifier.verify_async(value)) for _ in range(4)]
        try:
            assert await anyio.to_thread.run_sync(entered.wait, 2)
            tasks[0].cancel()
            with pytest.raises(asyncio.CancelledError):
                await tasks[0]
            assert not verifier.wait_for_idle(0)
            with pytest.raises(IngressFailure) as saturated:
                await verifier.verify_async(value)
            assert saturated.value.status_code == 503
        finally:
            release.set()
        assert len(await asyncio.gather(*tasks[1:])) == 3
        assert await anyio.to_thread.run_sync(verifier.wait_for_idle, 2)

    anyio.run(exercise)


@pytest.mark.parametrize(
    ("path", "headers", "method", "expected"),
    [
        (HEALTH, {}, "GET", 200),
        (HEALTH, {}, "HEAD", 200),
        (HEALTH + "/", {}, "GET", 403),
        (HEALTH + "?probe=1", {}, "GET", 403),
        (HEALTH, {"Authorization": "Bearer synthetic"}, "GET", 403),
        (HEALTH, {"Cookie": "trace_learner=synthetic"}, "GET", 403),
        (HEALTH, {"Content-Length": "1"}, "GET", 403),
        (HEALTH, {}, "OPTIONS", 403),
    ],
)
def test_required_only_exempts_bare_exact_health(workload, path, headers, method, expected):
    with observe(workload, required=True, peer="127.0.0.1") as client:
        result = client.request(method, path, headers=headers)
    assert result.status_code == expected and MARKER not in result.headers


def test_health_exception_still_uses_the_original_https_boundary(workload):
    with observe(workload, required=True) as client:
        result = client.get(HEALTH)
    assert result.status_code == 400 and result.json()["error"]["code"] == "https_required"
    assert MARKER not in result.headers


def test_settings_fail_closed_before_installing_conflicting_profiles(settings):
    assert IngressSettings(_env_file=None).mode == "disabled"
    with pytest.raises(ValidationError):
        IngressSettings(_env_file=None, mode="required")
    with pytest.raises(ValueError, match="requires production"):
        create_app(settings, ingress_settings=ingress_settings())
    with pytest.raises(ValueError, match="edge profile disabled"):
        create_app(
            production_settings(settings),
            ingress_settings=ingress_settings(),
            render_edge_settings=edge_settings(),
            accounting_settings=accounting(),
        )


def test_real_application_keeps_signed_learner_and_ownership_separate(settings, database, workload):
    config = production_settings(settings)
    first, other = SigningFixture(), SigningFixture(kid="other-user")
    learner_verifier = JwtVerifier(config, KeysFixture(first, other))
    seed_first_lesson(SqlLearningRepository(database))
    app = create_app(
        config,
        database,
        jwt_verifier=learner_verifier,
        accounting_settings=accounting(),
        ingress_settings=ingress_settings("required"),
        workload_verifier=workload[0],
    )
    try:
        with transport_client(app) as client:
            direct = client.options(
                ACCOUNT,
                headers={"Origin": SITE, "Access-Control-Request-Method": "GET"},
            )
            assert (
                direct.status_code == 403 and direct.json()["error"]["code"] == "ingress_rejected"
            )
            assert direct.headers["access-control-allow-origin"] == SITE
            assert MARKER not in direct.headers
            shared = {**proof(workload), "Origin": SITE, "X-Trace-Client": "learning-web"}
            signed_out = client.get(ACCOUNT, headers=shared)
            assert signed_out.status_code == 401 and signed_out.headers[MARKER] == "1"
            first_headers = {**shared, "Authorization": "Bearer " + first.token()}
            current = client.get(ACCOUNT, headers=first_headers)
            assert current.status_code == 200 and current.headers[MARKER] == "1"
            session = client.post(
                "/api/v1/sessions",
                json={"lesson_id": "fastapi-payload-mismatch", "version": "1.0.0"},
                headers={**first_headers, "Idempotency-Key": str(uuid4())},
            )
            assert session.status_code == 201 and session.headers[MARKER] == "1"
            foreign = client.get(
                f"/api/v1/sessions/{session.json()['id']}/progress",
                headers={**shared, "Authorization": "Bearer " + other.token()},
            )
            assert foreign.status_code == 404 and foreign.headers[MARKER] == "1"
        assert not workload[0].closed  # Injected verifier remains caller-owned.
    finally:
        learner_verifier.close()


def test_owned_verifier_stays_alive_for_nested_lifespan_then_recreates(settings, database):
    app = create_app(
        production_settings(settings),
        database,
        ingress_settings=ingress_settings(),
        accounting_settings=accounting(),
    )
    initial = app.state.workload_verifier
    with TestClient(app):
        with TestClient(app):
            assert app.state.workload_verifier is initial and not initial.closed
        assert not initial.closed
    assert initial.closed
    with TestClient(app):
        replacement = app.state.workload_verifier
        assert replacement is not initial and not replacement.closed
    assert replacement.closed
