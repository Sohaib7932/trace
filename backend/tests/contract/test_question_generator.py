"""Interface checks without a fake implementation, provider adapter or I/O."""

import inspect
from typing import Protocol, get_type_hints

from app.ai.interface import TutorProvider
from app.ai.question_generator import QuestionGenerator
from app.schemas.generation import GenerationCompletion, GenerationRequest


def test_question_generator_is_a_distinct_synchronous_protocol():
    assert QuestionGenerator is not TutorProvider
    assert QuestionGenerator.__bases__ == (Protocol,)
    assert list(inspect.signature(QuestionGenerator.generate).parameters) == ["self", "request"]
    assert not inspect.iscoroutinefunction(QuestionGenerator.generate)
    assert get_type_hints(QuestionGenerator.generate) == {
        "request": GenerationRequest,
        "return": GenerationCompletion,
    }


def test_generation_does_not_extend_or_replace_tutor_capabilities():
    assert not hasattr(TutorProvider, "generate")
    for name in ["generate_hint", "explain_attempt", "analyse_misconception"]:
        assert hasattr(TutorProvider, name)
        assert not hasattr(QuestionGenerator, name)
