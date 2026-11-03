"""Provider-neutral limits and explicitly approved free-tier activation metadata."""

from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.schemas.generation import TransportIdentifier

type Limit = Annotated[StrictInt, Field(ge=1)]
type Money = Annotated[StrictInt, Field(ge=0, le=1_000_000_000)]

GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_PROFILE = "gemini-free-text-v1"
GEMINI_MAX_OUTPUT_TOKENS = 4096
GEMINI_MAX_RESPONSE_SECONDS = 20.0


class AIClientSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRACE_LLM_", extra="forbid", frozen=True, hide_input_in_errors=True
    )

    mode: Literal["disabled", "mock", "gemini_free"] = "disabled"
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
    free_tier_project_confirmed: bool = False
    max_live_requests_per_process: Annotated[Limit, Field(le=100)] = 20
    max_in_flight: Annotated[Limit, Field(le=16)] = 4

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
        "max_live_requests_per_process",
        "max_in_flight",
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

    @field_validator("free_tier_project_confirmed", mode="before")
    @classmethod
    def explicit_free_tier_confirmation(cls, value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in {"true", "false"}:
            return value.lower() == "true"
        raise ValueError("Free-tier confirmation must be explicitly true or false")

    @model_validator(mode="after")
    def consistent_limits(self) -> Self:
        if self.mode == "mock" and self.provider_id not in {None, "mock"}:
            raise ValueError("Mock mode requires the explicitly labelled mock provider")
        if self.max_cost_per_attempt_microusd > self.spend_limit_microusd:
            raise ValueError("Per-attempt reservation cannot exceed the process spending cap")
        if self.response_timeout_seconds > self.total_timeout_seconds:
            raise ValueError("Response timeout cannot exceed the total call deadline")
        if self.mode == "gemini_free" and (
            self.provider_id != "gemini"
            or self.generation_model_id != GEMINI_MODEL
            or self.conversational_model_id != GEMINI_MODEL
            or self.credential_env_var != "GEMINI_API_KEY"
            or not self.free_tier_project_confirmed
            or self.spend_limit_microusd != 0
            or self.max_cost_per_attempt_microusd != 0
            or self.max_retries != 0
        ):
            raise ValueError(
                "Gemini requires the approved model, confirmed free project and zero paid budget"
            )
        if self.mode == "gemini_free" and (
            self.max_output_tokens > GEMINI_MAX_OUTPUT_TOKENS
            or self.response_timeout_seconds > GEMINI_MAX_RESPONSE_SECONDS
            or self.max_in_flight > 4
        ):
            raise ValueError("Limits exceed the approved Gemini text capability profile")
        return self
