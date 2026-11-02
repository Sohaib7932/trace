"""Process-local feedback limits; no provider activation or credential loading."""

from typing import Annotated, Self

from pydantic import Field, StrictInt, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

type FeedbackLimit = Annotated[StrictInt, Field(ge=1)]


class FeedbackSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRACE_FEEDBACK_",
        env_file=None,
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    requests_per_minute: Annotated[FeedbackLimit, Field(le=60)] = 10
    max_subjects: Annotated[FeedbackLimit, Field(le=10000)] = 1000
    max_subject_in_flight: Annotated[FeedbackLimit, Field(le=4)] = 1
    max_global_in_flight: Annotated[FeedbackLimit, Field(le=32)] = 4
    ingress_requests_per_minute: Annotated[FeedbackLimit, Field(le=600)] = 120
    max_ingress_in_flight: Annotated[FeedbackLimit, Field(le=64)] = 16
    request_timeout_seconds: Annotated[float, Field(gt=0, le=30)] = 8.0
    provider_timeout_seconds: Annotated[float, Field(gt=0, le=10)] = 2.0
    max_request_bytes: Annotated[FeedbackLimit, Field(le=16384)] = 4096
    max_response_bytes: Annotated[FeedbackLimit, Field(le=262144)] = 65536

    @field_validator(
        "requests_per_minute",
        "max_subjects",
        "max_subject_in_flight",
        "max_global_in_flight",
        "ingress_requests_per_minute",
        "max_ingress_in_flight",
        "max_request_bytes",
        "max_response_bytes",
        mode="before",
    )
    @classmethod
    def environment_integer(cls, value: object) -> object:
        if isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 10:
            return int(value)
        return value

    @model_validator(mode="after")
    def consistent_limits(self) -> Self:
        if self.max_subject_in_flight > self.max_global_in_flight:
            raise ValueError("Subject concurrency cannot exceed global concurrency")
        if self.provider_timeout_seconds > self.request_timeout_seconds:
            raise ValueError("Provider deadline cannot exceed the request deadline")
        return self
