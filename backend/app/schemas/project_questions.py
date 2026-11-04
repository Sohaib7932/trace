"""Bounded questions and exact source citations for private Project Learning."""

from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, model_validator

from app.domain.lesson_spec.fields import Digest, Items, Value
from app.schemas.conversation_tutor import TutorHistoryMessage, chat_text
from app.schemas.github_projects import CommitSha, ProjectExplanation
from app.schemas.project_knowledge import untrusted_source


class ProjectQuestionCreate(Value):
    commit_sha: CommitSha
    question: Annotated[str, Field(min_length=1, max_length=2000), AfterValidator(chat_text)] = (
        Field(repr=False)
    )
    history: Items[TutorHistoryMessage] = Field(default=(), max_length=4, repr=False)

    @model_validator(mode="after")
    def bounded_request(self) -> Self:
        if len(self.model_dump_json().encode("utf-8")) > 9000:
            raise ValueError("Project question exceeds the bounded request size")
        return self


class ProposedProjectCitation(Value):
    reference_id: Digest
    quote: Annotated[str, Field(min_length=3, max_length=500), AfterValidator(untrusted_source)]


class ProposedProjectSection(Value):
    explanation: ProjectExplanation
    citations: Items[ProposedProjectCitation] = Field(min_length=1, max_length=3)


class ProposedProjectAnswer(Value):
    schema_version: Literal["project-answer-v1"]
    status: Literal["answered", "insufficient_information"]
    sections: Items[ProposedProjectSection] = Field(default=(), max_length=5)

    @model_validator(mode="after")
    def supported_sections(self) -> Self:
        if bool(self.sections) != (self.status == "answered"):
            raise ValueError("Unsupported questions must abstain without conclusions")
        return self


class ProjectAnswerCitation(Value):
    reference_id: Digest
    path: str = Field(min_length=1, max_length=500)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    quote: str = Field(min_length=3, max_length=500, repr=False)

    @model_validator(mode="after")
    def ordered_lines(self) -> Self:
        if self.line_end < self.line_start:
            raise ValueError("Citation lines must be ordered")
        return self


class ProjectAnswerSection(Value):
    explanation: ProjectExplanation
    citations: Items[ProjectAnswerCitation] = Field(min_length=1, max_length=3)


class ProjectQuestionAnswer(Value):
    schema_version: Literal["project-question-v1"] = "project-question-v1"
    status: Literal["answered", "insufficient_information", "unavailable"]
    sections: Items[ProjectAnswerSection] = Field(default=(), max_length=5)
    commit_sha: CommitSha
    snapshot_digest: Digest
    source: Literal["ai", "test_fixture", "none"] = "none"
    selected_references: int = Field(ge=0, le=12)
    limitations: Items[str] = Field(default=(), max_length=5)
    grading: Literal["ungraded"] = "ungraded"
    execution_status: Literal["not_executed"] = "not_executed"
    can_complete_lesson: Literal[False] = False

    @model_validator(mode="after")
    def consistent_delivery(self) -> Self:
        if self.status == "answered":
            if not self.sections or self.source == "none":
                raise ValueError("An answer needs grounded sections and actual provenance")
        elif self.sections or self.source != "none":
            raise ValueError("Unavailable or unsupported replies cannot contain an invented answer")
        return self
