"""Blocked readiness and future atomic-assignment contracts; no remaining-slot claims."""

from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BeforeValidator,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

from app.domain.clock import as_utc
from app.domain.daily_assignments import LocalDayWindow
from app.domain.lesson_spec.fields import (
    Items,
    LocalId,
    No,
    Value,
    VersionId,
    VersionReference,
    Yes,
    integer,
    plain_text,
)

type ReadinessRequirement = Literal[
    "learner_timezone_policy",
    "assignment_semantics",
    "atomic_assignment_store",
    "candidate_release_process",
]
REQUIREMENTS: tuple[ReadinessRequirement, ...] = (
    "learner_timezone_policy",
    "assignment_semantics",
    "atomic_assignment_store",
    "candidate_release_process",
)


class NewAssignmentRequest(Value):
    learner_id: VersionId
    candidate: VersionReference = Field(repr=False)
    idempotency_key: VersionId
    requested_at: AwareDatetime
    classification: Literal["new_assignment"] = "new_assignment"

    @field_validator("requested_at")
    @classmethod
    def utc_request_time(cls, value: AwareDatetime) -> AwareDatetime:
        return as_utc(value)


class DailyAssignmentBlocked(Value):
    status: Literal["blocked"] = "blocked"
    requirements: Items[ReadinessRequirement] = Field(
        default=REQUIREMENTS, min_length=4, max_length=4
    )
    maximum_new_assignments: Annotated[Literal[3], BeforeValidator(integer)] = 3
    assignment_created: No = False
    quota_enforced: No = False
    assignment_id: None = None

    @model_validator(mode="after")
    def explicit_missing_requirements(self) -> Self:
        if self.requirements != REQUIREMENTS:
            raise ValueError(
                "Daily assignment execution remains blocked by the declared requirements"
            )
        return self


class ApprovedAssignmentSemantics(Value):
    """Future server-owned policy reference, not a policy invented by this milestone."""

    policy_id: LocalId
    revision: LocalId
    approved: Yes


class AtomicAssignmentRequest(Value):
    request: NewAssignmentRequest
    local_day: LocalDayWindow
    timezone_key: Annotated[str, Field(min_length=1, max_length=128), AfterValidator(plain_text)]
    timezone_authority_revision: LocalId
    semantics: ApprovedAssignmentSemantics
    maximum_new_assignments: Annotated[Literal[3], BeforeValidator(integer)] = 3

    @model_validator(mode="after")
    def captured_request_day(self) -> Self:
        if not self.local_day.utc_start <= self.request.requested_at < self.local_day.utc_end:
            raise ValueError("Captured request time must match its explicitly resolved local day")
        return self


class AtomicAssignmentReceipt(Value):
    """Future authoritative store output. Current code never constructs assignment receipts."""

    status: Literal["assigned", "existing", "quota_exhausted", "ineligible", "conflict"]
    assignment_id: VersionId | None
    assigned_at: AwareDatetime | None
    local_day: LocalDayWindow | None
    quota_consumed: StrictBool

    @field_validator("assigned_at")
    @classmethod
    def utc_assignment_time(cls, value: AwareDatetime | None) -> AwareDatetime | None:
        return as_utc(value) if value is not None else None

    @model_validator(mode="after")
    def factual_assignment_identity(self) -> Self:
        exists = self.status in {"assigned", "existing"}
        if exists != all(
            value is not None for value in (self.assignment_id, self.assigned_at, self.local_day)
        ):
            raise ValueError("Only an actual assignment receipt may carry assignment identity")
        if not exists and any(
            value is not None for value in (self.assignment_id, self.assigned_at, self.local_day)
        ):
            raise ValueError("Non-assignment outcomes cannot invent assignment metadata")
        if self.quota_consumed != (self.status == "assigned"):
            raise ValueError("Only a newly created assignment consumes its quota")
        if (
            self.assigned_at is not None
            and self.local_day is not None
            and not (self.local_day.utc_start <= self.assigned_at < self.local_day.utc_end)
        ):
            raise ValueError("Assignment timestamp must fall in its authoritative local-day window")
        return self
