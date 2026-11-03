"""Operator-invoked migration job; never called automatically by a worker."""

import sys

from alembic import command
from app.core.settings import Settings
from app.db.migrations import migration_config
from app.db.session import Database


def main() -> int:
    database = None
    try:
        settings = Settings(_env_file=None)
        if settings.environment != "production":
            raise ValueError
        database = Database(settings)
        config = migration_config("postgresql")
        with database.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        print("Production migration completed; run readiness and acceptance checks.")
        return 0
    except Exception:
        # DB exceptions can contain credentials, schema names or SQL; never print them.
        print(
            "Production migration failed. Preserve the backup and inspect privately.",
            file=sys.stderr,
        )
        return 1
    finally:
        if database is not None:
            database.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
