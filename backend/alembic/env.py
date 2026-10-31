from alembic import context
from app.core.settings import Settings
from app.db import models  # noqa: F401 -- register mapped product tables for migration metadata
from app.db.base import Base
from app.db.session import Database

config = context.config
target_metadata = Base.metadata


def run_migrations() -> None:
    if context.is_offline_mode():
        context.configure(
            url=Settings().database_url.get_secret_value(),
            target_metadata=target_metadata,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
        )
        with context.begin_transaction():
            context.run_migrations()
        return
    supplied = config.attributes.get("connection")
    if supplied is not None:
        context.configure(
            connection=supplied, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()
        return
    database = Database(Settings())
    try:
        with database.engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        database.dispose()


run_migrations()
