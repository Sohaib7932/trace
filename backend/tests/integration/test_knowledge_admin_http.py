"""Admin-only HTTP contract using real JWT verification and disposable persistence."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.v1.knowledge_admin import router
from app.auth.jwt import JwtVerifier
from app.core.feedback_middleware import FeedbackSecurityMiddleware
from app.core.feedback_settings import FeedbackSettings
from app.db import knowledge_models as k
from app.db import models as m
from app.db.accounts import SqlAccountRepository
from app.main import create_app
from app.services.accounts import AccountService
from tests.auth_fixtures import KeysFixture, SigningFixture, auth_settings
from tests.integration.test_knowledge_archive import archive as archive  # noqa: F401


@pytest.fixture
def admin_api(archive, settings):
    config = auth_settings(settings)
    signer, ordinary = (
        SigningFixture(clock=lambda: archive.now[0]),
        SigningFixture(kid="ordinary", clock=lambda: archive.now[0]),
    )
    verifier = JwtVerifier(config, KeysFixture(signer, ordinary), clock=lambda: archive.now[0])
    accounts = AccountService(SqlAccountRepository(archive.database), lambda: archive.now[0])
    account = accounts.bootstrap(verifier.verify(signer.token()))
    accounts.grant(
        account.id, "admin", "synthetic-test-operator", "Disposable administrative fixture."
    )
    app = create_app(config, archive.database, clock=lambda: archive.now[0], jwt_verifier=verifier)
    # The router is also tested independently before root application wiring lands.
    if not any(
        getattr(route, "path", "").startswith("/api/v1/admin/knowledge") for route in app.routes
    ):
        app.include_router(router)
    if not any(
        middleware.kwargs.get("path_pattern", "").startswith("/api/v1/admin/knowledge")
        for middleware in app.user_middleware
    ):
        app.add_middleware(
            FeedbackSecurityMiddleware,
            settings=FeedbackSettings(_env_file=None),
            allowed_origins=config.cors_origins,
            path_pattern=r"/api/v1/admin/knowledge(?:/.*)?\Z",
            error_subject="Knowledge administration",
            error_code_prefix="knowledge",
        )
    with TestClient(app) as client:
        client.headers.update({"Origin": "http://localhost:3000", "X-Trace-Client": "learning-web"})
        yield SimpleNamespace(client=client, signer=signer, ordinary=ordinary, archive=archive)


def body(context):
    return {
        "document": context.archive.package.documents[0].model_dump(mode="json"),
        "revision": "2.0.0",
        "operation_key": str(uuid4()),
    }


def test_administration_requires_bearer_and_database_admin_not_claimed_metadata(admin_api):
    response = admin_api.client.post("/api/v1/admin/knowledge/revisions", json=body(admin_api))
    assert response.status_code == 401 and response.headers["cache-control"] == "no-store"
    token = admin_api.ordinary.token({"user_metadata": {"role": "admin", "roles": ["admin"]}})
    response = admin_api.client.post(
        "/api/v1/admin/knowledge/revisions",
        json=body(admin_api),
        headers={"Authorization": "Bearer " + token},
    )
    assert response.status_code == 403 and response.headers["cache-control"] == "no-store"
    with admin_api.archive.database.session() as session:
        assert session.scalar(select(func.count()).select_from(k.KnowledgeRevisionRow)) == 0
        assert session.scalar(select(func.count()).select_from(m.Learner)) == 0


def test_real_signed_admin_can_ingest_and_read_but_cannot_skip_lifecycle(admin_api):
    admin_api.client.headers["Authorization"] = "Bearer " + admin_api.signer.token()
    created = admin_api.client.post("/api/v1/admin/knowledge/revisions", json=body(admin_api))
    assert created.status_code == 200 and created.headers["cache-control"] == "no-store"
    result = created.json()
    assert result["events"][-1]["state"] == "ingested"
    revision_id = result["revision"]["id"]
    history = admin_api.client.get(f"/api/v1/admin/knowledge/revisions/{revision_id}")
    assert history.status_code == 200 and history.headers["cache-control"] == "no-store"
    denied = admin_api.client.post(
        f"/api/v1/admin/knowledge/revisions/{revision_id}/transitions",
        json={
            "action": "approve",
            "expected_sequence": 0,
            "operation_key": str(uuid4()),
            "reason": "A direct approval cannot bypass all earlier gates.",
        },
    )
    assert denied.status_code == 409 and denied.headers["cache-control"] == "no-store"
    assert not admin_api.archive.knowledge.available


@pytest.mark.parametrize("mutation", ["path", "private_copy", "unknown", "malformed_id"])
def test_admin_invalid_requests_are_sanitized_and_cannot_load_arbitrary_material(
    admin_api, mutation
):
    admin_api.client.headers["Authorization"] = "Bearer " + admin_api.signer.token()
    payload = body(admin_api)
    canary = "synthetic-private-admin-canary"
    if mutation == "path":
        payload["source_path"] = canary
    elif mutation == "unknown":
        payload["credential"] = canary
    elif mutation == "malformed_id":
        payload["operation_key"] = canary
    else:
        payload["document"]["passages"][0]["text"] = "api_key=" + canary
    response = admin_api.client.post("/api/v1/admin/knowledge/revisions", json=payload)
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert canary not in response.text


def test_admin_write_origin_is_required_and_expired_token_cannot_administer(admin_api):
    headers = {
        "Authorization": "Bearer " + admin_api.signer.token(),
        "Origin": "https://unapproved.example.invalid",
    }
    assert (
        admin_api.client.post(
            "/api/v1/admin/knowledge/revisions", json=body(admin_api), headers=headers
        ).status_code
        == 403
    )
    expired = admin_api.signer.token({"exp": int(admin_api.archive.now[0].timestamp())})
    response = admin_api.client.post(
        "/api/v1/admin/knowledge/revisions",
        json=body(admin_api),
        headers={"Authorization": "Bearer " + expired},
    )
    assert response.status_code == 401 and response.headers["cache-control"] == "no-store"


def test_complete_reviewed_corpus_import_and_explicit_publication_fit_admin_response_bounds(
    admin_api,
):
    admin_api.client.headers["Authorization"] = "Bearer " + admin_api.signer.token()
    imported = admin_api.client.post(
        "/api/v1/admin/knowledge/import-reviewed-corpus",
        json={"operation_key": str(uuid4()), "adopt_existing_review": True},
    )
    assert imported.status_code == 200
    histories = imported.json()
    assert len(histories) == 9
    assert all(history["events"][-1]["state"] == "approved" for history in histories)
    assert all(history["events"][-1]["action"] == "adopt_existing_review" for history in histories)
    assert 65536 < len(imported.content) <= 262144
    assert imported.headers["cache-control"] == "no-store"
    assert not admin_api.archive.knowledge.available
    published = admin_api.client.post(
        "/api/v1/admin/knowledge/publications",
        json={
            "revision_ids": [history["revision"]["id"] for history in histories],
            "expected_sequence": -1,
            "operation_key": str(uuid4()),
            "reason": "Explicit synthetic administrator publication after exact review adoption.",
        },
    )
    assert published.status_code == 200
    assert admin_api.archive.knowledge.snapshot().available
