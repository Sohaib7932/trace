"""Explicit learner-safe values, separate from internal evidence/provenance.

These are output contracts, never authentication or evidence inputs. No public
route accepts them. An internal, release-authorized projector supplies the data.
"""

from types import MappingProxyType
from typing import Annotated, Final, Literal, Self
from uuid import UUID

from pydantic import ConfigDict, Field, StrictBool, field_validator, model_validator

from app.domain.lesson_spec.fields import CheckCode, Digest, Items, LocalId, Value
from app.schemas.evidence_feedback import FeedbackState, FeedbackText, LessonField, SectionName
from app.schemas.feedback_release import FeedbackReleaseScope
from app.schemas.learner_evidence import UTCInstant

PUBLIC_SCHEMA_VERSION: Final = "evidence-feedback-public-v1"
VISIBILITY_POLICY_VERSION: Final = "evidence-feedback-visibility-v1"
NOTICE_NOT_READY: Final = "Feedback is not ready until an attempt has been submitted."
NOTICE_NOT_SUPPORTED: Final = "Feedback is not enabled for this session."
NOTICE_UNAVAILABLE: Final = "Feedback is unavailable. Try again later."
NOTICE_DETERMINISTIC: Final = "This feedback uses deterministic evidence rules."
NOTICE_MOCK: Final = "This feedback uses a deterministic mock wording selection."
NOTICE_INSUFFICIENT: Final = "There is not enough evidence for a competency conclusion."

LESSON_LABELS = MappingProxyType(
    {
        "title": "Lesson title",
        "objective": "Learning objective",
        "scenario": "Lesson scenario",
        "outgoing_code": "Outgoing request builder",
        "schema_code": "Receiving schema",
    }
)

type EvidenceAlias = Annotated[str, Field(pattern=r"^e(?:[1-9]|[1-5][0-9]|6[0-4])$")]
type LessonAlias = Annotated[str, Field(pattern=r"^l[1-5]$")]
type PublicRole = Literal["observation", "limitation", "next_action"]
type EvidenceDescription = Literal[
    "Your original prediction",
    "Your submitted attempt",
    "Your runtime verification",
    "Your recorded recovery sequence",
    "Your completed Tasks exercise",
    "Your hint request",
    "Your tutor guidance record",
]
type PublicLessonLabel = Literal[
    "Lesson title",
    "Learning objective",
    "Lesson scenario",
    "Outgoing request builder",
    "Receiving schema",
]
type PublicNotice = Literal[
    "Feedback is not ready until an attempt has been submitted.",
    "Feedback is not enabled for this session.",
    "Feedback is unavailable. Try again later.",
    "This feedback uses deterministic evidence rules.",
    "This feedback uses a deterministic mock wording selection.",
    "There is not enough evidence for a competency conclusion.",
]


class _PublicValue(Value):
    # A copied/constructed typed object is not a substitute for output validation.
    model_config = ConfigDict(revalidate_instances="always")


class FeedbackVisibilityPolicy(_PublicValue):
    """Backend configuration only; disabled until an audience is explicitly supplied.

    An approval reference is audit metadata, not proof or a client capability.
    Tests use clearly proposed references; no production policy is registered.
    Recall inclusion has not been approved and cannot be enabled in this V1.
    """

    policy_version: Literal["evidence-feedback-visibility-v1"] = VISIBILITY_POLICY_VERSION
    scope: FeedbackReleaseScope
    include_recall: Literal[False]
    next_action_ids: Items[Literal["compare-receiving-contract"]] = Field(max_length=1)
    allow_mock_delivery: StrictBool
    approval_reference: LocalId | None = Field(repr=False)

    @field_validator("scope", mode="before")
    @classmethod
    def refresh_scope(cls, value: object) -> object:
        if isinstance(value, FeedbackReleaseScope):
            return value.model_dump(warnings=False)
        return value

    @field_validator("include_recall", mode="before")
    @classmethod
    def recall_is_disabled(cls, value: object) -> object:
        if value is not False:
            raise ValueError("Recall disclosure is not approved for this policy version")
        return value

    @model_validator(mode="after")
    def explicit_configuration(self) -> Self:
        if (
            self.scope.allowed_modes
            or self.scope.allow_terminal_reflection
            or self.next_action_ids
            or self.allow_mock_delivery
        ) and self.approval_reference is None:
            raise ValueError("An explicit server-side policy reference is required")
        return self

    @classmethod
    def disabled(cls) -> Self:
        return cls(
            scope=FeedbackReleaseScope.disabled(),
            include_recall=False,
            next_action_ids=(),
            allow_mock_delivery=False,
            approval_reference=None,
        )


class PublicLessonIdentity(_PublicValue):
    lesson_id: Literal["fastapi-payload-mismatch", "fastapi-nested-payload-transfer"]
    version: Literal["1.0.0"]
    public_content_sha256: Digest


class PublicVerificationCheck(_PublicValue):
    code: CheckCode
    matched: StrictBool


class PublicEvidenceCitation(_PublicValue):
    alias: EvidenceAlias
    description: EvidenceDescription
    occurred_at: UTCInstant
    checks: Items[PublicVerificationCheck] = Field(max_length=5)

    @model_validator(mode="after")
    def exact_checks(self) -> Self:
        if len(self.checks) != len({check.code for check in self.checks}):
            raise ValueError("Verification check categories cannot repeat")
        if self.checks and self.description not in {
            "Your runtime verification",
            "Your recorded recovery sequence",
            "Your completed Tasks exercise",
        }:
            raise ValueError("Runtime checks require a corresponding observed event")
        return self


class PublicLessonCitation(_PublicValue):
    alias: LessonAlias
    lesson: PublicLessonIdentity
    field: LessonField
    label: PublicLessonLabel
    sha256: Digest

    @model_validator(mode="after")
    def exact_label(self) -> Self:
        if self.label != LESSON_LABELS[self.field]:
            raise ValueError("A lesson field must use its approved public label")
        return self


class PublicFeedbackStatement(_PublicValue):
    role: PublicRole
    text: FeedbackText = Field(repr=False)
    evidence_aliases: Items[EvidenceAlias] = Field(max_length=8)
    lesson_aliases: Items[LessonAlias] = Field(max_length=5)

    @model_validator(mode="after")
    def supported_statement(self) -> Self:
        if len(self.evidence_aliases) != len(set(self.evidence_aliases)) or len(
            self.lesson_aliases
        ) != len(set(self.lesson_aliases)):
            raise ValueError("Statement citations cannot repeat")
        if self.role == "observation" and not self.evidence_aliases:
            raise ValueError("A factual observation requires an evidence citation")
        if self.role == "next_action" and not self.lesson_aliases:
            raise ValueError("A next action requires approved lesson material")
        return self


class PublicFeedbackSection(_PublicValue):
    kind: SectionName
    items: Items[PublicFeedbackStatement] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def section_roles(self) -> Self:
        if self.kind == "next":
            if len(self.items) != 1 or self.items[0].role != "next_action":
                raise ValueError("The next section contains at most one approved next action")
        elif any(item.role == "next_action" for item in self.items):
            raise ValueError("Next actions belong only in the next section")
        if self.kind in {"demonstrated", "needs_improvement"} and any(
            item.role != "observation" for item in self.items
        ):
            raise ValueError("Observed actions and discrepancies require actual evidence")
        return self


class PublicFeedbackReply(_PublicValue):
    schema_version: Literal["evidence-feedback-public-v1"] = PUBLIC_SCHEMA_VERSION
    policy_version: Literal["evidence-feedback-visibility-v1"] = VISIBILITY_POLICY_VERSION
    availability: Literal["available", "not_ready", "not_supported", "unavailable"]
    feedback_state: FeedbackState | None
    delivery_state: Literal["deterministic", "mock", "unavailable"]
    session_id: UUID
    lesson: PublicLessonIdentity | None
    as_of: UTCInstant | None
    sections: Items[PublicFeedbackSection] = Field(max_length=4)
    # Keep native JSON array validation here. A container BeforeValidator
    # switches nested strict datetimes to Python mode, breaking wire roundtrips.
    evidence_citations: tuple[PublicEvidenceCitation, ...] = Field(max_length=64)
    lesson_citations: Items[PublicLessonCitation] = Field(max_length=5)
    notice: PublicNotice

    @model_validator(mode="after")
    def coherent_projection(self) -> Self:
        if self.availability != "available":
            expected = "unavailable" if self.availability == "unavailable" else None
            notices = {
                "not_ready": NOTICE_NOT_READY,
                "not_supported": NOTICE_NOT_SUPPORTED,
                "unavailable": NOTICE_UNAVAILABLE,
            }
            if (
                self.feedback_state != expected
                or self.delivery_state != "unavailable"
                or self.sections
                or self.evidence_citations
                or self.lesson_citations
                or self.lesson is not None
                or self.as_of is not None
                or self.notice != notices[self.availability]
            ):
                raise ValueError("Closed or unavailable feedback contains no evaluated content")
            return self
        if (
            self.feedback_state in {None, "unavailable"}
            or self.delivery_state == "unavailable"
            or self.lesson is None
            or self.as_of is None
        ):
            raise ValueError("Available feedback requires a pinned, evaluated result")
        if self.notice != (
            NOTICE_INSUFFICIENT
            if self.feedback_state == "insufficient_evidence"
            else NOTICE_MOCK
            if self.delivery_state == "mock"
            else NOTICE_DETERMINISTIC
        ):
            raise ValueError("Delivery and uncertainty require an accurate public notice")
        kinds = tuple(section.kind for section in self.sections)
        if len(kinds) != len(set(kinds)):
            raise ValueError("Public feedback sections cannot repeat")
        statements = tuple(item for section in self.sections for item in section.items)
        if len(statements) > 16:
            raise ValueError("Public feedback has at most sixteen statements")
        if self.feedback_state in {"supported", "partially_supported"} and not any(
            item.role == "observation" for item in statements
        ):
            raise ValueError("Neutral limitations alone cannot be supported feedback")
        if [ref.alias for ref in self.evidence_citations] != [
            f"e{index}" for index in range(1, len(self.evidence_citations) + 1)
        ] or [ref.alias for ref in self.lesson_citations] != [
            f"l{index}" for index in range(1, len(self.lesson_citations) + 1)
        ]:
            raise ValueError("Citations require unique response-local contiguous aliases")
        used_evidence = {alias for item in statements for alias in item.evidence_aliases}
        used_lesson = {alias for item in statements for alias in item.lesson_aliases}
        if used_evidence != {ref.alias for ref in self.evidence_citations} or used_lesson != {
            ref.alias for ref in self.lesson_citations
        }:
            raise ValueError(
                "Every citation must support a retained statement without dangling refs"
            )
        if any(ref.lesson != self.lesson for ref in self.lesson_citations):
            raise ValueError("Lesson citations must match the exact public lesson identity")
        return self
