"""Inactive, provider-neutral AI limits. No credential values are loaded here."""

from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.schemas.generation import TransportIdentifier

type Limit = Annotated[StrictInt, Field(ge=1)]
type Money = Annotated[StrictInt, Field(ge=0, le=1_000_000_000)]


class AIClientSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRACE_LLM_", extra="forbid", frozen=True, hide_input_in_errors=True
    )

    # Live mode requires separately reviewed provider-specific implementation.
    mode: Literal["disabled", "mock"] = "disabled"
    provider_id: TransportIdentifier | None = None
    generation_model_id: TransportIdentifier | None = None
    conversational_model_id: TransportIdentifier | None = None
    credential_env_var: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{0,127}$")] | None = None
    max_request_bytes: Annotated[Limit, Field(le=65536)] = 32768
    max_response_bytes: Annotated[Limit, Field(le=65536)] = 16384
    max_input_tokens: Annotated[Limit, Field(le=65536)] = 16384
    max_output_tokens: Annotated[Limit, Field(le=16384)] = 4096
    connect_timeout_seconds: Annotated[float, Field(gt=0, le=10)] = 3.0
    response_timeout_seconds: Annotated[float, Field(gt=0, le=30)] = 10.0
    total_timeout_seconds: Annotated[float, Field(gt=0, le=60)] = 20.0
    max_retries: Annotated[StrictInt, Field(ge=0, le=2)] = 0
    requests_per_minute: Annotated[Limit, Field(le=60)] = 10
    max_subjects: Annotated[Limit, Field(le=10000)] = 1000
    spend_limit_microusd: Money = 0
    max_cost_per_attempt_microusd: Money = 0

    @field_validator(
        "max_request_bytes",
        "max_response_bytes",
        "max_input_tokens",
        "max_output_tokens",
        "max_retries",
        "requests_per_minute",
        "max_subjects",
        "spend_limit_microusd",
        "max_cost_per_attempt_microusd",
        mode="before",
    )
    @classmethod
    def environment_integer(cls, value: object) -> object:
        # Environment files contain strings. Preserve strict rejection of booleans,
        # floats and arbitrary coercions while accepting bounded decimal settings.
        if isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 10:
            return int(value)
        return value

    @field_validator(
        "provider_id",
        "generation_model_id",
        "conversational_model_id",
        "credential_env_var",
        mode="before",
    )
    @classmethod
    def empty_optional_configuration(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def consistent_limits(self) -> Self:
        if self.mode == "mock" and self.provider_id not in {None, "mock"}:
            raise ValueError("Mock mode requires the explicitly labelled mock provider")
        if self.max_cost_per_attempt_microusd > self.spend_limit_microusd:
            raise ValueError("Per-attempt reservation cannot exceed the process spending cap")
        if self.response_timeout_seconds > self.total_timeout_seconds:
            raise ValueError("Response timeout cannot exceed the total call deadline")
        return self
