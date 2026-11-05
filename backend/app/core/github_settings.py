"""Opt-in GitHub App configuration; social sign-in is a separate capability."""

import os
from collections.abc import MutableMapping
from pathlib import Path
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


_GITHUB_ENV_FILE = Path(__file__).resolve().parents[2] / ".env.github"
_GITHUB_ENV_PREFIX = "TRACE_GITHUB_APP_"


def load_github_env_file(
    environ: MutableMapping[str, str] | None = None, path: Path = _GITHUB_ENV_FILE
) -> tuple[str, ...]:
    """Local development only: load owner GitHub App values from an untracked file.

    Only ``TRACE_GITHUB_APP_*`` names are read, a variable already set in the real
    environment always wins, and values are never logged or returned (only the names
    that were added). Quoted values may span lines and use ``\n`` (for the private key).
    """
    target = os.environ if environ is None else environ
    before = set(target)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ()
    added: list[str] = []
    key_file = ""
    lines = iter(text.splitlines())
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        name = name.removeprefix("export ").strip()
        value = value.strip()
        if value[:1] in {'"', "'"}:
            quote = value[0]
            body = value[1:]
            while quote not in body:
                follow = next(lines, None)
                if follow is None:
                    break
                body += "\n" + follow
            value = body.split(quote, 1)[0]
            if quote == '"':
                value = value.replace("\\n", "\n")
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if name == _GITHUB_ENV_PREFIX + "PRIVATE_KEY_FILE":
            key_file = value
            continue
        if name == _GITHUB_ENV_PREFIX + "PRIVATE_KEY" and "\\n" in value and "\n" not in value:
            value = value.replace("\\n", "\n")
        if name.startswith(_GITHUB_ENV_PREFIX) and name not in target and value:
            target[name] = value
            added.append(name)
    # A path to the downloaded .pem file is easier than a multi-line value, and wins over a
    # PRIVATE_KEY line in this file (but never over a variable set in the real environment).
    key_name = _GITHUB_ENV_PREFIX + "PRIVATE_KEY"
    if key_file and key_name not in before:
        try:
            pem = Path(key_file).expanduser().read_text(encoding="utf-8").strip()
        except OSError:
            pem = ""
        if "PRIVATE KEY-----" in pem:
            target[key_name] = pem
            if key_name not in added:
                added.append(key_name)
    return tuple(added)
