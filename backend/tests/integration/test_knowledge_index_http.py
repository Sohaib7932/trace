"""Admin index job boundaries using explicitly synthetic vectors, never live quality evidence."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.ai.embeddings import BoundedEmbeddingClient
from app.core.embedding_settings import EmbeddingSettings
from app.db import knowledge_models as k
from app.support.embedding_index import document_inputs
from tests.integration.test_knowledge_admin_http import admin_api as admin_api  # noqa: F401
from tests.integration.test_knowledge_archive import archive as archive  # noqa: F401
from tests.integration.test_knowledge_archive import publish_corpus
from tests.unit.test_embeddings import ControlledEmbeddings


class SyntheticLiveWire(ControlledEmbeddings):
    # Simulates the genuine adapter's provenance for admission tests only.
    # These artificial vectors are confined to a disposable database.
    source = "ai"


def configure(admin_api, callback=None):
    transport = SyntheticLiveWire(callback=callback)
    client = BoundedEmbeddingClient(
        EmbeddingSettings(
            _env_file=None, mode="gemini_free", free_tier_unbilled_project_confirmed=True
        ),
        transport,
    )
    admin_api.client.app.state.ai_resources.embeddings.close()
    admin_api.client.app.state.ai_resources.embeddings = client
    admin_api.client.headers["Authorization"] = "Bearer " + admin_api.signer.token()
    return transport


def post(context, key=None, **extra):
    return context.client.post(
        "/api/v1/admin/knowledge/indexes/build",
        json={"operation_key": key or str(uuid4()), **extra},
    )


def test_indexing_requires_authentication_admin_role_and_no_client_source_selection(admin_api):
    assert post(admin_api).status_code == 401
    admin_api.client.headers["Authorization"] = "Bearer " + admin_api.ordinary.token()
    assert post(admin_api).status_code == 403
    transport = configure(admin_api)
    response = post(admin_api, source_path="synthetic-private-path-canary")
    assert response.status_code == 422 and "synthetic-private" not in response.text
    assert response.headers["cache-control"] == "no-store" and not transport.calls


def test_disabled_embedding_and_unpublished_corpus_do_not_call_a_provider(admin_api):
    admin_api.client.headers["Authorization"] = "Bearer " + admin_api.signer.token()
    assert post(admin_api).status_code == 503
    transport = configure(admin_api)
    assert post(admin_api).status_code == 503
    assert not transport.calls


def test_server_selected_index_is_durable_replayable_but_does_not_activate_retrieval(admin_api):
    publish_corpus(admin_api.archive)
    transport = configure(admin_api)
    key = str(uuid4())
    response = post(admin_api, key)
    assert response.status_code == 200
    result = response.json()
    assert result["passage_count"] == 19 and result["retrieval_activated"] is False
    assert set(result) == {
        "index_sha256",
        "manifest_sha256",
        "space_sha256",
        "passage_count",
        "source",
        "retrieval_activated",
    }
    assert transport.calls[0].texts == document_inputs(admin_api.archive.knowledge.snapshot())
    assert post(admin_api, key).json() == result and len(transport.calls) == 1
    assert admin_api.client.app.state.retrieval_settings.mode == "lexical"
    with admin_api.archive.database.session() as session:
        assert session.scalar(select(func.count()).select_from(k.KnowledgeIndexRow)) == 1


def test_revocation_during_embedding_prevents_archive_and_cannot_release_vectors(admin_api):
    histories, _ = publish_corpus(admin_api.archive)

    def revoked(request):
        history = admin_api.archive.service.get(
            histories[0].revision.id, actor=admin_api.archive.admin
        )
        admin_api.archive.service.advance(
            history.revision.id,
            action="revoke",
            expected_sequence=history.events[-1].sequence,
            key=str(uuid4()),
            actor=admin_api.archive.admin,
            reason="Synthetic source revocation during slow embedding.",
        )
        from app.schemas.embeddings import EmbeddingTransportResult
        from tests.unit.test_embeddings import basis

        return EmbeddingTransportResult(
            vectors=tuple(basis(i) for i, _ in enumerate(request.texts))
        )

    configure(admin_api, revoked)
    response = post(admin_api)
    assert response.status_code == 409 and "values" not in response.text
    with admin_api.archive.database.session() as session:
        assert session.scalar(select(func.count()).select_from(k.KnowledgeIndexRow)) == 0


@pytest.mark.parametrize("extra", [{"model_id": "unapproved"}, {"publish": True}])
def test_index_request_cannot_choose_provider_or_promote_itself(admin_api, extra):
    transport = configure(admin_api)
    assert post(admin_api, **extra).status_code == 422 and not transport.calls
