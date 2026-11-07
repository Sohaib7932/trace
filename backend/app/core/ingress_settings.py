"""Explicit staged workload ingress for Trace's existing production gateway."""

from typing import Literal, Self

from pydantic import Field, StrictInt, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.auth.workload_ingress import IngressConfig, IssuerMode


class IngressSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRACE_INGRESS_",
        env_file=None,
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )
    mode: Literal["disabled", "verify", "required"] = "disabled"
    issuer_mode: IssuerMode = "team"
    identity_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    jwks_cache_seconds: StrictInt = Field(default=300, ge=1, le=300)
    verification_timeout_seconds: float = Field(default=4.0, gt=0, le=4)

    @field_validator("identity_sha256", mode="before")
    @classmethod
    def empty_identity(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("jwks_cache_seconds", mode="before")
    @classmethod
    def decimal_environment_integer(cls, value: object) -> object:
        if isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 3:
            return int(value)
        return value

    @field_validator("verification_timeout_seconds", mode="before")
    @classmethod
    def no_boolean_deadline(cls, value: object) -> object:
        if type(value) is bool:
            raise ValueError("Ingress deadlines require numeric seconds")
        return value

    @model_validator(mode="after")
    def explicit_pinned_identity(self) -> Self:
        if self.mode != "disabled":
            self.verifier_config()
        return self

    def verifier_config(self) -> IngressConfig:
        if self.mode == "disabled":
            raise ValueError("Workload ingress is disabled")
        return IngressConfig(self.issuer_mode, self.identity_sha256 or "", self.jwks_cache_seconds)

    def validate_deployment(self, environment: str, render_edge_mode: str) -> None:
        if self.mode != "disabled" and (
            environment != "production" or render_edge_mode != "disabled"
        ):
            raise ValueError(
                "Workload ingress requires production with the Render edge profile disabled"
            )
