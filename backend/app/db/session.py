import math
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.pool.base import ConnectionPoolEntry

from app.core.settings import Settings


class Database:
    def __init__(self, settings: Settings) -> None:
        url = make_url(settings.database_url.get_secret_value())
        if url.get_backend_name() == "sqlite":
            self.engine = create_engine(
                url,
                echo=False,
                hide_parameters=True,
                connect_args={
                    "check_same_thread": False,
                    "autocommit": False,
                    "timeout": settings.database_timeout_seconds,
                },
                **({"poolclass": StaticPool} if url.database in {None, "", ":memory:"} else {}),
            )
            event.listen(self.engine, "connect", self._configure_sqlite)
        else:
            self.engine = create_engine(
                url,
                echo=False,
                hide_parameters=True,
                isolation_level="READ COMMITTED",
                pool_size=settings.database_pool_size,
                max_overflow=settings.database_max_overflow,
                pool_timeout=settings.database_pool_timeout_seconds,
                pool_recycle=settings.database_pool_recycle_seconds,
                pool_pre_ping=True,
                connect_args={
                    "connect_timeout": max(1, math.ceil(settings.database_timeout_seconds)),
                    "options": (
                        f"-c search_path={settings.database_schema},pg_catalog "
                        "-c statement_timeout="
                        f"{int(settings.database_statement_timeout_seconds * 1000)} "
                        f"-c lock_timeout={int(settings.database_lock_timeout_seconds * 1000)} "
                        "-c timezone=UTC"
                    ),
                    # Safe with transaction poolers; no session prepared-statement assumptions.
                    "prepare_threshold": None,
                },
            )
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    @staticmethod
    def _configure_sqlite(connection: sqlite3.Connection, _: ConnectionPoolEntry) -> None:
        # PRAGMA is ignored inside a transaction. Python 3.13 allows explicit control.
        original = connection.autocommit
        connection.autocommit = True
        try:
            connection.execute("PRAGMA foreign_keys=ON")
        finally:
            connection.autocommit = original

    @contextmanager
    def session(self) -> Iterator[Session]:
        # Closing rolls back uncommitted work. Services explicitly own session.begin().
        with self.sessions() as session:
            yield session

    def dispose(self) -> None:
        self.engine.dispose()

    @contextmanager
    def consistent_read(self) -> Iterator[Session]:
        """Short stable snapshot; never retain this context across provider I/O."""
        with self.sessions() as session:
            if self.engine.dialect.name == "postgresql":
                session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
                session.execute(text("SET TRANSACTION READ ONLY"))
            yield session
