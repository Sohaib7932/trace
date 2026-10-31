"""Explicit Playwright-only bootstrap: a new migrated/seeded temporary DB per run."""

import json
import os
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from pydantic import SecretStr

from alembic import command
from app.core.settings import Settings
from app.db.learning import SqlLearningRepository
from app.db.migrations import migration_config
from app.db.session import Database
from app.domain.clock import as_utc, utc_now
from app.main import create_app
from app.services.catalog import seed_first_lesson, seed_transfer_lesson


def fixture_clock() -> datetime:
    # Test-bootstrap-only local file. No production setting or public time-control route.
    name = os.environ.get("TRACE_E2E_CLOCK_FILE")
    if name and Path(name).is_file():
        return as_utc(
            datetime.fromisoformat(json.loads(Path(name).read_text(encoding="utf-8"))["now"])
        )
    return utc_now()


def main() -> None:
    with TemporaryDirectory(prefix="trace-e2e-") as directory:
        settings = Settings(
            _env_file=None,
            environment="test",
            log_level="WARNING",
            database_url=SecretStr(f"sqlite+pysqlite:///{Path(directory) / 'learning.db'}"),
            cookie_secure=False,
            allow_insecure_local_cookies=True,
            cors_origins=("http://127.0.0.1:3100",),
            supabase_url="http://127.0.0.1:8001",
            supabase_issuer="http://127.0.0.1:8001/auth/v1",
            supabase_jwks_url="http://127.0.0.1:8001/auth/v1/.well-known/jwks.json",
            auth_allow_insecure_loopback=True,
        )
        database = Database(settings)
        try:
            config = migration_config()
            with database.engine.begin() as connection:
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
            seed_first_lesson(SqlLearningRepository(database))
            seed_transfer_lesson(SqlLearningRepository(database))
            uvicorn.run(
                create_app(settings, database, fixture_clock),
                host="127.0.0.1",
                port=8000,
                access_log=False,
                log_level="warning",
            )
        finally:
            database.dispose()


if __name__ == "__main__":
    main()
