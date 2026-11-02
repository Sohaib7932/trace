"""Durable hint-request identity, separate from append-only delivered guidance."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.learning import TutorInteraction


@dataclass(frozen=True)
class HintOperation:
    id: UUID
    session_id: UUID
    attempt_id: UUID | None
    sequence: int
    idempotency_key: str
    created_at: datetime
    deadline_at: datetime
    status: str = "pending"
    completed_at: datetime | None = None


def hint_request_count(
    hints: Iterable[TutorInteraction], operations: Iterable[HintOperation]
) -> int:
    """Reservations already represented by a final interaction count only once."""
    return max(
        (item.sequence for collection in (hints, operations) for item in collection), default=0
    )
