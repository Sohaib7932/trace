from sqlalchemy import text
from sqlalchemy.engine import Connection

from alembic import context
from app.core.settings import Settings
from app.db import (
    accounting_models,  # noqa: F401 -- durable AI controls
    knowledge_models,  # noqa: F401 -- register additive archive metadata
    models,  # noqa: F401 -- register mapped product tables for migration metadata
)
from app.db.base import Base
from app.db.session import Database

config = context.config
target_metadata = Base.metadata


def configure(connection: Connection) -> None:
    dialect = config.get_main_option("trace_dialect", "sqlite")
    if connection.dialect.name != dialect:
        raise RuntimeError("Use the explicit Alembic configuration for this database dialect")
    if dialect == "postgresql":
        schema = connection.scalar(text("SELECT current_schema()"))
        if schema in {None, "pg_catalog", "information_schema"}:
            raise RuntimeError("Create the intended application schema before migrations")
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=dialect == "sqlite",
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


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
        configure(supplied)
        return
    database = Database(Settings())
    try:
        with database.engine.begin() as connection:
            configure(connection)
    finally:
        database.dispose()


run_migrations()
