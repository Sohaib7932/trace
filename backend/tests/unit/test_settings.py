import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.settings import BACKEND_ROOT, Settings


def test_environment_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRACE_MAX_REQUEST_BYTES", "2048")
    monkeypatch.setenv("TRACE_CORS_ORIGINS", '["https://trace.example"]')
    settings = Settings(_env_file=None)
    assert settings.max_request_bytes == 2048
    assert settings.cors_origins == ("https://trace.example",)


@pytest.mark.parametrize(
    "values",
    [
        {"cors_origins": ("*",)},
        {"cors_origins": ("https://site.example/path",)},
        {"cors_origins": ("https://user:password@site.example",)},
        {"request_timeout_seconds": 0},
        {"database_timeout_seconds": -1},
        {"database_url": "not-a-url"},
        {"database_url": "postgresql://localhost/trace"},
        {"ai_provider": "gemini"},
        {"environment": "production"},
    ],
)
def test_invalid_configuration_fails_clearly(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, **values)
    assert caught.value.errors()[0]["loc"]


def test_relative_database_path_is_independent_of_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None)
    assert str(BACKEND_ROOT / "trace.db") in settings.database_url.get_secret_value()
    assert "trace.db" not in repr(settings)


def test_explicit_env_file_is_supported(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("TRACE_LOG_LEVEL=WARNING\n", encoding="utf-8")
    assert Settings(_env_file=env).log_level == "WARNING"


def test_sensitive_structured_logging_uses_allowlisted_fields() -> None:
    import logging

    from app.core.logging import JsonFormatter

    record = logging.LogRecord(
        "trace", logging.ERROR, "private/path", 1, "request_failed", (), None
    )
    record.request_id = "trace-test"
    record.password = "private-password"
    record.headers = {"authorization": "Bearer private-token"}
    record.exc_text = "database path and credentials"
    output = JsonFormatter().format(record)
    assert json.loads(output)["request_id"] == "trace-test"
    assert "private" not in output and "credentials" not in output
