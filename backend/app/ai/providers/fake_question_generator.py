"""Deterministic in-memory contract fixtures. This provider is never live AI."""

import json
from dataclasses import dataclass
from typing import Literal, get_args

from app.ai.providers.question_fixtures import COPY_FIXTURES
from app.domain.generation_copy import TEMPLATE_COPY_SLOTS
from app.schemas.generation import (
    GenerationCompletion,
    GenerationRequest,
    ModelMetadata,
    ProviderMetadata,
    TransportMetadata,
)

type FakeGenerationFixture = Literal[
    "valid",
    "refusal",
    "malformed_json",
    "truncated",
    "unknown_fields",
    "unsupported_references",
    "invalid_content",
]


@dataclass(frozen=True)
class FakeQuestionGenerator:
    fixture: FakeGenerationFixture = "valid"

    def __post_init__(self) -> None:
        if self.fixture not in get_args(FakeGenerationFixture.__value__):
            raise ValueError("Unknown fake generation fixture")

    def generate(self, request: GenerationRequest) -> GenerationCompletion:
        # The fake supports only the reviewed copy destinations. Unsupported
        # briefs fail deterministically; no arbitrary slot gains a capability.
        slots = TEMPLATE_COPY_SLOTS[request.template_family]
        compatible = (
            set(request.requested_objective_slots) == slots.objectives
            and set(request.requested_misconception_slots) <= slots.misconceptions
        )
        transport = TransportMetadata(
            source="transport",
            provider=ProviderMetadata(
                provider_id="fake-question-generator-test-fixture", request_id=None
            ),
            model=ModelMetadata(
                requested_model_id=None, returned_model_id="static-copy-test-fixture-v1"
            ),
        )
        if self.fixture == "refusal" or not compatible:
            return GenerationCompletion(status="refusal", raw_json=None, transport=transport)

        body = COPY_FIXTURES[request.template_family].model_dump(mode="json")
        # Bind only reference destinations, not educational meaning or trusted
        # lesson configuration. All educational wording remains the fixed copy.
        body["context_variant"] = request.permitted_narrative_variants[0]
        body["prediction"]["choice_wording"] = {
            outcome: getattr(request.approved_prediction_wording, outcome)[0].key
            for outcome in ("rejected", "saved", "server_error")
        }
        body["misconceptions"] = [
            item
            for item in body["misconceptions"]
            if item["slot_key"] in request.requested_misconception_slots
        ]
        if self.fixture == "unknown_fields":
            body["unsupported_field"] = "Untrusted fixture extension."
        elif self.fixture == "unsupported_references":
            body["objectives"][0]["slot_key"] = "unsupported-fixture-objective"
        elif self.fixture == "invalid_content":
            body["scenario_narrative"] = "```python\nprint('fixture')\n```"
        # A stable fixture encoding, not definition canonicalization or a digest.
        raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        if self.fixture == "malformed_json":
            raw = '{"title":'
        if self.fixture == "truncated":
            return GenerationCompletion(status="truncated", raw_json=raw[:80], transport=transport)
        return GenerationCompletion(status="success", raw_json=raw, transport=transport)
