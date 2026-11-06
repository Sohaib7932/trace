"""The real protected APIs, signed fixture JWTs and disposable databases only."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select

from app.auth.jwt import JwtVerifier
from app.db import knowledge_models as k
from app.db.accounts import SqlAccountRepository
from app.domain.knowledge import KnowledgeRevision, sealed
from app.main import create_app
from app.services.accounts import AccountService
from scripts.corpus_operator import (
    CorpusOperatorError,
    _histories,
    checked_package,
    decode_history,
    execute,
)
from scripts.operator_http import FRONTEND_ORIGIN, OperatorHTTP, OperatorHTTPError
from tests.auth_fixtures import KeysFixture, SigningFixture, auth_settings
from tests.integration.test_knowledge_archive import archive as archive  # noqa: F401


@pytest.fixture
def operator(archive, settings):
    config = auth_settings(settings).model_copy(update={"cors_origins": (FRONTEND_ORIGIN,)})
    signer = SigningFixture(clock=lambda: archive.now[0])
    ordinary = SigningFixture(kid="ordinary", clock=lambda: archive.now[0])
    verifier = JwtVerifier(config, KeysFixture(signer, ordinary), clock=lambda: archive.now[0])
    accounts = AccountService(SqlAccountRepository(archive.database), lambda: archive.now[0])
    account = accounts.bootstrap(verifier.verify(signer.token()))
    accounts.grant(account.id, "admin", "synthetic-operator", "Disposable operator test.")
    app = create_app(config, archive.database, clock=lambda: archive.now[0], jwt_verifier=verifier)
    calls = []
    with TestClient(app) as api:

        def transport(request):
            calls.append((request.method, request.url.path))
            result = api.request(
                request.method,
                request.url.path,
                content=request.content,
                headers=dict(request.headers),
            )
            return httpx2.Response(
                result.status_code, content=result.content, headers=dict(result.headers)
            )

        with OperatorHTTP(
            SecretStr(signer.token()), transport=httpx2.MockTransport(transport)
        ) as client:
            yield SimpleNamespace(
                client=client,
                archive=archive,
                calls=calls,
                transport=transport,
                account=account,
                signer=signer,
                ordinary=ordinary,
            )


def run(operator, key, *, publish=False):
    return execute(
        operator.client, operation_id=key, publish=publish, clock=lambda: operator.archive.now[0]
    )


def test_real_admin_import_then_initial_publication_and_same_key_resume(operator):
    key = uuid4()
    assert run(operator, key)["status"] == "review_adopted"
    assert not operator.archive.knowledge.available
    result = run(operator, key, publish=True)
    snapshot = operator.archive.knowledge.snapshot()
    assert result["published"] and result["source_count"] == 9 and result["passage_count"] == 19
    assert snapshot.available and result["manifest_sha256"] == snapshot.manifest_sha256
    assert run(operator, key, publish=True) == result
    # Exactly five knowledge calls across all three commands: no nine-read burst.
    assert len([path for _, path in operator.calls if "/knowledge/" in path]) == 5
    with operator.archive.database.session() as session:
        assert session.scalar(select(func.count()).select_from(k.KnowledgeRevisionRow)) == 9
        assert session.scalar(select(func.count()).select_from(k.KnowledgePublicationRow)) == 1


def test_another_operation_cannot_replace_current_publication(operator):
    original = run(operator, uuid4(), publish=True)
    with pytest.raises(OperatorHTTPError) as error:
        run(operator, uuid4(), publish=True)
    assert error.value.code == "conflict" and not error.value.outcome_unknown
    snapshot = operator.archive.knowledge.snapshot()
    assert snapshot.publication_sequence == 0
    assert snapshot.manifest_sha256 == original["manifest_sha256"]


def test_import_commit_with_lost_response_can_be_deliberately_resumed_without_duplicate(operator):
    key, lost = uuid4(), [False]

    def flaky(request):
        result = operator.transport(request)
        if request.url.path.endswith("/import-reviewed-corpus") and not lost[0]:
            lost[0] = True
            raise httpx2.ReadTimeout("synthetic-lost-response-canary")
        return result

    with OperatorHTTP(
        SecretStr(operator.signer.token()), transport=httpx2.MockTransport(flaky)
    ) as client:
        with pytest.raises(OperatorHTTPError) as error:
            execute(client, operation_id=key, publish=True, clock=lambda: operator.archive.now[0])
        assert error.value.code == "transport_unavailable" and error.value.outcome_unknown
        assert not operator.archive.knowledge.available
        assert execute(
            client, operation_id=key, publish=True, clock=lambda: operator.archive.now[0]
        )["published"]
    with operator.archive.database.session() as session:
        assert session.scalar(select(func.count()).select_from(k.KnowledgeRevisionRow)) == 9
        assert session.scalar(select(func.count()).select_from(k.KnowledgePublicationRow)) == 1


@pytest.mark.parametrize("identity", ["ordinary", "expired"])
def test_real_jwt_authorization_denied_before_import(operator, identity):
    token = (
        operator.ordinary.token()
        if identity == "ordinary"
        else operator.signer.token({"exp": int(operator.archive.now[0].timestamp())})
    )
    with (
        OperatorHTTP(
            SecretStr(token), transport=httpx2.MockTransport(operator.transport)
        ) as client,
        pytest.raises(OperatorHTTPError) as error,
    ):
        execute(client, operation_id=uuid4(), publish=True, clock=lambda: operator.archive.now[0])
    assert error.value.code == ("forbidden" if identity == "ordinary" else "unauthenticated")
    assert not any(method == "POST" for method, _ in operator.calls)


def test_exact_histories_reject_changed_fingerprints_review_and_actor(operator):
    payload = operator.client.request(
        "POST",
        "/api/v1/admin/knowledge/import-reviewed-corpus",
        body={"operation_key": str(uuid4()), "adopt_existing_review": True},
    )
    assert _histories(
        payload, operator.archive.package, operator.account.id, operator.archive.now[0]
    )
    for mutate in ("missing", "duplicate", "raw_digest", "actor", "review"):
        changed = deepcopy(payload)
        if mutate == "missing":
            changed.pop()
        elif mutate == "duplicate":
            changed[1] = changed[0]
        elif mutate == "raw_digest":
            changed[0]["revision"]["normalized_sha256"] = "0" * 64
        else:
            history = decode_history(changed[0])
            revision = history.revision.model_dump(exclude={"content_sha256"})
            revision["imported_review"] = history.revision.imported_review
            if mutate == "actor":
                revision["actor_id"] = str(uuid4())
            else:
                revision["imported_review"] = history.revision.imported_review.model_copy(
                    update={"reviewer_label": "different-reviewer"}
                )
            changed[0]["revision"] = sealed(KnowledgeRevision, **revision).model_dump(mode="json")
        with pytest.raises(CorpusOperatorError, match="corpus_integrity_unavailable"):
            _histories(
                changed, operator.archive.package, operator.account.id, operator.archive.now[0]
            )


def test_expiry_and_changed_installed_package_are_rejected_offline(operator, monkeypatch):
    from scripts import corpus_operator

    with pytest.raises(CorpusOperatorError):
        checked_package(lambda: operator.archive.package.valid_until + timedelta(seconds=1))
    changed = operator.archive.package.model_copy(update={"revision": "2.0.0"})
    monkeypatch.setattr(corpus_operator, "load_corpus_package", lambda: changed)
    with pytest.raises(CorpusOperatorError):
        checked_package(lambda: operator.archive.now[0])
    assert operator.calls == []


def test_valid_but_wrong_publication_manifest_is_unknown_not_success(operator):
    from app.support.versioning import canonical_digest

    def forged_receipt(request):
        response = operator.transport(request)
        if request.url.path.endswith("/publications") and response.status_code == 200:
            receipt = response.json()
            receipt["manifest_sha256"] = "0" * 64
            receipt["content_sha256"] = canonical_digest(
                {key: value for key, value in receipt.items() if key != "content_sha256"}
            )
            return httpx2.Response(200, json=receipt)
        return response

    with (
        OperatorHTTP(
            SecretStr(operator.signer.token()), transport=httpx2.MockTransport(forged_receipt)
        ) as client,
        pytest.raises(OperatorHTTPError) as error,
    ):
        execute(client, operation_id=uuid4(), publish=True, clock=lambda: operator.archive.now[0])
    assert error.value.code == "invalid_response" and error.value.outcome_unknown
    assert operator.archive.knowledge.available
