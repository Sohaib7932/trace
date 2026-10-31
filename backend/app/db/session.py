import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.pool.base import ConnectionPoolEntry

from app.core.settings import Settings


class Database:
    def __init__(self, settings: Settings) -> None:
        url = make_url(settings.database_url.get_secret_value())
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
