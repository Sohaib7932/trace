"""Opt-in GitHub App configuration; social sign-in is a separate capability."""

from typing import Literal
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class GitHubSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRACE_GITHUB_APP_",
        env_file=None,
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        populate_by_name=True,
    )
    mode: Literal["disabled", "enabled"] = "disabled"
    app_id: int = Field(default=0, ge=0, validation_alias="TRACE_GITHUB_APP_ID")
    slug: str = Field(default="", pattern=r"^[a-z0-9-]{0,100}$")
    client_id: str = Field(default="", max_length=200)
    client_secret: SecretStr = Field(default=SecretStr(""), repr=False)
    private_key: SecretStr = Field(default=SecretStr(""), repr=False)
    state_signing_secret: SecretStr = Field(default=SecretStr(""), repr=False)
    token_encryption_key: SecretStr = Field(default=SecretStr(""), repr=False)
    callback_url: str = "http://localhost:3000/projects/github/callback"

    @model_validator(mode="after")
    def enabled_configuration(self) -> "GitHubSettings":
        parsed = urlsplit(self.callback_url)
        if (
            parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path != "/projects/github/callback"
            or not (
                parsed.scheme == "https"
                and parsed.hostname
                or parsed.scheme == "http"
                and parsed.hostname in {"localhost", "127.0.0.1"}
            )
        ):
            raise ValueError("Configure an exact secure application callback")
        if self.mode == "enabled" and not (
            self.app_id
            and self.slug
            and self.client_id
            and self.client_secret.get_secret_value()
            and self.private_key.get_secret_value()
            and len(self.state_signing_secret.get_secret_value()) >= 32
            and self.token_encryption_key.get_secret_value()
        ):
            raise ValueError("Enabled GitHub App requires private owner configuration")
        if self.token_encryption_key.get_secret_value():
            try:
                Fernet(self.token_encryption_key.get_secret_value().encode("ascii"))
            except Exception:
                raise ValueError("Configure a valid private GitHub token encryption key") from None
        return self
