"""Explicit public-MVP mode: trusted deterministic text, without a model call."""

from app.schemas.evidence_feedback import FeedbackCompletion, FeedbackRequest


class DisabledEvidenceFeedbackProvider:
    def explain(self, request: FeedbackRequest) -> FeedbackCompletion:
        # The existing feedback service renders its backend-authorized claims
        # when optional explanatory generation is disabled. No mock wording is
        # presented as live AI, and no credentials/transport are constructed.
        return FeedbackCompletion(
            status="unavailable", text=None, source="none", error_code="disabled"
        )
