import pytest
from pydantic import ValidationError

from app.ai.interface import TutorProvider
from app.ai.providers.fake import FakeTutorProvider
from app.schemas.tutoring import (
    EvaluatedAttempt,
    HintRequest,
    TutorContext,
    TutorMessage,
)


@pytest.fixture
def context() -> TutorContext:
    return TutorContext(
        scenario="A request uses body but the schema requires content.",
        learner_attempt='{"body":"Buy milk"}',
    )


def test_fake_obeys_all_three_operations_without_network(context: TutorContext) -> None:
    provider: TutorProvider = FakeTutorProvider()
    hints = [provider.generate_hint(HintRequest(context=context, level=n)) for n in (1, 2, 3)]
    assert len({h.text for h in hints}) == 3
    assert hints[0] == provider.generate_hint(HintRequest(context=context, level=1))
    attempt = EvaluatedAttempt(context=context, outcome="incorrect", evidence=("HTTP 422",))
    explanation = provider.explain_attempt(attempt)
    assert attempt.outcome == "incorrect" and "incorrect" in explanation.text
    analysis = provider.analyse_misconception(context)
    assert analysis.possible_misconception is None
    assert all(h.source == "test_fixture" and h.interpretation_only for h in hints)
    assert explanation.source == analysis.source == "test_fixture"


def test_infrastructure_failure_is_not_a_learner_error(context: TutorContext) -> None:
    attempt = EvaluatedAttempt(
        context=context, outcome="infrastructure_error", evidence=("Dependency unavailable",)
    )
    assert (
        "does not establish a learner mistake" in FakeTutorProvider().explain_attempt(attempt).text
    )


def test_unbounded_input_invalid_levels_and_unobserved_evaluation_rejected(
    context: TutorContext,
) -> None:
    with pytest.raises(ValidationError):
        HintRequest(context=context, level=4)
    with pytest.raises(ValidationError):
        TutorContext(scenario="x" * 4001, learner_attempt="x")
    with pytest.raises(ValidationError):
        EvaluatedAttempt(context=context, outcome="correct", evidence=())
    with pytest.raises(ValidationError):
        TutorMessage(text="x" * 2401, source="ai")
    with pytest.raises(ValidationError):
        TutorMessage(text="Grade override", source="ai", interpretation_only=False)
