"""Explicit Playwright-only bootstrap: a new migrated/seeded temporary DB per run."""

from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from pydantic import SecretStr

from alembic import command
from app.core.settings import Settings
from app.db.learning import SqlLearningRepository
from app.db.migrations import migration_config
from app.db.session import Database
from app.main import create_app
from app.services.catalog import seed_first_lesson


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
        )
        database = Database(settings)
        try:
            config = migration_config()
            with database.engine.begin() as connection:
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
            seed_first_lesson(SqlLearningRepository(database))
            uvicorn.run(
                create_app(settings, database),
                host="127.0.0.1",
                port=8000,
                access_log=False,
                log_level="warning",
            )
        finally:
            database.dispose()


if __name__ == "__main__":
    main()
