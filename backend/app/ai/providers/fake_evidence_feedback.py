"""Deterministic feedback selection fixture; never selected as a live fallback."""

import json
from collections.abc import Sequence

from app.schemas.evidence_feedback import (
    POLICY_VERSION,
    SELECTION_VERSION,
    FeedbackCompletion,
    FeedbackRequest,
)

type FakeFeedbackOutcome = FeedbackCompletion | Exception


class FakeEvidenceFeedbackProvider:
    def __init__(
        self,
        outcomes: FakeFeedbackOutcome | Sequence[FakeFeedbackOutcome] | None = None,
    ) -> None:
        self.calls: list[FeedbackRequest] = []
        self._single: FakeFeedbackOutcome | None = None
        self._outcomes: tuple[FakeFeedbackOutcome, ...] | None = None
        if isinstance(outcomes, (FeedbackCompletion, Exception)):
            self._single = outcomes
        elif outcomes is not None:
            self._outcomes = tuple(outcomes)
        if self._outcomes is not None and any(
            not isinstance(outcome, (FeedbackCompletion, Exception)) for outcome in self._outcomes
        ):
            raise ValueError("Unknown fake feedback outcome")

    def explain(self, request: FeedbackRequest) -> FeedbackCompletion:
        checked = FeedbackRequest.model_validate(request.model_dump(warnings=False))
        index = len(self.calls)
        self.calls.append(checked)
        outcome = self._single
        if self._outcomes is not None:
            if index >= len(self._outcomes):
                return FeedbackCompletion(
                    status="transport_error",
                    text=None,
                    source="test_fixture",
                    error_code="transport_error",
                )
            outcome = self._outcomes[index]
        if isinstance(outcome, Exception):
            raise outcome
        if outcome is not None:
            # Scripted results may deliberately violate the structured selection
            # contract. The feedback service owns rejection, never silent repair.
            return outcome
        data = {
            "schema_version": SELECTION_VERSION,
            "policy_version": POLICY_VERSION,
            "request_id": str(checked.request_id),
            "lesson": checked.evidence.lesson.model_dump(mode="json"),
            "state": checked.state,
            "choices": [
                {
                    "claim_id": claim.claim_id,
                    "wording_id": claim.wordings[0].wording_id,
                    "evidence_ids": [str(identity) for identity in claim.evidence_ids],
                    "lesson_reference_ids": list(claim.lesson_reference_ids),
                    "coverage_refs": [competency.value for competency in claim.coverage_refs],
                }
                for claim in checked.claims
            ],
        }
        return FeedbackCompletion(
            status="success", text=json.dumps(data, separators=(",", ":")), source="test_fixture"
        )
