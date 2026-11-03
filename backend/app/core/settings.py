from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
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

    database_url: SecretStr = SecretStr("sqlite+pysqlite:///./trace.db")
    database_timeout_seconds: float = Field(default=3, gt=0, le=30)
    database_schema: str = Field(default="public", pattern=r"^[a-z][a-z0-9_]{0,47}$")
    database_pool_size: int = Field(default=4, ge=1, le=32)
    database_max_overflow: int = Field(default=0, ge=0, le=16)
    database_pool_timeout_seconds: float = Field(default=3, gt=0, le=30)
    database_pool_recycle_seconds: int = Field(default=300, ge=30, le=3600)
    database_statement_timeout_seconds: float = Field(default=5, gt=0, le=30)
    database_lock_timeout_seconds: float = Field(default=3, gt=0, le=30)
    cors_origins: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    request_timeout_seconds: float = Field(default=30, gt=0, le=120)
    max_request_bytes: int = Field(default=65536, ge=1024, le=1048576)
    ai_provider: Literal["fake"] = "fake"
    cookie_secure: bool = True
    allow_insecure_local_cookies: bool = False
    credential_lifetime_seconds: int = Field(default=2592000, ge=60, le=2592000)
    verification_timeout_seconds: float = Field(default=10, gt=0, le=30)
    supabase_url: str = ""
    supabase_issuer: str = ""
    supabase_jwks_url: str = ""
    supabase_audience: str = "authenticated"
    auth_allow_insecure_loopback: bool = False
    auth_jwks_cache_seconds: int = Field(default=300, ge=1, le=600)
    # Last field so errors can name the environment after checking its profile.
    environment: Literal["development", "test", "production"] = "development"

    @field_validator("environment")
    @classmethod
    def production_security(
        cls, value: Literal["development", "test", "production"], info: ValidationInfo
    ) -> Literal["development", "test", "production"]:
        if value != "production" or "database_url" not in info.data:
            return value
        values = info.data
        url = make_url(values["database_url"].get_secret_value())
        if (
            url.drivername != "postgresql+psycopg"
            or not url.host
            or url.query.get("sslmode") != "verify-full"
            or values.get("database_schema") in {"public", "pg_catalog", "information_schema"}
            or str(values.get("database_schema", "")).startswith("pg_")
            or not values.get("cookie_secure")
            or values.get("allow_insecure_local_cookies")
            or values.get("auth_allow_insecure_loopback")
            or values.get("log_level") == "DEBUG"
            or not all(
                values.get(key) for key in ("supabase_url", "supabase_issuer", "supabase_jwks_url")
            )
            or not values.get("cors_origins")
            or any(urlsplit(origin).scheme != "https" for origin in values.get("cors_origins", ()))
            or any(
                urlsplit(origin).hostname in {"localhost", "127.0.0.1", "::1"}
                for origin in values.get("cors_origins", ())
            )
        ):
            raise ValueError(
                "Production requires private-schema TLS PostgreSQL, HTTPS auth/origins "
                "and secure settings."
            )
        return value

    @model_validator(mode="after")
    def validate_auth_config(self) -> "Settings":
        values = (self.supabase_url, self.supabase_issuer, self.supabase_jwks_url)
        if any(values):
            if not all(values) or not self.supabase_audience:
                raise ValueError("Set the complete Supabase URL, issuer, JWKS and audience config.")
            url = urlsplit(self.supabase_url)
            if (
                not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
                or url.path not in {"", "/"}
                or not (
                    url.scheme == "https"
                    or (
                        url.scheme == "http"
                        and self.auth_allow_insecure_loopback
                        and url.hostname in {"localhost", "127.0.0.1", "::1"}
                    )
                )
                or self.supabase_issuer != self.supabase_url.rstrip("/") + "/auth/v1"
                or self.supabase_jwks_url != self.supabase_issuer + "/.well-known/jwks.json"
            ):
                raise ValueError("Use the project's HTTPS Auth issuer and public JWKS endpoint.")
        return self

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
        if url.drivername not in {"sqlite+pysqlite", "postgresql+psycopg"}:
            raise ValueError("Use sqlite+pysqlite or postgresql+psycopg.")
        if url.drivername == "postgresql+psycopg" and (
            not url.host or not url.database or url.query.get("options") is not None
        ):
            raise ValueError(
                "PostgreSQL requires a host/database and settings-controlled connection options."
            )
        if url.drivername == "sqlite+pysqlite" and url.database and url.database != ":memory:":
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
