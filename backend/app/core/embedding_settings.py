"""Independent disabled-by-default embedding settings; no private env-file writes."""

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EmbeddingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRACE_EMBEDDING_",
        env_file=None,
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )
    mode: Literal["disabled", "mock", "gemini_free"] = "disabled"
    model_id: Literal["gemini-embedding-001"] = "gemini-embedding-001"
    dimensions: Literal[768] = 768
    free_tier_unbilled_project_confirmed: bool = False
    paid_budget_microusd: Literal[0] = 0
    max_retries: Literal[0] = 0
    max_requests_per_process: int = Field(default=32, ge=1, le=1000)
    max_items_per_process: int = Field(default=512, ge=1, le=10000)
    max_reserved_input_tokens_per_process: int = Field(default=100000, ge=1, le=1000000)
    max_concurrent_requests: int = Field(default=2, ge=1, le=4)
    connect_timeout_seconds: float = Field(default=3, gt=0, le=10)
    response_timeout_seconds: float = Field(default=10, gt=0, le=30)
    max_response_bytes: int = Field(default=4194304, ge=4096, le=4194304)

    @field_validator(
        "dimensions",
        "paid_budget_microusd",
        "max_retries",
        "max_requests_per_process",
        "max_items_per_process",
        "max_reserved_input_tokens_per_process",
        "max_concurrent_requests",
        "max_response_bytes",
        mode="before",
    )
    @classmethod
    def strict_decimal_environment_integer(cls, value: object) -> int:
        if isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 10:
            return int(value)
        if type(value) is not int:
            raise ValueError(
                "Embedding integer limits require integers or decimal environment text"
            )
        return value

    @field_validator("free_tier_unbilled_project_confirmed", mode="before")
    @classmethod
    def explicit_boolean(cls, value: object) -> bool:
        if type(value) is bool:
            return value
        if isinstance(value, str) and value.lower() in {"true", "false"}:
            return value.lower() == "true"
        raise ValueError("Free-project confirmation must be explicitly true or false")

    @field_validator("connect_timeout_seconds", "response_timeout_seconds", mode="before")
    @classmethod
    def no_boolean_deadline(cls, value: object) -> object:
        if type(value) is bool:
            raise ValueError("Embedding deadlines must be numeric seconds")
        return value

    @model_validator(mode="after")
    def explicit_free_mode(self) -> Self:
        if self.mode == "gemini_free" and not self.free_tier_unbilled_project_confirmed:
            raise ValueError("Explicit unbilled free-project confirmation is required")
        if self.connect_timeout_seconds > self.response_timeout_seconds:
            raise ValueError("Connection budget cannot exceed the total response budget")
        return self
