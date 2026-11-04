"""Limits for learner-requested (custom) lesson generation. Process variables only.

Public configuration, never credentials. Generation reuses the shared AI settings (mode,
model, credential variable, spend limits); these values only bound this feature.
"""

from typing import Annotated

from pydantic import Field, StrictInt, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.ai_settings import GEMINI_MAX_RESPONSE_SECONDS

type Limit = Annotated[StrictInt, Field(ge=1)]


class CustomLessonSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRACE_CUSTOM_LESSONS_",
        env_file=None,
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    enabled: bool = True
    # Per provider call. Separate from the tutor's 10 s limit; capped by the Gemini adapter.
    provider_timeout_seconds: Annotated[float, Field(gt=0, le=GEMINI_MAX_RESPONSE_SECONDS)] = (
        GEMINI_MAX_RESPONSE_SECONDS
    )
    requests_per_minute: Annotated[Limit, Field(le=30)] = 2
    daily_requests_per_account: Annotated[Limit, Field(le=100)] = 5
    # Live provider calls this feature may make per process (shared free-tier quota).
    max_live_calls_per_process: Annotated[Limit, Field(le=100)] = 15
    # A queued/generating job not updated for this long is marked failed (restart safety).
    stale_after_seconds: Annotated[Limit, Field(ge=60, le=3600)] = 600

    @field_validator(
        "requests_per_minute",
        "daily_requests_per_account",
        "max_live_calls_per_process",
        "stale_after_seconds",
        mode="before",
    )
    @classmethod
    def environment_integer(cls, value: object) -> object:
        if isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 6:
            return int(value)
        return value
