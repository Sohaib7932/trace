"""Customer-safe, stateless support contracts; no account or lesson records."""

import re
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import AfterValidator, Field, model_validator

from app.domain.lesson_spec.fields import Items, LocalId, Title, Value, plain_text


def support_question(value: str) -> str:
    plain_text(value)
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError:
        raise ValueError("Support questions must be valid UTF-8") from None
    if size > 4000 or re.search(
        r"(?i)(?:\b(?:sk|ghp|github_pat)-?[A-Za-z0-9_]{12,}"
        r"|\b(?:api[_ -]?key|password|secret|token)\s*[:=]\s*\S+)",
        value,
    ):
        raise ValueError("Do not include credentials in support questions")
    return value


def customer_reference(value: str) -> str:
    """Defense in depth for approved references, not automatic source approval."""
    plain_text(value)
    if re.search(
        r"(?i)(?:\b(?:sk|ghp|github_pat)-?[A-Za-z0-9_]{12,}"
        r"|\b(?:api[_ -]?key|password|secret|token)\s*[:=]\s*\S+"
        r"|(?:\.env\b|\.claude-logs\b|[A-Z]:\\|backend[/\\]|app[/\\]db)"
        r"|\b(?:ignore|override|disregard)\b.{0,60}\b(?:instructions|rules|policy|prompt)\b"
        r"|\b(?:system|developer)\s*(?:message|prompt|:))",
        value,
    ):
        raise ValueError("Reference is not suitable for customer support")
    return value


type QuestionText = Annotated[
    str, Field(min_length=1, max_length=1000), AfterValidator(support_question)
]
type PassageText = Annotated[
    str, Field(min_length=1, max_length=1200), AfterValidator(customer_reference)
]


class SupportQuestion(Value):
    question: QuestionText = Field(repr=False)


class SupportPassage(Value):
    passage_id: LocalId
    text: PassageText = Field(repr=False)


class SupportDocument(Value):
    """Server-approved copy only; an approval label is not a review mechanism."""

    source_id: LocalId
    title: Annotated[Title, AfterValidator(customer_reference)]
    approval: Literal["approved_customer_safe", "test_fixture"]
    passages: Items[SupportPassage] = Field(min_length=1, max_length=8, repr=False)

    @model_validator(mode="after")
    def bounded_unique_passages(self) -> Self:
        ids = [passage.passage_id for passage in self.passages]
        if len(ids) != len(set(ids)):
            raise ValueError("Support passage identifiers must be unique")
        if len(self.model_dump_json().encode("utf-8")) > 8192:
            raise ValueError("Support document exceeds the byte limit")
        return self


class SupportMatch(Value):
    source_id: LocalId
    title: Title
    passage_id: LocalId
    text: PassageText = Field(repr=False)
    approval: Literal["approved_customer_safe", "test_fixture"]


class SupportSelection(Value):
    """The model selects references. It cannot write unsupported factual prose."""

    status: Literal["answered", "unsupported"]
    passage_ids: Items[LocalId] = Field(max_length=3)

    @model_validator(mode="after")
    def consistent_selection(self) -> Self:
        if len(self.passage_ids) != len(set(self.passage_ids)):
            raise ValueError("Selected passages must be distinct")
        if (self.status == "answered") != bool(self.passage_ids):
            raise ValueError("An answered request requires source passages")
        return self


class SupportSelectionResult(Value):
    """Server-set provenance, never a field the model is permitted to supply."""

    selection: SupportSelection
    source: Literal["test_fixture", "ai"]


class SupportReference(Value):
    source_id: LocalId
    source_name: Title
    passage_id: LocalId
    quote: PassageText


def public_support_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        or len(value) > 300
        or any(ord(char) < 33 for char in value)
    ):
        raise ValueError("Use an approved public HTTPS support destination")
    return value


class SupportEscalation(Value):
    label: Title
    url: Annotated[str, Field(min_length=1, max_length=300), AfterValidator(public_support_url)]


type SupportStatus = Literal["answered", "no_sources", "unsupported", "unavailable"]
type SupportMessage = Literal[
    "Relevant approved documentation is quoted below.",
    "No relevant approved documentation was found.",
    "The approved documentation does not establish an answer.",
    "Customer support is currently unavailable.",
]


class SupportResponse(Value):
    status: SupportStatus
    message: SupportMessage
    references: Items[SupportReference] = Field(default=(), max_length=3)
    escalation: SupportEscalation | None = None
    source: Literal["test_fixture", "ai", "unavailable"]

    @model_validator(mode="after")
    def grounded_response(self) -> Self:
        if (self.status == "answered") != bool(self.references):
            raise ValueError("Only an answered response can contain supporting quotations")
        if self.status == "answered" and self.source == "unavailable":
            raise ValueError("An unavailable provider cannot establish an answer")
        expected: dict[SupportStatus, SupportMessage] = {
            "answered": "Relevant approved documentation is quoted below.",
            "no_sources": "No relevant approved documentation was found.",
            "unsupported": "The approved documentation does not establish an answer.",
            "unavailable": "Customer support is currently unavailable.",
        }
        if self.message != expected[self.status]:
            raise ValueError("Support diagnostics must match the response status")
        return self
