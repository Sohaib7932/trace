"""Explicit Render edge policy: scheme interpretation is not peer authentication."""

import re
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_HOSTNAME = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.onrender\.com\Z")
_SERVICE_ID = re.compile(r"srv-[a-z0-9][a-z0-9-]{0,99}\Z")


class RenderEdgeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRACE_RENDER_EDGE_",
        env_file=None,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        hide_input_in_errors=True,
    )
    mode: Literal["disabled", "enabled"] = "disabled"
    hostname: str = Field(default="", max_length=253)
    trusted_private_perimeter_confirmed: bool = False
    render: str = Field(default="", validation_alias="RENDER")
    render_service_type: str = Field(default="", validation_alias="RENDER_SERVICE_TYPE")
    render_service_id: str = Field(default="", validation_alias="RENDER_SERVICE_ID")
    render_external_hostname: str = Field(default="", validation_alias="RENDER_EXTERNAL_HOSTNAME")

    @model_validator(mode="after")
    def require_explicit_perimeter(self) -> Self:
        if self.mode == "enabled" and (
            not self.trusted_private_perimeter_confirmed
            or self.render != "true"
            or self.render_service_type != "web"
            or not _SERVICE_ID.fullmatch(self.render_service_id)
            or not _HOSTNAME.fullmatch(self.hostname)
            or self.hostname != self.render_external_hostname
        ):
            raise ValueError(
                "Render edge mode requires pinned Render web metadata "
                "and explicit perimeter confirmation"
            )
        return self

    def validate_environment(self, environment: str) -> None:
        if self.mode == "enabled" and environment != "production":
            raise ValueError("Render edge mode is production-only")
