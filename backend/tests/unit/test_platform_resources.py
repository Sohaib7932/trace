"""Production boundaries and shared embedding ownership; no cloud calls or real DB."""

from unittest.mock import patch

import anyio
import pytest
from pydantic import SecretStr, ValidationError

from app.ai.providers.mock_transport import MockAITransport
from app.ai.resources import AIResourceError, AIResources
from app.core.accounting_settings import AccountingSettings
from app.core.ai_settings import GEMINI_MODEL, AIClientSettings
from app.core.embedding_settings import EmbeddingSettings
from app.core.https_middleware import ProductionHTTPSMiddleware
from app.core.retrieval_settings import RetrievalSettings
from app.core.settings import Settings
from app.domain.clock import utc_now
from app.main import create_app
from tests.unit.test_embeddings import ControlledEmbeddings


def production_settings():
    return Settings(
        _env_file=None,
        environment="production",
        database_url=SecretStr(
            "postgresql+psycopg://synthetic@db.example.invalid/trace?sslmode=verify-full"
        ),
        database_schema="trace_app",
        cors_origins=("https://trace.example.invalid",),
        supabase_url="https://synthetic.supabase.co",
        supabase_issuer="https://synthetic.supabase.co/auth/v1",
        supabase_jwks_url="https://synthetic.supabase.co/auth/v1/.well-known/jwks.json",
    )


def live_settings():
    return AIClientSettings(
        _env_file=None,
        mode="gemini_free",
        provider_id="gemini",
        generation_model_id=GEMINI_MODEL,
        conversational_model_id=GEMINI_MODEL,
        credential_env_var="GEMINI_API_KEY",
        free_tier_project_confirmed=True,
    )


@pytest.mark.parametrize(
    "client,path,scheme,headers,allowed",
    [
        (("127.0.0.1", 41000), "/api/v1/health/ready", "http", [], True),
        (("::1", 41000), "/api/v1/health/live", "http", [], True),
        (("192.0.2.2", 41000), "/api/v1/health/live", "http", [], False),
        (("127.0.0.1", 41000), "/api/v1/support/ask", "http", [], False),
        (("192.0.2.2", 41000), "/openapi.json", "http", [(b"x-forwarded-proto", b"https")], False),
        (("192.0.2.2", 41000), "/openapi.json", "https", [], True),
        (("bad-peer", 41000), "/api/v1/health/live", "http", [], False),
    ],
)
def test_https_guard_uses_server_scheme_not_raw_proxy_headers(
    client, path, scheme, headers, allowed
):
    messages, calls = [], []

    async def downstream(scope, receive, send):
        calls.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    anyio.run(
        ProductionHTTPSMiddleware(downstream),
        {
            "type": "http",
            "path": path,
            "method": "GET",
            "scheme": scheme,
            "client": client,
            "headers": headers,
            "state": {"request_id": "synthetic-probe"},
        },
        receive,
        send,
    )
    assert bool(calls) is allowed
    assert messages[0]["status"] == (200 if allowed else 400)
    if not allowed:
        assert (b"cache-control", b"no-store") in messages[0]["headers"]
        assert b"https_required" in messages[1]["body"]


def test_production_live_mode_requires_stable_durable_controls_before_startup():
    with pytest.raises(ValueError, match="durable shared"):
        create_app(production_settings(), ai_settings=live_settings())
    with pytest.raises(ValidationError):
        AccountingSettings(_env_file=None, mode="durable")


def test_default_jwt_clock_remains_utc_independent_of_learning_replay_clock():
    from datetime import UTC, datetime

    app = create_app(Settings(_env_file=None), clock=lambda: datetime(2026, 11, 1, tzinfo=UTC))
    assert app.state.jwt_verifier.clock is utc_now
    app.state.jwt_verifier.close()


def test_unreviewed_semantic_retrieval_cannot_activate_in_production():
    retrieval = RetrievalSettings(
        _env_file=None,
        mode="hybrid",
        index_sha256="a" * 64,
        allow_unreviewed_experiment=True,
    )
    with pytest.raises(ValueError, match="independent quality approval"):
        create_app(
            production_settings(),
            retrieval_settings=retrieval,
            accounting_settings=AccountingSettings(
                _env_file=None, mode="durable", scope="prod-test"
            ),
        )


def test_disabled_embedding_never_constructs_a_transport_and_owns_one_client():
    def forbidden():
        raise AssertionError("A disabled embedding transport must not be constructed")

    resources = AIResources.create(
        AIClientSettings(_env_file=None), embedding_transport_factory=forbidden
    )
    assert resources.embeddings.settings.mode == "disabled"
    assert resources.embeddings.embed(("Public question",), "query").status == "unavailable"
    resources.stop_admission()
    assert resources.wait_for_idle(0)
    resources.close()


def test_embedding_factory_is_application_scoped_reused_and_disposed_once():
    transport, factories = ControlledEmbeddings(), []

    def factory():
        factories.append(True)
        return transport

    resources = AIResources.create(
        AIClientSettings(_env_file=None, mode="mock"),
        lambda: MockAITransport([]),
        embedding_settings=EmbeddingSettings(_env_file=None, mode="mock"),
        embedding_transport_factory=factory,
    )
    assert resources.embeddings.embed(("Public article",), "document").status == "success"
    assert resources.embeddings.embed(("Public question",), "query").status == "success"
    resources.close()
    resources.close()
    assert factories == [True] and transport.closed == 1 and len(transport.calls) == 2


def test_partial_embedding_startup_failure_closes_both_allocated_transports():
    text, embedding = MockAITransport([]), ControlledEmbeddings()
    with (
        patch(
            "app.ai.resources.BoundedEmbeddingClient", side_effect=RuntimeError("private-canary")
        ),
        pytest.raises(AIResourceError, match="^AI resources are unavailable\\.$"),
    ):
        AIResources.create(
            AIClientSettings(_env_file=None, mode="mock"),
            lambda: text,
            embedding_settings=EmbeddingSettings(_env_file=None, mode="mock"),
            embedding_transport_factory=lambda: embedding,
        )
    assert embedding.closed == 1
