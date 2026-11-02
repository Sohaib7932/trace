"""Internal phrasing port; evidence authority remains in deterministic backend code."""

from typing import Protocol

from app.schemas.evidence_feedback import FeedbackCompletion, FeedbackRequest


class EvidenceFeedbackProvider(Protocol):
    def explain(self, request: FeedbackRequest) -> FeedbackCompletion: ...
