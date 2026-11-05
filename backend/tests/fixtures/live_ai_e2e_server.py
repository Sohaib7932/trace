"""Loopback-only real-HTTP browser fixture. No real key, live provider or developer DB."""

import argparse
import json
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated

import uvicorn
from fastapi import Depends, HTTPException
from pydantic import SecretStr

from alembic import command
from app.ai.client import AITransportError
from app.ai.providers.bounded_support import BoundedSupportAssistant
from app.api.dependencies import current_account, get_http_support_service
from app.core.ai_settings import AIClientSettings
from app.core.settings import Settings
from app.core.tutor_settings import TutorSettings
from app.db.github_projects import SqlGitHubProjectRepository
from app.db.learning import SqlLearningRepository
from app.db.migrations import migration_config
from app.db.project_knowledge import SqlProjectKnowledgeRepository
from app.db.session import Database
from app.domain.accounts import AuthenticatedAccount
from app.main import create_app
from app.repositories.support_knowledge import ApprovedSupportKnowledge
from app.schemas.ai_client import TransportCompletion
from app.schemas.github_projects import InstallationComplete, RepositoryView
from app.schemas.support import SupportDocument
from app.services.catalog import seed_first_lesson, seed_transfer_lesson
from app.services.github_projects import GitHubProjectService
from app.services.project_knowledge import ProjectKnowledgeService
from app.services.support import SupportService
from app.support.knowledge import load_corpus_package
from scripts import auth_fixture
from tests.integration.test_github_projects import FakeGitHub
from tests.integration.test_github_projects import config as github_settings
from tests.unit.test_project_ingestion import SHA, FixtureRepository, sha

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
        elif json.loads(request.data_json).get("operation") == "engineering_conversation":
            text = json.dumps(
                {
                    "status": "answered",
                    "text": "A request schema describes accepted data. Compare the declared field "
                    "types with the submitted JSON before editing. What mismatch do you observe?",
                }
            )
        elif json.loads(request.data_json).get("operation") == "private_learning_guide_v1":
            from tests.integration.test_private_guides import content

            text = json.dumps(content())
        elif json.loads(request.data_json).get("operation") == "project-learning-v1":
            data = json.loads(request.data_json)
            text = json.dumps(
                {
                    "schema_version": "project-learning-v1",
                    "title": "Read the identity helper",
                    "steps": [
                        {
                            "title": "Inspect the return value",
                            "explanation": "The supplied helper returns its subject.",
                            "question": "Which argument is returned?",
                            "reference_ids": [data["snapshot"]["references"][0]["reference_id"]],
                        }
                    ],
                }
            )
        elif json.loads(request.data_json).get("operation") == "project-question-v1":
            data = json.loads(request.data_json)
            reference = next(
                item for item in data["untrusted_sources"] if item["path"] == "backend/identity.py"
            )
            text = json.dumps(
                {
                    "schema_version": "project-answer-v1",
                    "status": "answered",
                    "sections": [
                        {
                            "explanation": "The supplied backend helper returns its subject. "
                            "The excerpt does not prove other authentication behavior.",
                            "citations": [
                                {
                                    "reference_id": reference["reference_id"],
                                    "quote": "return subject",
                                }
                            ],
                        }
                    ],
                }
            )
        else:
            text = '{"guidance_id":"extra-fields"}'
        return TransportCompletion(text=text, input_tokens=100, output_tokens=30, cost_microusd=0)

    def close(self):
        pass


class BrowserFixtureGitHub(FakeGitHub):
    """Every external App/repository operation is synthetic; HTTP auth stays real."""

    def __init__(self, settings):
        super().__init__(settings)
        self.fixture_repository = FixtureRepository()

    def accessible_repositories(self, token, installation_id):
        super().accessible_repositories(token, installation_id)
        return [RepositoryView(repository_id=22, full_name="fixture/architecture", private=True)]

    def commit(self, token, full_name, identifier):
        # The preparation UI now syncs before ingestion. Both operations must see
        # the same synthetic files and blob identifiers.
        return {
            "sha": identifier,
            "commit": {"message": "Add the identity helper"},
            "files": [
                {"filename": "backend/identity.py", "status": "modified", "sha": sha("identity.py")}
            ],
        }

    def repository(self, token, name):
        return self.fixture_repository.repository(token, name)

    def tree(self, token, name, sha):
        return self.fixture_repository.tree(token, name, sha)

    def commit_page(self, token, name, sha, page):
        return self.fixture_repository.commit_page(token, name, sha, page)

    def history_page(self, token, name, sha, page):
        return self.fixture_repository.history_page(token, name, sha, page)

    def content(self, token, name, path, sha, *, blob_sha):
        return self.fixture_repository.content(token, name, path, sha, blob_sha=blob_sha)


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
                ai_settings=AIClientSettings(
                    _env_file=None,
                    mode="mock",
                    generation_model_id="fixture-project-model",
                    conversational_model_id="fixture-conversation-model",
                ),
                ai_transport_factory=lambda: transport,
                # All browser journeys share one loopback client and one minute window. The default
                # 120-per-minute project/tutor ingress allowance is for real users, not this suite.
                tutor_settings=TutorSettings(_env_file=None, ingress_requests_per_minute=600),
            )
            original_lifespan = app.router.lifespan_context

            @asynccontextmanager
            async def fixture_lifespan(application):
                async with original_lifespan(application):
                    config = github_settings(callback_url=FRONT + "/projects/github/callback")
                    github = BrowserFixtureGitHub(config)
                    projects = GitHubProjectService(
                        SqlGitHubProjectRepository(database),
                        config,
                        github,
                        application.state.ai_resources.client,
                    )
                    application.state.github_projects = projects
                    application.state.project_knowledge = ProjectKnowledgeService(
                        projects,
                        SqlProjectKnowledgeRepository(database),
                        application.state.ai_resources.client,
                    )
                    try:
                        yield
                    finally:
                        github.close()

            app.router.lifespan_context = fixture_lifespan

            @app.post("/__fixture__/github/connect")
            def prepare_github(
                auth: Annotated[AuthenticatedAccount, Depends(current_account)],
            ):
                # Test-only shortcut for the EXTERNAL OAuth screen, not for Trace
                # identity, ownership, state consumption or repository authorization.
                auth.account.require_role("learner")
                projects = app.state.github_projects
                start = projects.start(auth.account.id)
                projects.complete(
                    auth.account.id,
                    InstallationComplete(
                        installation_id=11, state=start.state, code="synthetic-browser-code"
                    ),
                )
                connected = projects.connect(auth.account.id, 11, 22)
                return {
                    "connection_id": connected.id,
                    "commit_sha": SHA,
                    "source": "test_fixture",
                    "live_github_authorization": False,
                }

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
