"""Real SDK + trusted production-candidate pipeline using synthetic HTTP responses only."""

import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.ai.client import BoundedAIClient
from app.ai.providers.bounded_question_generator import BoundedQuestionGenerator
from app.ai.providers.fake_question_generator import FakeQuestionGenerator
from app.ai.providers.gemini import MODEL, GeminiTransport
from app.blueprints.candidates import notes_blueprint_candidate, tasks_blueprint_candidate
from app.core.ai_settings import AIClientSettings
from app.db import models as m
from app.db.candidates import SqlCandidateRepository
from app.domain.learning import LearningError
from app.schemas.lesson_composition import CompositionIdentity
from app.services.candidate_generation import CandidateGenerationService, request_from_blueprint
from app.services.candidate_lifecycle import CandidateLifecycleService
from app.services.candidate_validation import CandidateValidationService
from app.verification.candidate_runtime import IsolatedCandidateRuntime


def setup_pipeline(database, family="notes-v1", bad_output=None):
    blueprint = (
        notes_blueprint_candidate() if family == "notes-v1" else tasks_blueprint_candidate()
    ).trusted_blueprint()
    brief = request_from_blueprint(blueprint)
    # Deterministic copy is only the vendor-response fixture. No fixture definition
    # enters the trusted blueprint or the application production package.
    raw = FakeQuestionGenerator().generate(brief).raw_json
    if bad_output is not None:
        raw = bad_output
    calls = []

    def handle(wire):
        calls.append(wire)
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": raw}]}, "finishReason": "STOP"}],
                "modelVersion": MODEL,
                "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 1000},
            },
        )

    transport = GeminiTransport(
        SecretStr("controlled-provider-wire-fixture"), http_transport=httpx.MockTransport(handle)
    )
    config = AIClientSettings(
        _env_file=None,
        mode="gemini_free",
        provider_id="gemini",
        generation_model_id=MODEL,
        conversational_model_id=MODEL,
        credential_env_var="GEMINI_API_KEY",
        free_tier_project_confirmed=True,
    )
    client = BoundedAIClient(config, transport)
    lifecycle = CandidateLifecycleService(
        SqlCandidateRepository(database), CandidateValidationService(IsolatedCandidateRuntime())
    )
    pipeline = CandidateGenerationService(BoundedQuestionGenerator(client), lifecycle)
    args = dict(
        generation_request_id=str(uuid4()),
        creation_key=str(uuid4()),
        validation_key=str(uuid4()),
        request=brief,
        blueprint=blueprint,
        identity=CompositionIdentity(
            lesson_id=blueprint.definition.lesson_id, version="2.0.0", version_id=str(uuid4())
        ),
        transfer_target=tasks_blueprint_candidate().trusted_blueprint()
        if family == "notes-v1"
        else None,
    )
    return pipeline, client, calls, args


@pytest.mark.parametrize("family", ["notes-v1", "tasks-nested-v1"])
def test_generation_runs_admission_persistence_and_all_runtime_checks_without_approval(
    database, family
):
    pipeline, client, calls, args = setup_pipeline(database, family)
    try:
        history = pipeline.generate_and_validate(**args)
        assert history.state == "validated" and history.review_status == "pending"
        assert history.release_eligible is False
        assert history.snapshot.generation_origin == "provider"
        assert history.snapshot.transport.provider.provider_id == "gemini"
        assert history.snapshot.source_blueprint == args["blueprint"].reference()
        receipt = history.events[-1].validation
        assert receipt.status == "validated"
        assert receipt.runtime_verification_completed
        assert len(receipt.runtime_evidence) == 2
        assert all(
            len(profile.checks) == 5 and all(check.passed for check in profile.checks)
            for profile in receipt.runtime_evidence
        )
        candidate, *_ = history.snapshot.context()
        assert candidate.definition.private == args["blueprint"].definition.private
        assert len(calls) == 1
        sent = json.loads(calls[0].content)
        model_input = json.loads(sent["contents"][0]["parts"][0]["text"])
        assert set(model_input) == {"generation_request"}
        assert "private" not in model_input["generation_request"]
        assert pipeline.generate_and_validate(**args) == history
        assert len(calls) == 1
        with database.session() as db:
            assert len(db.scalars(select(m.GeneratedCandidate)).all()) == 1
            assert len(db.scalars(select(m.CandidateLifecycleEvent)).all()) == 2
            for model in (
                m.Learner,
                m.LearningSession,
                m.Attempt,
                m.VerificationRun,
                m.RetrievalCheckpoint,
            ):
                assert not db.scalars(select(model)).all()
    finally:
        client.close()


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '{"private":{"evaluator":"private-canary"}}',
        '{"contract_version":"1.0.0","title":"x"}',
    ],
)
def test_invalid_generated_content_is_not_persisted_or_replaced_by_fake_copy(database, raw):
    pipeline, client, calls, args = setup_pipeline(database, bad_output=raw)
    try:
        with pytest.raises(LearningError) as exc:
            pipeline.generate_and_validate(**args)
        assert exc.value.code == "generation_rejected"
        assert "private-canary" not in str(exc.value)
        assert len(calls) == 1
        with database.session() as db:
            assert not db.scalars(select(m.GeneratedCandidate)).all()
    finally:
        client.close()


def test_changed_input_cannot_reuse_a_generation_creation_key(database):
    pipeline, client, calls, args = setup_pipeline(database)
    try:
        pipeline.generate_and_validate(**args)
        changed = {**args, "generation_request_id": str(uuid4())}
        with pytest.raises(LearningError) as exc:
            pipeline.generate_and_validate(**changed)
        assert exc.value.code == "conflict" and len(calls) == 1
    finally:
        client.close()


def test_concurrent_local_retries_share_one_generation_and_candidate(database):
    pipeline, client, calls, args = setup_pipeline(database)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(pipeline.generate_and_validate, **args)
            second = pool.submit(pipeline.generate_and_validate, **args)
            assert first.result(timeout=30) == second.result(timeout=30)
        assert len(calls) == 1
    finally:
        client.close()
