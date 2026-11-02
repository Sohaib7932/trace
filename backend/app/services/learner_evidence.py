"""Pure factual aggregation. No database, identity, provider or profile capability."""

from app.schemas.generation import LearnerEvidenceSummary
from app.schemas.learner_evidence import (
    HintFact,
    LearnerEvidenceBatch,
    ModificationFact,
    PredictionFact,
    RetrievalAnswerFact,
    VerificationErrorFact,
)


def summarize_learner_evidence(batch: LearnerEvidenceBatch) -> LearnerEvidenceSummary:
    # Rebuild nested values so model_construct/model_copy cannot bypass boundaries.
    checked = LearnerEvidenceBatch.model_validate(batch.model_dump(warnings=False))
    counts = {
        "prediction_count": 0,
        "correct_prediction_count": 0,
        "modification_attempt_count": 0,
        "hint_request_count": 0,
        "hints_delivered_count": 0,
        "retrieval_answer_count": 0,
        "correct_retrieval_answer_count": 0,
        "verification_error_count": 0,
    }
    for fact in checked.facts:
        if isinstance(fact, PredictionFact):
            counts["prediction_count"] += 1
            counts["correct_prediction_count"] += int(fact.correct)
        elif isinstance(fact, ModificationFact):
            counts["modification_attempt_count"] += 1
        elif isinstance(fact, HintFact):
            counts["hint_request_count"] += 1
            counts["hints_delivered_count"] += int(fact.status == "delivered")
        elif isinstance(fact, RetrievalAnswerFact):
            counts["retrieval_answer_count"] += 1
            counts["correct_retrieval_answer_count"] += int(fact.correct)
        elif isinstance(fact, VerificationErrorFact):
            counts["verification_error_count"] += 1
    return LearnerEvidenceSummary.model_validate(counts)
