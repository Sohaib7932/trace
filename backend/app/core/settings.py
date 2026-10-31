from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRACE_",
        env_file=BACKEND_ROOT / ".env",
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    environment: Literal["development", "test"] = "development"
    database_url: SecretStr = SecretStr("sqlite+pysqlite:///./trace.db")
    database_timeout_seconds: float = Field(default=3, gt=0, le=30)
    cors_origins: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    request_timeout_seconds: float = Field(default=30, gt=0, le=120)
    max_request_bytes: int = Field(default=65536, ge=1024, le=1048576)
    ai_provider: Literal["fake"] = "fake"
    cookie_secure: bool = True
    allow_insecure_local_cookies: bool = False
    credential_lifetime_seconds: int = Field(default=604800, ge=60, le=2592000)
    verification_timeout_seconds: float = Field(default=10, gt=0, le=30)

    @model_validator(mode="after")
    def validate_cookie_security(self) -> "Settings":
        if not self.cookie_secure and (
            not self.allow_insecure_local_cookies
            or any(
                urlsplit(origin).hostname not in {"localhost", "127.0.0.1", "::1"}
                for origin in self.cors_origins
            )
        ):
            raise ValueError(
                "Non-Secure cookies require explicit local-HTTP mode and loopback origins."
            )
        return self

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
        except ArgumentError:
            raise ValueError("Use a valid SQLAlchemy database URL.") from None
        if url.drivername != "sqlite+pysqlite":
            raise ValueError("Module 1 supports sqlite+pysqlite only; PostgreSQL is planned.")
        if url.database and url.database != ":memory:":
            path = Path(url.database)
            if not path.is_absolute():
                path = BACKEND_ROOT / path
            url = url.set(database=str(path.resolve()))
        return SecretStr(url.render_as_string(hide_password=False))

    @field_validator("cors_origins")
    @classmethod
    def validate_origins(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for origin in values:
            url = urlsplit(origin)
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username
                or url.password
                or url.path
                or url.query
                or url.fragment
                or "*" in origin
            ):
                raise ValueError("CORS origins must be explicit http(s) origins without paths.")
        return values
