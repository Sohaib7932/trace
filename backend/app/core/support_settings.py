"""Protected support HTTP limits, reusing bounded account operations."""

from pydantic_settings import SettingsConfigDict

from app.core.tutor_settings import TutorSettings


class SupportSettings(TutorSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRACE_SUPPORT_",
        env_file=None,
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )
