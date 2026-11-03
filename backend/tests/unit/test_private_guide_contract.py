"""Strict guide input/output and provider boundary security."""

import json

import pytest
from pydantic import ValidationError

from app.ai.client import BoundedAIClient
from app.ai.providers.private_guides import BoundedGuideGenerator
from app.core.ai_settings import AIClientSettings
from app.schemas.ai_client import TransportCompletion
from app.schemas.private_guides import GuideContent, GuideCreate
from tests.integration.test_private_guides import content


def request():
    return GuideCreate(
        topic="Python variables",
        start_level="beginner",
        target_level="intermediate",
        practical=True,
    )


@pytest.mark.parametrize(
    "change",
    [
        {"topic": "x" * 501},
        {"topic": ""},
        {"topic": "learner@example.test"},
        {"topic": "GEMINI_API_KEY=private-canary-value"},
        {"start_level": "expert"},
        {"practical": "true"},
        {"owner_id": "forged"},
        {"goals": "x" * 601},
    ],
)
def test_invalid_untrusted_guide_input_is_rejected(change):
    with pytest.raises(ValidationError):
        GuideCreate.model_validate({**request().model_dump(), **change})


@pytest.mark.parametrize(
    "mutation", ["schema", "duplicate", "missing", "oversized", "secret", "completion", "url"]
)
def test_generated_structure_cannot_claim_execution_or_expose_private_details(mutation):
    payload = content()
    if mutation == "schema":
        payload["schema_version"] = "other"
    elif mutation == "duplicate":
        payload["sections"][1]["id"] = payload["sections"][0]["id"]
    elif mutation == "missing":
        del payload["learning_objectives"]
    elif mutation == "oversized":
        payload["summary"] = "x" * 3001
    elif mutation == "secret":
        payload["summary"] = "GEMINI_API_KEY=private-canary-value"
    elif mutation == "completion":
        payload["summary"] = "I executed your code and verified the lesson."
    else:
        payload["summary"] = "Open https://untrusted.example for your result."
    with pytest.raises(ValidationError):
        GuideContent.model_validate(payload)


class Transport:
    source = "test_fixture"

    def __init__(self, payload):
        self.payload, self.calls = payload, []

    def complete(self, request):
        self.calls.append(request)
        return TransportCompletion(text=self.payload)


def test_generator_reuses_shared_client_and_labels_untrusted_prompt_data():
    transport = Transport(json.dumps(content()))
    client = BoundedAIClient(AIClientSettings(_env_file=None, mode="mock"), transport)
    result = BoundedGuideGenerator(client).generate(
        request(), subject="synthetic", timeout_seconds=1
    )
    assert result is not None and result[1] == "test_fixture"
    sent = transport.calls[0]
    assert sent.capability == "generation"
    assert json.loads(sent.data_json)["untrusted_request"] == request().model_dump(mode="json")
    assert "not an executable Trace lesson" in sent.instructions
    assert sent.response_timeout_seconds <= 1


@pytest.mark.parametrize(
    "payload", ["not json", '{"owner_id":"forged"}', '{"title":"x"}', "x" * 20000]
)
def test_invalid_provider_output_returns_unavailable_without_a_fixture_success(payload):
    transport = Transport(payload)
    client = BoundedAIClient(AIClientSettings(_env_file=None, mode="mock"), transport)
    assert (
        BoundedGuideGenerator(client).generate(request(), subject="synthetic", timeout_seconds=1)
        is None
    )
