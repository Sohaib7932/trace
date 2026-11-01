"""Future server-resolved policy and atomic assignment ports. No implementation exists."""

from typing import Protocol
from uuid import UUID

from app.domain.daily_assignments import ResolvedLearnerTimezone
from app.schemas.daily_assignments import (
    ApprovedAssignmentSemantics,
    AtomicAssignmentReceipt,
    AtomicAssignmentRequest,
)


class LearnerTimezoneResolver(Protocol):
    def resolve(self, learner_id: UUID) -> ResolvedLearnerTimezone | None:
        """Resolve approved learner authority; missing data must never fall back to host time."""
        ...


class AssignmentSemanticsResolver(Protocol):
    def resolve(self) -> ApprovedAssignmentSemantics | None: ...


class AtomicAssignmentStore(Protocol):
    def try_assign(self, request: AtomicAssignmentRequest) -> AtomicAssignmentReceipt:
        """Future single-transaction authority, not a count-then-insert convenience API.

        Verify owned learner and authoritative candidate validation, human approval,
        separately authorized release and non-fixture provenance. Re-read eligibility
        while atomically checking the three-new-assignment cap and inserting its row.
        Exact learner/key retries return the original immutable receipt/day, even
        after midnight; a changed candidate or policy binding conflicts. Uniqueness
        and concurrency protection belong in the store, never an LLM or frontend.
        Hints, explanations, retries, review and retrieval do not invoke this port.
        """
        ...
