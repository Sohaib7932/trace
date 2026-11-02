"""Opt-in bounded Gemini checks using public/synthetic inputs; never print credentials/text."""

import argparse
import json
import tempfile
from pathlib import Path
from uuid import uuid4

from pydantic import SecretStr

from alembic import command
from app.ai.providers.gemini import _KEY_FILE, MODEL, GeminiCredentials
from app.ai.providers.guided_lesson_assistant import GuidedLessonAssistant
from app.ai.resources import AIResources
from app.blueprints.candidates import tasks_blueprint_candidate
from app.core.ai_settings import AIClientSettings
from app.core.settings import Settings
from app.db.candidates import SqlCandidateRepository
from app.db.migrations import migration_config
from app.db.session import Database
from app.domain.learning import LearningError
from app.schemas.lesson_composition import CompositionIdentity
from app.schemas.support import SupportQuestion
from app.services.candidate_generation import CandidateGenerationService, request_from_blueprint
from app.services.candidate_lifecycle import CandidateLifecycleService
from app.services.candidate_validation import CandidateValidationService
from app.services.catalog import PUBLIC_CONTENT
from app.services.lesson_assistant import LessonAssistantService, build_lesson_assistant_request
from app.services.lesson_tutoring import GUIDANCE
from app.verification.candidate_runtime import IsolatedCandidateRuntime


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--confirm-free-project", action="store_true")
    parser.add_argument("--generation", action="store_true")
    args = parser.parse_args()
    try:
        key = GeminiCredentials(_env_file=_KEY_FILE)
        present = bool(key.key.get_secret_value().strip())
    except Exception:
        present = False
    report: dict[str, object] = {
        "model": MODEL,
        "credential_present": present,
        "live_calls_started": False,
        "billing_verified": False,
    }
    if not present or not args.live or not args.confirm_free_project:
        report["status"] = "missing_credentials" if not present else "live_check_not_authorized"
        print(json.dumps(report))
        return 2
    config = AIClientSettings(
        _env_file=None,
        mode="gemini_free",
        provider_id="gemini",
        generation_model_id=MODEL,
        conversational_model_id=MODEL,
        credential_env_var="GEMINI_API_KEY",
        free_tier_project_confirmed=True,
        max_live_requests_per_process=3,
    )
    resources: AIResources | None = None
    passed = False
    try:
        resources = AIResources.create(config)
        report["live_calls_started"] = True
        request = build_lesson_assistant_request(
            lesson_id="fastapi-payload-mismatch",
            stage="predict",
            public_content=PUBLIC_CONTENT,
            question="What does extra forbid mean in the receiving Pydantic model?",
        )
        tutor = LessonAssistantService(
            GuidedLessonAssistant(resources.client, GUIDANCE, "synthetic-check")
        )
        reply = tutor.answer(request)
        tutor_ok = (
            reply.status == "answered" and reply.source == "ai" and reply.text in GUIDANCE.values()
        )
        report["tutor"] = {"status": reply.status, "source": reply.source, "grounded": tutor_ok}
        answer = resources.support.answer(
            SupportQuestion(
                question="When are review checkpoints due after Tasks transfer completion?"
            ),
            subject="synthetic-check",
        )
        support_ok = (
            answer.status == "answered" and answer.source == "ai" and bool(answer.references)
        )
        report["support"] = {
            "status": answer.status,
            "source": answer.source,
            "sources": [item.source_id for item in answer.references],
            "passages": [item.passage_id for item in answer.references],
        }
        passed = tutor_ok and support_ok
        if args.generation:
            directory = Path(tempfile.mkdtemp(prefix="trace-gemini-synthetic-"))
            database = Database(
                Settings(
                    _env_file=None,
                    database_url=SecretStr(
                        "sqlite+pysqlite:///" + (directory / "candidate.db").as_posix()
                    ),
                )
            )
            try:
                migration = migration_config()
                with database.engine.begin() as connection:
                    migration.attributes["connection"] = connection
                    command.upgrade(migration, "head")
                blueprint = tasks_blueprint_candidate().trusted_blueprint()
                pipeline = CandidateGenerationService(
                    resources.question_generator,
                    CandidateLifecycleService(
                        SqlCandidateRepository(database),
                        CandidateValidationService(IsolatedCandidateRuntime()),
                    ),
                )
                try:
                    history = pipeline.generate_and_validate(
                        generation_request_id=str(uuid4()),
                        creation_key=str(uuid4()),
                        validation_key=str(uuid4()),
                        request=request_from_blueprint(blueprint),
                        blueprint=blueprint,
                        identity=CompositionIdentity(
                            lesson_id=blueprint.definition.lesson_id,
                            version="2.0.0",
                            version_id=str(uuid4()),
                        ),
                    )
                    report["generation"] = {
                        "state": history.state,
                        "review_status": history.review_status,
                        "release_eligible": history.release_eligible,
                        "disposable_database": True,
                    }
                    passed = (
                        passed and history.state == "validated" and not history.release_eligible
                    )
                except LearningError as exc:
                    report["generation"] = {"status": "rejected_or_unavailable", "code": exc.code}
                    passed = False
            finally:
                database.dispose()
        report["usage"] = [
            item.model_dump(mode="json") for item in resources.client.usage_snapshot()
        ]
        report["status"] = "passed" if passed else "partial_or_failed"
    except Exception:
        report["status"] = "check_failed"
    finally:
        if resources is not None:
            try:
                resources.close()
            except Exception:
                report["status"] = "cleanup_failed"
                passed = False
    print(json.dumps(report))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
