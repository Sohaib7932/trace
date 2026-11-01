"""Public-only, stateless lesson assistance; never evaluation or progress commands."""

from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, model_validator

from app.domain.lesson_spec.fields import CheckCode, Items, No, Value, Yes, plain_text


def _utf8(value: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ValueError("Lesson assistance requires valid UTF-8") from None
    return value


type SupportedLesson = Literal["fastapi-payload-mismatch", "fastapi-nested-payload-transfer"]
type LessonStage = Literal["predict", "investigate", "modify", "verify", "transfer", "revisit"]
type AssistantText = Annotated[
    str, Field(min_length=1, max_length=2400), AfterValidator(plain_text), AfterValidator(_utf8)
]
type VisibleText = Annotated[
    str, Field(min_length=1, max_length=600), AfterValidator(plain_text), AfterValidator(_utf8)
]
type PublicCode = Annotated[str, Field(min_length=1, max_length=2400), AfterValidator(_utf8)]


class PublicLessonContent(Value):
    """The existing catalog's five learner-visible fields, without its private siblings."""

    title: Annotated[str, Field(min_length=1, max_length=120), AfterValidator(plain_text)]
    objective: Annotated[str, Field(min_length=1, max_length=1000), AfterValidator(plain_text)]
    scenario: AssistantText
    outgoing_code: PublicCode = Field(repr=False)
    schema_code: PublicCode = Field(repr=False)


class VisibleEvidence(Value):
    """Caller supplies only feedback already visible to this owned learner session."""

    category: CheckCode
    feedback: VisibleText = Field(repr=False)


class LessonAssistantContext(Value):
    lesson_id: SupportedLesson
    stage: LessonStage
    lesson: PublicLessonContent = Field(repr=False)
    visible_attempt: AssistantText | None = Field(default=None, repr=False)
    evidence: Items[VisibleEvidence] = Field(default=(), max_length=5, repr=False)
    previous_hints: Items[VisibleText] = Field(default=(), max_length=3, repr=False)

    @model_validator(mode="after")
    def unique_evidence_categories(self) -> Self:
        categories = [item.category for item in self.evidence]
        if len(categories) != len(set(categories)):
            raise ValueError("Visible evidence categories must be unique")
        return self


class LessonAssistantRequest(Value):
    context: LessonAssistantContext = Field(repr=False)
    question: AssistantText = Field(repr=False)
    hint_level: Annotated[int, Field(ge=1, le=3)] | None = None

    @model_validator(mode="after")
    def bounded_context(self) -> Self:
        try:
            size = len(self.model_dump_json().encode("utf-8"))
        except UnicodeError:
            raise ValueError("Lesson assistance requires valid UTF-8") from None
        if size > 16384:
            raise ValueError("Lesson assistance exceeds 16384 UTF-8 bytes")
        return self


class LessonAssistantReply(Value):
    status: Literal["answered", "declined", "unavailable"]
    text: AssistantText = Field(repr=False)
    source: Literal["test_fixture", "ai", "none"]
    interpretation_only: Yes = True
    can_complete_lesson: No = False

    @model_validator(mode="after")
    def unavailable_has_no_provider_answer(self) -> Self:
        if (self.status == "unavailable") != (self.source == "none"):
            raise ValueError("Unavailable assistance cannot claim a provider answer")
        return self
