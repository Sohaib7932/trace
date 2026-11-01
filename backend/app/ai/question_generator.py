"""Provider-independent generation port; separate from runtime tutoring."""

from typing import Protocol

from app.schemas.generation import GenerationCompletion, GenerationRequest


class QuestionGenerator(Protocol):
    def generate(self, request: GenerationRequest) -> GenerationCompletion: ...
