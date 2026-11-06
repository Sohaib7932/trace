from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, update
from sqlalchemy.exc import OperationalError

from app.auth.jwt import JwtVerifier
from app.db import models as m
from app.db.session import Database
from app.services.identity import COOKIE_NAME
from tests.auth_fixtures import KeysFixture, SigningFixture, auth_settings
from tests.integration.test_learning import start

ORIGIN = "http://localhost:3000"
HEADERS = {"Origin": ORIGIN, "X-Trace-Client": "learning-web"}


def identity_counts(database: Database) -> tuple[int, int]:
    with database.session() as fresh:
        return (
            fresh.scalar(select(func.count()).select_from(m.Learner)),
            fresh.scalar(select(func.count()).select_from(m.LearnerCredential)),
        )


@pytest.fixture
def signer(learning_app: FastAPI) -> SigningFixture:
    signer = SigningFixture()
    config = auth_settings(learning_app.state.settings)
    learning_app.state.settings = config
    learning_app.state.jwt_verifier = JwtVerifier(config, KeysFixture(signer))
    return signer


@pytest.mark.parametrize("cookie_kind", ["missing", "malformed", "unknown", "expired", "revoked"])
def test_cross_site_unusable_guest_bootstrap_stops_before_creating_identities(
    learning_app: FastAPI, database: Database, cookie_kind: str
) -> None:
    with TestClient(learning_app) as browser:
        browser.headers.update(HEADERS)
        raw = None
        if cookie_kind in {"expired", "revoked"}:
            assert browser.post("/api/v1/learners/anonymous", json={}).status_code == 200
            raw = browser.cookies.get(COOKIE_NAME)
            values = (
                {"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
                if cookie_kind == "expired"
                else {"revoked_at": datetime.now(UTC)}
            )
            with database.session() as fresh, fresh.begin():
                fresh.execute(update(m.LearnerCredential).values(**values))
        elif cookie_kind != "missing":
            raw = "invalid" if cookie_kind == "malformed" else "x" * 43
        browser.cookies.clear()
        if raw is not None:
            browser.cookies.set(COOKIE_NAME, raw)
        before = identity_counts(database)
        browser.headers["Sec-Fetch-Site"] = "cross-site"
        for _ in range(3):
            response = browser.post("/api/v1/learners/anonymous", json={})
            assert response.status_code == 409
            assert response.json()["error"]["code"] == "guest_sign_in_required"
            assert (
                response.json()["error"]["message"]
                == "Sign in to start learning from this address."
            )
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["access-control-allow-origin"] == ORIGIN
            assert response.headers["access-control-allow-credentials"] == "true"
            assert "set-cookie" not in response.headers
            assert identity_counts(database) == before


def test_cross_site_valid_guest_is_authenticated_read_only_without_cookie_renewal(
    learner: TestClient, database: Database
) -> None:
    expected = learner.get("/api/v1/learners/me").json()
    expires_at = datetime.now(UTC) + timedelta(seconds=60)
    with database.session() as fresh, fresh.begin():
        fresh.execute(update(m.LearnerCredential).values(expires_at=expires_at))
    writes = []

    def capture_write(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    before = identity_counts(database)
    event.listen(database.engine, "before_cursor_execute", capture_write)
    try:
        response = learner.post(
            "/api/v1/learners/anonymous", json={}, headers={"Sec-Fetch-Site": "cross-site"}
        )
    finally:
        event.remove(database.engine, "before_cursor_execute", capture_write)
    assert response.status_code == 200
    assert response.json()["learner_id"] == expected["learner_id"]
    assert datetime.fromisoformat(response.json()["expires_at"]) == expires_at
    assert "set-cookie" not in response.headers
    assert response.headers["cache-control"] == "no-store"
    assert writes == []
    assert identity_counts(database) == before


def test_cross_site_verified_account_bootstrap_does_not_require_a_guest_cookie(
    learning_app: FastAPI, database: Database, signer: SigningFixture
) -> None:
    with TestClient(learning_app) as browser:
        browser.headers.update(
            {**HEADERS, "Sec-Fetch-Site": "cross-site", "Authorization": "Bearer " + signer.token()}
        )
        response = browser.post("/api/v1/learners/anonymous", json={})
        assert response.status_code == 200
        assert browser.get("/api/v1/learners/me").json() == response.json()
        assert "set-cookie" not in response.headers
        assert identity_counts(database) == (1, 0)


@pytest.mark.parametrize("fetch_site", [None, "same-site"])
def test_normal_guest_bootstrap_and_claim_keep_the_existing_identity_contract(
    learning_app: FastAPI, database: Database, signer: SigningFixture, fetch_site: str | None
) -> None:
    with TestClient(learning_app) as browser:
        browser.headers.update(HEADERS)
        if fetch_site is not None:
            browser.headers["Sec-Fetch-Site"] = fetch_site
        response = browser.post("/api/v1/learners/anonymous", json={})
        assert response.status_code == 200
        guest_id = response.json()["learner_id"]
        assert "httponly" in response.headers["set-cookie"].lower()
        assert "samesite=lax" in response.headers["set-cookie"].lower()
        assert browser.post("/api/v1/learners/anonymous", json={}).json() == response.json()
        browser.headers["Authorization"] = "Bearer " + signer.token()
        key = str(uuid4())
        claim = browser.post(
            "/api/v1/account/claim-anonymous", json={}, headers={"Idempotency-Key": key}
        )
        assert claim.status_code == 200
        assert claim.json()["learner_id"] == guest_id
        assert (
            browser.post(
                "/api/v1/account/claim-anonymous", json={}, headers={"Idempotency-Key": key}
            ).json()
            == claim.json()
        )
        assert browser.cookies.get(COOKIE_NAME) is None
        browser.headers["Sec-Fetch-Site"] = "cross-site"
        assert browser.post("/api/v1/learners/anonymous", json={}).json()["learner_id"] == guest_id
        assert identity_counts(database) == (1, 1)
        with database.session() as fresh:
            assert fresh.scalar(select(m.LearnerCredential.revoked_at)) is not None


def test_cross_site_invalid_bearer_still_fails_authentication_instead_of_guest_fallback(
    learning_app: FastAPI, database: Database, signer: SigningFixture
) -> None:
    with TestClient(learning_app) as browser:
        browser.headers.update(
            {**HEADERS, "Sec-Fetch-Site": "cross-site", "Authorization": "Bearer invalid"}
        )
        response = browser.post("/api/v1/learners/anonymous", json={})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthenticated"
        assert identity_counts(database) == (0, 0)


def test_forged_fetch_metadata_never_authenticates_or_exposes_another_learner(
    learner: TestClient, learning_app: FastAPI
) -> None:
    victim = learner.get("/api/v1/learners/me").json()["learner_id"]
    session = start(learner)
    with TestClient(learning_app) as attacker:
        attacker.headers.update(
            {
                **HEADERS,
                "Sec-Fetch-Site": "same-site",
                "X-Learner-ID": victim,
                "Forwarded": "for=192.0.2.1;proto=https",
                "X-Forwarded-For": "192.0.2.1",
            }
        )
        assert attacker.get("/api/v1/learners/me").status_code == 401
        assert attacker.get(f"/api/v1/sessions/{session}/progress").status_code == 401
        created = attacker.post("/api/v1/learners/anonymous", json={})
        assert created.status_code == 200
        assert UUID(created.json()["learner_id"]) != UUID(victim)
        assert attacker.get(f"/api/v1/sessions/{session}/progress").status_code == 404


def test_cross_site_credential_lookup_outage_remains_an_infrastructure_error(
    learning_app: FastAPI, database: Database
) -> None:
    def unavailable(*args):
        raise OperationalError("synthetic lookup", {}, RuntimeError("synthetic dependency failure"))

    with TestClient(learning_app) as browser:
        browser.headers.update({**HEADERS, "Sec-Fetch-Site": "cross-site"})
        browser.cookies.set(COOKIE_NAME, "x" * 43)
        event.listen(database.engine, "before_cursor_execute", unavailable)
        try:
            response = browser.post("/api/v1/learners/anonymous", json={})
        finally:
            event.remove(database.engine, "before_cursor_execute", unavailable)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "dependency_unavailable"
        assert "synthetic" not in response.text
        assert identity_counts(database) == (0, 0)


@pytest.mark.parametrize(
    ("method", "body", "status", "code"),
    [
        ("GET", None, 401, "unauthenticated"),
        ("POST", {}, 409, "guest_sign_in_required"),
        ("POST", {"unsupported": True}, 422, "validation_error"),
    ],
)
def test_learning_auth_application_and_validation_errors_are_never_cacheable(
    learning_app: FastAPI,
    method: str,
    body: dict[str, object] | None,
    status: int,
    code: str,
) -> None:
    with TestClient(learning_app) as browser:
        browser.headers.update({**HEADERS, "Sec-Fetch-Site": "cross-site"})
        if method == "GET":
            response = browser.get("/api/v1/learners/me")
        else:
            response = browser.post("/api/v1/learners/anonymous", json=body)
        assert response.status_code == status
        assert response.json()["error"]["code"] == code
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["access-control-allow-origin"] == ORIGIN
        assert response.headers["access-control-allow-credentials"] == "true"
        assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
