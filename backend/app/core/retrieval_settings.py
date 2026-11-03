"""Operator-only retrieval selection. Experimental vectors never auto-promote."""

from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RetrievalSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRACE_RETRIEVAL_",
        env_file=None,
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )
    mode: Literal["lexical", "semantic", "hybrid"] = "lexical"
    allow_unreviewed_experiment: bool = False
    index_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    lexical_weight: float = Field(default=1, ge=0, le=4)
    semantic_weight: float = Field(default=1, ge=0, le=4)
    minimum_cosine: float = Field(default=0, ge=-1, le=1)

    @model_validator(mode="after")
    def explicit_experiment(self) -> Self:
        if self.mode != "lexical" and (
            not self.allow_unreviewed_experiment or self.index_sha256 is None
        ):
            raise ValueError("Vector retrieval requires an explicit experiment and pinned index")
        if self.mode == "hybrid" and self.lexical_weight + self.semantic_weight == 0:
            raise ValueError("Hybrid retrieval requires a positive weight")
        return self
