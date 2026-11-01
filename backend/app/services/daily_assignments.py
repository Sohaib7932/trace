"""Fail-closed readiness only. No learner assignment, quota counter or store call exists."""

from app.repositories.assignments import (
    AssignmentSemanticsResolver,
    AtomicAssignmentStore,
    LearnerTimezoneResolver,
)
from app.schemas.daily_assignments import DailyAssignmentBlocked, NewAssignmentRequest


class DailyAssignmentService:
    def __init__(
        self,
        timezone_resolver: LearnerTimezoneResolver | None = None,
        semantics_resolver: AssignmentSemanticsResolver | None = None,
        store: AtomicAssignmentStore | None = None,
    ) -> None:
        # These are future integration boundaries, not authority supplied by a model
        # or proof that product policy and a persistent atomic implementation exist.
        self.timezone_resolver, self.semantics_resolver, self.store = (
            timezone_resolver,
            semantics_resolver,
            store,
        )

    def readiness(self) -> DailyAssignmentBlocked:
        return DailyAssignmentBlocked()

    def request_new(self, request: NewAssignmentRequest) -> DailyAssignmentBlocked:
        NewAssignmentRequest.model_validate_json(request.model_dump_json(warnings=False))
        # Deliberately do not resolve unapproved policy, compute availability, read a
        # counter, call a fake store or fabricate an assignment/remaining-slot value.
        return self.readiness()
