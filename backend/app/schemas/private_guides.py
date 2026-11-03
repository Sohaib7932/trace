"""Private instructional material, never an executable LessonSpec or grading contract."""

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AfterValidator, Field, model_validator

from app.core.ai_privacy import public_ai_question
from app.domain.lesson_spec.fields import Digest, Items, LocalId, Value, Yes, plain_text
from app.schemas.conversation_tutor import explanatory_text

type Level = Literal["beginner", "intermediate", "advanced"]
type InputText = Annotated[
    str,
    Field(min_length=1, max_length=600),
    AfterValidator(plain_text),
    AfterValidator(public_ai_question),
]
type GuideText = Annotated[
    str,
    Field(min_length=1, max_length=3000),
    AfterValidator(plain_text),
    AfterValidator(explanatory_text),
]
type GuideTitle = Annotated[
    str,
    Field(min_length=1, max_length=150),
    AfterValidator(plain_text),
    AfterValidator(explanatory_text),
]


class GuideCreate(Value):
    topic: Annotated[InputText, Field(max_length=500)] = Field(repr=False)
    start_level: Level
    target_level: Level
    practical: bool
    goals: InputText | None = Field(default=None, repr=False)
    preferences: InputText | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def bounds(self) -> Self:
        if len(self.model_dump_json().encode("utf-8")) > 7000:
            raise ValueError("Guide request exceeds its byte limit")
        return self


class GuideExample(Value):
    language: Literal["python", "typescript", "javascript", "text", "sql"]
    code: GuideText = Field(repr=False)
    explanation: GuideText = Field(repr=False)


class GuideSection(Value):
    id: LocalId
    title: GuideTitle
    explanation: GuideText = Field(repr=False)
    example: GuideExample | None
    practice: GuideText | None = Field(repr=False)
    expected_outcome: GuideText


class GuideContent(Value):
    schema_version: Literal["private-learning-guide-v1"]
    title: GuideTitle
    description: GuideText
    learning_objectives: Items[GuideTitle] = Field(min_length=1, max_length=6)
    sections: Items[GuideSection] = Field(min_length=2, max_length=6, repr=False)
    summary: GuideText

    @model_validator(mode="after")
    def consistency(self) -> Self:
        identifiers = [section.id for section in self.sections]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Section IDs must be unique")
        if len(self.model_dump_json().encode("utf-8")) > 14000:
            raise ValueError("Guide content exceeds 14000 UTF-8 bytes")
        return self


def canonical_digest(value: Value) -> str:
    data = json.dumps(
        value.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


class GuideSummary(Value):
    id: UUID
    topic: str
    status: Literal["generating", "ready", "unavailable"]
    created_at: datetime
    updated_at: datetime
    version: Literal["1.0.0"] = "1.0.0"
    title: str | None


class GuideDetail(GuideSummary):
    generation_version: Literal["private-guide-generator-v1"] = "private-guide-generator-v1"
    request: GuideCreate = Field(repr=False)
    content: GuideContent | None = Field(repr=False)
    content_sha256: Digest | None
    source: Literal["ai", "test_fixture"] | None
    ungraded: Yes = True
    execution_status: Literal["not_executed"] = "not_executed"

    @model_validator(mode="after")
    def provenance(self) -> Self:
        if self.status == "ready":
            if self.content is None or self.source is None:
                raise ValueError("Ready guides require content and provider provenance")
            if self.content_sha256 != canonical_digest(self.content):
                raise ValueError("Guide content digest failed")
            if self.title != self.content.title:
                raise ValueError("Guide title integrity failed")
        elif any(value is not None for value in (self.content, self.content_sha256, self.source)):
            raise ValueError("Incomplete guides cannot expose generated content")
        return self
