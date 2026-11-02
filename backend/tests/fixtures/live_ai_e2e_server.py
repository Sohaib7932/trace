"""Loopback-only real-HTTP browser fixture. No real key, live provider or developer DB."""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from fastapi import HTTPException
from pydantic import SecretStr

from alembic import command
from app.ai.client import AITransportError
from app.ai.providers.bounded_support import BoundedSupportAssistant
from app.api.dependencies import get_http_support_service
from app.core.ai_settings import AIClientSettings
from app.core.settings import Settings
from app.db.learning import SqlLearningRepository
from app.db.migrations import migration_config
from app.db.session import Database
from app.main import create_app
from app.repositories.support_knowledge import ApprovedSupportKnowledge
from app.schemas.ai_client import TransportCompletion
from app.schemas.support import SupportDocument
from app.services.catalog import seed_first_lesson, seed_transfer_lesson
from app.services.support import SupportService
from app.support.knowledge import load_corpus_package
from scripts import auth_fixture

API = "http://127.0.0.1:8100"
AUTH = "http://127.0.0.1:8101"
FRONT = "http://127.0.0.1:3200"


class BrowserFixtureTransport:
    source = "test_fixture"

    def __init__(self):
        self.mode = "normal"
        self.calls = []

    def complete(self, request):
        self.calls.append(request.capability)
        if self.mode == "timeout":
            raise AITransportError("timeout")
        if self.mode == "invalid":
            text = '{"unapproved":"not a valid reply"}'
        elif request.capability == "support":
            data = json.loads(request.data_json)
            text = json.dumps(
                {"status": "answered", "passage_ids": [data["reference_passages"][0]["passage_id"]]}
            )
        else:
            text = '{"guidance_id":"extra-fields"}'
        return TransportCompletion(text=text, input_tokens=100, output_tokens=30, cost_microusd=0)

    def close(self):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=("auth", "backend"))
    option = parser.parse_args()
    if option.service == "auth":
        auth_fixture.URL, auth_fixture.ORIGIN = AUTH, FRONT
        uvicorn.run(
            auth_fixture.create_fixture(),
            host="127.0.0.1",
            port=8101,
            access_log=False,
            log_level="warning",
        )
        return
    with TemporaryDirectory(prefix="trace-ai-browser-") as directory:
        settings = Settings(
            _env_file=None,
            environment="test",
            log_level="WARNING",
            database_url=SecretStr(
                "sqlite+pysqlite:///" + (Path(directory) / "learning.db").as_posix()
            ),
            cookie_secure=False,
            allow_insecure_local_cookies=True,
            cors_origins=(FRONT,),
            supabase_url=AUTH,
            supabase_issuer=AUTH + "/auth/v1",
            supabase_jwks_url=AUTH + "/auth/v1/.well-known/jwks.json",
            auth_allow_insecure_loopback=True,
        )
        database = Database(settings)
        try:
            migration = migration_config()
            with database.engine.begin() as connection:
                migration.attributes["connection"] = connection
                command.upgrade(migration, "head")
            repository = SqlLearningRepository(database)
            seed_first_lesson(repository)
            seed_transfer_lesson(repository)
            transport = BrowserFixtureTransport()
            app = create_app(
                settings,
                database,
                ai_settings=AIClientSettings(_env_file=None, mode="mock"),
                ai_transport_factory=lambda: transport,
            )
            # Explicit fixture provenance, including the public-document inputs.
            documents = tuple(
                SupportDocument(
                    source_id=doc.source_id,
                    title=doc.title,
                    approval="test_fixture",
                    passages=doc.passages,
                )
                for doc in load_corpus_package().documents
            )
            knowledge = ApprovedSupportKnowledge(documents, allow_test_fixtures=True)

            def support_service():
                return SupportService(
                    BoundedSupportAssistant(app.state.ai_resources.client), knowledge
                )

            app.dependency_overrides[get_http_support_service] = support_service

            @app.post("/__fixture__/ai-outcome/{mode}")
            def set_outcome(mode: str):
                if mode not in {"normal", "timeout", "invalid"}:
                    raise HTTPException(422)
                transport.mode = mode
                return {"mode": mode}

            @app.get("/__fixture__/ai-stats")
            def stats():
                return {"capabilities": transport.calls}

            uvicorn.run(app, host="127.0.0.1", port=8100, access_log=False, log_level="warning")
        finally:
            database.dispose()


if __name__ == "__main__":
    main()
