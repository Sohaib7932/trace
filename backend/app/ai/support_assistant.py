"""Support selection is a separate responsibility from lesson tutoring."""

from typing import Protocol

from app.schemas.support import SupportMatch, SupportQuestion, SupportSelectionResult


class SupportAssistant(Protocol):
    def select(
        self, question: SupportQuestion, passages: tuple[SupportMatch, ...], *, subject: str
    ) -> SupportSelectionResult | None:
        """Return validated reference selections, or None for unavailable assistance."""
        ...
