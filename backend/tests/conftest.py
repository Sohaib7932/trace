from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import ForeignKey, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from alembic import command
from app.core.settings import Settings
from app.db.base import Base
from app.db.migrations import migration_config
from app.db.session import Database
from app.main import create_app


class FixtureBase(DeclarativeBase):
    metadata = MetaData(naming_convention=Base.metadata.naming_convention)


class Parent(FixtureBase):
    __tablename__ = "fixture_parent"
    id: Mapped[int] = mapped_column(primary_key=True)
    value: Mapped[str]


class Child(FixtureBase):
    __tablename__ = "fixture_child"
    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("fixture_parent.id"))


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    for key in list(os.environ):
        if key.startswith("TRACE_"):
            monkeypatch.delenv(key)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr(f"sqlite+pysqlite:///{tmp_path / 'test.db'}"),
    )


def migrate(database: Database, revision: str = "head") -> None:
    config = migration_config()
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)


@pytest.fixture
def database(settings: Settings) -> Iterator[Database]:
    resource = Database(settings)
    migrate(resource)
    yield resource
    resource.dispose()


@pytest.fixture
def app(settings: Settings, database: Database) -> FastAPI:
    return create_app(settings, database)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as connection:
        yield connection


@pytest.fixture
def learning_app(settings: Settings, database: Database) -> FastAPI:
    from app.db.learning import SqlLearningRepository
    from app.services.catalog import seed_first_lesson

    seed_first_lesson(SqlLearningRepository(database))
    config = settings.model_copy(
        update={"cookie_secure": False, "allow_insecure_local_cookies": True}
    )
    return create_app(config, database)


@pytest.fixture
def learner(learning_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(learning_app) as connection:
        connection.headers.update(
            {"Origin": "http://localhost:3000", "X-Trace-Client": "learning-web"}
        )
        assert connection.post("/api/v1/learners/anonymous", json={}).status_code == 200
        yield connection
