"""Tutor admission settings reuse the verified bounded-operation infrastructure."""

from typing import Annotated

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from app.core.feedback_settings import FeedbackLimit, FeedbackSettings


class TutorSettings(FeedbackSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRACE_TUTOR_",
        env_file=None,
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )
    requests_per_minute: Annotated[FeedbackLimit, Field(le=60)] = 5
    max_global_in_flight: Annotated[FeedbackLimit, Field(le=32)] = 2
    request_timeout_seconds: Annotated[float, Field(gt=0, le=30)] = 30.0
    provider_timeout_seconds: Annotated[float, Field(gt=0, le=20)] = 20.0
    max_request_bytes: Annotated[FeedbackLimit, Field(le=16384)] = 16384
