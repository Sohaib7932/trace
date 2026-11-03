"""Explicit stable durable allowance scope; no automatic daily/reset policy."""

from typing import Literal, Self

from pydantic import StrictInt, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.ai.accounting import AllowancePolicy, Scope


class AccountingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRACE_ACCOUNTING_",
        env_file=None,
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )
    mode: Literal["memory", "durable"] = "memory"
    scope: Scope | None = None
    max_attempts: StrictInt = 20
    max_in_flight: StrictInt = 4
    max_subject_in_flight: StrictInt = 1
    requests_per_minute: StrictInt = 10

    @field_validator(
        "max_attempts",
        "max_in_flight",
        "max_subject_in_flight",
        "requests_per_minute",
        mode="before",
    )
    @classmethod
    def decimal_environment_limit(cls, value: object) -> object:
        if isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 10:
            return int(value)
        return value

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if self.mode == "durable" and self.scope is None:
            raise ValueError("Durable accounting requires an explicit stable operator scope")
        AllowancePolicy(
            scope=self.scope or "memory",
            max_attempts=self.max_attempts,
            max_in_flight=self.max_in_flight,
            max_subject_in_flight=self.max_subject_in_flight,
            requests_per_minute=self.requests_per_minute,
        )
        return self

    def policy(self) -> AllowancePolicy:
        if self.mode != "durable" or self.scope is None:
            raise ValueError("Durable policy is not configured")
        return AllowancePolicy(
            scope=self.scope,
            max_attempts=self.max_attempts,
            max_in_flight=self.max_in_flight,
            max_subject_in_flight=self.max_subject_in_flight,
            requests_per_minute=self.requests_per_minute,
        )
