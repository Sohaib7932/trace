from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

ShortText = Annotated[str, Field(min_length=1, max_length=4000)]
EvidenceText = Annotated[str, Field(min_length=1, max_length=400)]


class TutorContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    scenario: ShortText
    learner_attempt: ShortText


class HintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    context: TutorContext
    level: int = Field(ge=1, le=3)


class EvaluatedAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    context: TutorContext
    outcome: Literal["correct", "incorrect", "infrastructure_error"]
    evidence: tuple[EvidenceText, ...] = Field(min_length=1, max_length=20)


class TutorMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=2400)
    source: Literal["test_fixture", "ai"]
    interpretation_only: Literal[True] = True


class MisconceptionAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    possible_misconception: str | None = Field(default=None, min_length=1, max_length=1200)
    source: Literal["test_fixture", "ai"]
    interpretation_only: Literal[True] = True
