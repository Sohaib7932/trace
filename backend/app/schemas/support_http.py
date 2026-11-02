"""Minimal protected support input; clients cannot choose documents or user scope."""

from typing import Annotated

from pydantic import AfterValidator, Field

from app.core.ai_privacy import public_ai_question
from app.domain.lesson_spec.fields import Value, plain_text


class SupportAskCreate(Value):
    question: Annotated[
        str,
        Field(min_length=1, max_length=500),
        AfterValidator(plain_text),
        AfterValidator(public_ai_question),
    ]
