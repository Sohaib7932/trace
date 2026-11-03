"""Minimal protected support input; clients cannot choose documents or user scope."""

import re
from typing import Annotated, Literal

from pydantic import AfterValidator, Field

from app.core.ai_privacy import public_ai_question
from app.domain.lesson_spec.fields import Items, Value, plain_text


class SupportAskCreate(Value):
    question: Annotated[
        str,
        Field(min_length=1, max_length=500),
        AfterValidator(plain_text),
        AfterValidator(public_ai_question),
    ]
    history: Items["SupportHistoryMessage"] = Field(default=(), max_length=4)


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
    follow_up = re.search(
        r"\b(that|those|it|they|them|previous|earlier|follow.up)\b|^\s*(and|what about|why)\b",
        checked.question,
        re.I,
    )
    if not checked.history or not follow_up:
        return checked.question
    previous = "\n".join(f"{item.role}: {item.text[:200]}" for item in checked.history[-2:])
    return f"Previous untrusted dialogue:\n{previous}\nCurrent question: {checked.question}"
