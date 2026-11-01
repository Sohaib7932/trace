"""Three operations share accounting without sharing their private context or authority."""

import json

from app.ai.client import BoundedAIClient
from app.ai.providers.bounded_question_generator import BoundedQuestionGenerator
from app.ai.providers.bounded_support import BoundedSupportAssistant
from app.ai.providers.bounded_tutor import BoundedTutorProvider
from app.ai.providers.mock_transport import MockAITransport
from app.core.ai_settings import AIClientSettings
from app.repositories.support_knowledge import ApprovedSupportKnowledge
from app.schemas.ai_client import TransportCompletion
from app.schemas.generation import GenerationRequest
from app.schemas.generation_admission import AdmissionAccepted
from app.schemas.support import SupportDocument, SupportPassage, SupportQuestion
from app.schemas.tutoring import HintRequest, TutorContext
from app.services.challenge_content_admission import ChallengeContentAdmission
from app.services.support import SupportService
from tests.generation_fixtures import content_data, request_data


def test_three_capabilities_use_one_mock_client_but_separate_context_and_authority(monkeypatch):
    def no_database(*args, **kwargs):
        raise AssertionError("AI operations cannot create or query learner history")

    monkeypatch.setattr("sqlite3.connect", no_database)
    monkeypatch.setattr("sqlalchemy.create_engine", no_database)
    raw = json.dumps(content_data("notes-v1"))
    transport = MockAITransport(
        [
            TransportCompletion(text=raw, cost_microusd=0),
            TransportCompletion(text='{"text":"Follow the request fields."}', cost_microusd=0),
            TransportCompletion(
                text='{"status":"answered","passage_ids":["support-fixture-login"]}',
                cost_microusd=0,
            ),
        ]
    )
    client = BoundedAIClient(AIClientSettings(_env_file=None, mode="mock"), transport)
    request = GenerationRequest.model_validate(request_data("notes-v1"))
    admitted = ChallengeContentAdmission().admit(
        request, BoundedQuestionGenerator(client).generate(request)
    )
    assert isinstance(admitted, AdmissionAccepted) and admitted.release_eligible is False
    hint = BoundedTutorProvider(client).generate_hint(
        HintRequest(
            context=TutorContext(scenario="Public lesson scenario.", learner_attempt="body"),
            level=1,
        )
    )
    assert hint.interpretation_only and hint.source == "test_fixture"
    document = SupportDocument(
        source_id="support-fixture",
        title="Fixture sign in",
        approval="test_fixture",
        passages=(
            SupportPassage(
                passage_id="support-fixture-login",
                text="Fixture: Open Sign in for email login.",
            ),
        ),
    )
    support = SupportService(
        BoundedSupportAssistant(client),
        ApprovedSupportKnowledge((document,), allow_test_fixtures=True),
    ).answer(SupportQuestion(question="How does email login work?"), subject="account-fixture")
    assert support.status == "answered" and support.source == "test_fixture"
    assert {entry.capability for entry in client.usage_snapshot()} == {
        "generation",
        "tutor",
        "support",
    }
    assert len({call.instructions for call in transport.calls}) == 3
    generation, tutor, customer_support = [json.loads(call.data_json) for call in transport.calls]
    assert "reference_passages" not in generation and "reference_passages" not in tutor
    assert "public_context" not in customer_support
    for call in transport.calls:
        assert "private" not in call.data_json
        assert "correct_value" not in call.data_json
        assert "verification_profiles" not in call.data_json
