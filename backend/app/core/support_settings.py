"""Protected support HTTP limits, reusing bounded account operations."""

from typing import Annotated

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from app.core.feedback_settings import FeedbackLimit
from app.core.tutor_settings import TutorSettings


class SupportSettings(TutorSettings):
    max_request_bytes: Annotated[FeedbackLimit, Field(le=16384)] = 4096
    model_config = SettingsConfigDict(
        env_prefix="TRACE_SUPPORT_",
        env_file=None,
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )
