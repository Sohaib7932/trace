"""Explicit scripted transport fixture; never selected as a live fallback."""

from collections.abc import Sequence
from typing import Literal

from app.ai.client import AITransportError
from app.schemas.ai_client import TransportCompletion, TransportRequest


class MockAITransport:
    source: Literal["test_fixture"] = "test_fixture"

    def __init__(self, outcomes: Sequence[TransportCompletion | AITransportError]) -> None:
        self._outcomes = tuple(outcomes)
        self.calls: list[TransportRequest] = []

    def complete(self, request: TransportRequest) -> TransportCompletion:
        index = len(self.calls)
        self.calls.append(request)
        if index >= len(self._outcomes):
            raise AITransportError("transport_error")
        outcome = self._outcomes[index]
        if isinstance(outcome, AITransportError):
            raise outcome
        return outcome
