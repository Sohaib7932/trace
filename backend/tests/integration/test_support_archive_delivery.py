"""Request-bound retrieval and durable release integration with synthetic providers."""

import io
import json
import logging
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.ai.embeddings import BoundedEmbeddingClient
from app.api.dependencies import get_http_support_service
from app.auth.jwt import JwtVerifier
from app.core.accounting_settings import AccountingSettings
from app.core.embedding_settings import EmbeddingSettings
from app.core.logging import JsonFormatter
from app.db import knowledge_models as k
from app.main import create_app
from app.schemas.support import SupportQuestion, SupportSelection, SupportSelectionResult
from app.services.support import SupportService
from app.support.embedding_index import compose_index, document_inputs
from app.support.semantic import SemanticRetrievalSettings, SemanticSupportKnowledge
from tests.auth_fixtures import KeysFixture, SigningFixture, auth_settings
from tests.integration.test_knowledge_archive import archive as archive  # noqa: F401
from tests.integration.test_knowledge_archive import publish_corpus
from tests.unit.test_embeddings import ControlledEmbeddings


class SelectingAssistant:
    def __init__(self, callback=None):
        self.callback, self.calls = callback, []

    def select(self, question, passages, *, subject):
        self.calls.append((question, passages))
        if self.callback:
            self.callback()
        return SupportSelectionResult(
            selection=SupportSelection(status="answered", passage_ids=(passages[0].passage_id,)),
            source="ai",  # Deliberate simulated provider provenance, never a live-test claim.
        )


def test_durable_snapshot_matches_exact_quotes_and_rechecks_revocation_after_provider(archive):
    histories, _ = publish_corpus(archive)
    assistant = SelectingAssistant()
    service = SupportService(assistant, archive.knowledge)
    question = SupportQuestion(question="password recovery expired link")
    answer = service.answer_with_provenance(question)
    assert answer.response.status == "answered"
    assert answer.manifest_sha256 == archive.knowledge.snapshot().manifest_sha256
    assert answer.passages[0].passage_sha256
    assert answer.response.references[0].quote == assistant.calls[0][1][0].text

    def revoke():
        history = archive.service.get(histories[0].revision.id, actor=archive.admin)
        archive.service.advance(
            history.revision.id,
            action="revoke",
            expected_sequence=history.events[-1].sequence,
            key=str(uuid4()),
            actor=archive.admin,
            reason="Synthetic concurrent source revocation.",
        )

    assistant.callback = revoke
    result = service.answer_with_provenance(question)
    assert result.response.status == "unavailable" and result.response.references == ()
    assert result.manifest_sha256 is None


def test_semantic_delivery_reuses_one_bound_query_vector_and_checks_fresh_sources(archive):
    publish_corpus(archive)
    transport = ControlledEmbeddings()
    client = BoundedEmbeddingClient(EmbeddingSettings(_env_file=None, mode="mock"), transport)
    snapshot = archive.knowledge.snapshot()
    index = compose_index(
        snapshot, client.embed(document_inputs(snapshot), "document"), created_at=archive.now[0]
    )
    knowledge = SemanticSupportKnowledge(
        archive.knowledge,
        client,
        index,
        SemanticRetrievalSettings(mode="hybrid", allow_unreviewed_experiment=True),
    )
    try:
        answer = SupportService(SelectingAssistant(), knowledge).answer_with_provenance(
            SupportQuestion(question="password recovery expired link")
        )
        assert answer.response.status == "answered"
        assert answer.retrieval_profile == "hybrid" and answer.index_sha256 == index.index_sha256
        assert [call.purpose for call in transport.calls] == ["document", "query"]
        assert answer.safe_receipt()["index_sha256"] == index.index_sha256
    finally:
        client.close()


def test_budget_exhaustion_does_not_start_source_selection(archive):
    publish_corpus(archive)
    assistant = SelectingAssistant()
    response = SupportService(assistant, archive.knowledge, remaining_seconds=lambda: 0).answer(
        SupportQuestion(question="password recovery expired link")
    )
    assert response.status == "unavailable" and not assistant.calls


@pytest.mark.parametrize("fail_receipt", [False, True])
def test_http_durable_mode_persists_release_or_withholds_every_quote(
    archive, settings, monkeypatch, fail_receipt
):
    publish_corpus(archive)
    config = auth_settings(settings)
    signer = SigningFixture(clock=lambda: archive.now[0])
    verifier = JwtVerifier(config, KeysFixture(signer), clock=lambda: archive.now[0])
    app = create_app(
        config,
        archive.database,
        clock=lambda: archive.now[0],
        jwt_verifier=verifier,
        accounting_settings=AccountingSettings(
            _env_file=None, mode="durable", scope="delivery-test"
        ),
    )
    app.dependency_overrides[get_http_support_service] = lambda: SupportService(
        SelectingAssistant(), archive.knowledge
    )
    diagnostics = io.StringIO()
    handler = logging.StreamHandler(diagnostics)
    handler.setFormatter(JsonFormatter())
    app.state.logger.addHandler(handler)
    if fail_receipt:

        def unavailable(*args, **kwargs):
            raise RuntimeError("synthetic-private-database-detail")

        monkeypatch.setattr(
            "app.api.v1.support.KnowledgeGovernanceService.authorize_release", unavailable
        )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/support/ask",
            json={"question": "password recovery expired link"},
            headers={
                "Origin": "http://localhost:3000",
                "X-Trace-Client": "learning-web",
                "Authorization": "Bearer " + signer.token(),
            },
        )
    assert response.headers["cache-control"] == "no-store"
    with archive.database.session() as session:
        count = session.scalar(select(func.count()).select_from(k.KnowledgeReceiptRow))
    if fail_receipt:
        assert response.status_code == 503 and count == 0
        assert "quote" not in response.text and "synthetic-private" not in response.text
    else:
        assert response.status_code == 200 and response.json()["status"] == "answered"
        assert count == 1
    release = [
        event
        for line in diagnostics.getvalue().splitlines()
        if (event := json.loads(line)).get("support_stage") == "release"
    ]
    assert [event["support_reason"] for event in release] == [
        "failed" if fail_receipt else "authorized"
    ]
    assert all(event["request_id"] == response.headers["X-Request-ID"] for event in release)
    assert "synthetic-private" not in diagnostics.getvalue()
