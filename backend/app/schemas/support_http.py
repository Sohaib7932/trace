"""Minimal protected support input; clients cannot choose documents or user scope."""

import re
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, model_validator

from app.core.ai_privacy import public_ai_question
from app.domain.lesson_spec.fields import Items, Value, plain_text
from app.schemas.support import SupportQuestion


class SupportAskCreate(Value):
    question: Annotated[
        str,
        Field(min_length=1, max_length=500),
        AfterValidator(plain_text),
        AfterValidator(public_ai_question),
    ]
    history: Items["SupportHistoryMessage"] = Field(default=(), max_length=4)

    @model_validator(mode="after")
    def valid_internal_question(self) -> "SupportAskCreate":
        # Validate the actual bounded request before any admitted worker runs.
        # A field-only check misses credential patterns formed across dialogue
        # boundaries; unused history retains its existing shape/meaning.
        SupportQuestion(question=_render_context(self))
        return self


class SupportHistoryMessage(Value):
    role: Literal["user", "assistant"]
    text: Annotated[
        str,
        Field(min_length=1, max_length=250),
        AfterValidator(plain_text),
        AfterValidator(public_ai_question),
    ] = Field(repr=False)


SupportAskCreate.model_rebuild()


def contextual_support_question(body: SupportAskCreate) -> str:
    """Carry bounded untrusted dialogue only for explicit conversational references.

    Prior replies never establish facts or source permission. The ordinary
    retrieval/selection/revalidation pipeline must still establish every quote.
    Standalone unrelated questions do not inherit an earlier supported topic.
    """
    checked = SupportAskCreate.model_validate(body.model_dump(warnings=False))
    return _render_context(checked)


def _render_context(body: SupportAskCreate) -> str:
    """Pure context rendering, shared with schema validation without recursion."""
    follow_up = re.search(
        r"\b(that|those|it|they|them|previous|earlier|follow.up)\b|^\s*(and|what about|why)\b",
        body.question,
        re.I,
    )
    if not body.history or not follow_up:
        return body.question
    previous = "\n".join(f"{item.role}: {item.text[:200]}" for item in body.history[-2:])
    return f"Previous untrusted dialogue:\n{previous}\nCurrent question: {body.question}"
