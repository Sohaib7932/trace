"""Client supplies a bounded question, never lesson context, evidence or policy."""

from typing import Annotated

from pydantic import AfterValidator, Field

from app.core.ai_privacy import public_ai_question
from app.domain.lesson_spec.fields import Value, plain_text


class TutorQuestionCreate(Value):
    question: Annotated[
        str,
        Field(min_length=1, max_length=400),
        AfterValidator(plain_text),
        AfterValidator(public_ai_question),
    ]
