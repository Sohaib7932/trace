from app.schemas.tutoring import (
    EvaluatedAttempt,
    HintRequest,
    MisconceptionAnalysis,
    TutorContext,
    TutorMessage,
)


class FakeTutorProvider:
    """Deterministic contract fixture, not a live model or lesson correctness engine."""

    def generate_hint(self, request: HintRequest) -> TutorMessage:
        hints = (
            "Follow the request data from the sender to the receiver.",
            "Compare the outgoing field names with the receiving schema.",
            "Check which required field is missing before considering database code.",
        )
        return TutorMessage(text=hints[request.level - 1], source="test_fixture")

    def explain_attempt(self, attempt: EvaluatedAttempt) -> TutorMessage:
        if attempt.outcome == "infrastructure_error":
            text = "The dependency failed. This does not establish a learner mistake."
        else:
            text = (
                f"The supplied deterministic evaluation is {attempt.outcome}. Inspect its evidence."
            )
        return TutorMessage(text=text, source="test_fixture")

    def analyse_misconception(self, context: TutorContext) -> MisconceptionAnalysis:
        # A fixture cannot diagnose a person's understanding from arbitrary text.
        return MisconceptionAnalysis(possible_misconception=None, source="test_fixture")
