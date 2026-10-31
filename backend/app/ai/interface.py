from typing import Protocol

from app.schemas.tutoring import (
    EvaluatedAttempt,
    HintRequest,
    MisconceptionAnalysis,
    TutorContext,
    TutorMessage,
)


class TutorProvider(Protocol):
    def generate_hint(self, request: HintRequest) -> TutorMessage: ...

    def explain_attempt(self, attempt: EvaluatedAttempt) -> TutorMessage: ...

    def analyse_misconception(self, context: TutorContext) -> MisconceptionAnalysis: ...
