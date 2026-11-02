"""Server-owned support review metadata; labels alone do not establish approval."""

from typing import Literal

from pydantic import AwareDatetime, Field, StrictBool, model_validator

from app.domain.lesson_spec.fields import Digest, Items, LocalId, No, Value, Version


class SupportSourceReview(Value):
    source_id: LocalId
    revision: Version
    document_sha256: Digest
    review_status: Literal["draft", "unknown", "approved"]
    reviewed_at: AwareDatetime | None = None
    valid_until: AwareDatetime | None = None
    declared_conflict: StrictBool = False


type ReadinessCode = Literal[
    "missing_document",
    "missing_review",
    "draft",
    "unapproved",
    "fixture_not_enabled",
    "content_mismatch",
    "missing_freshness",
    "future_review",
    "invalid_review_window",
    "stale",
    "declared_conflict",
]


class SupportReadinessIssue(Value):
    source_id: LocalId
    code: ReadinessCode


class SupportReadinessReport(Value):
    status: Literal["prepared", "unavailable"]
    evaluated_at: AwareDatetime
    prepared_source_ids: Items[LocalId] = Field(default=(), max_length=32)
    issues: Items[SupportReadinessIssue] = Field(default=(), max_length=64)
    fixture_mode: StrictBool = False
    production_activated: No = False

    @model_validator(mode="after")
    def consistent_report(self) -> "SupportReadinessReport":
        if (self.status == "prepared") != bool(self.prepared_source_ids):
            raise ValueError("Prepared support sources must match the readiness status")
        if len(self.prepared_source_ids) != len(set(self.prepared_source_ids)):
            raise ValueError("Prepared support sources must be unique")
        return self
