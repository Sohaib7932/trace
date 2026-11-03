"""Opt-in PostgreSQL suite. Refuses non-disposable or non-loopback targets."""

import os
import re
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from alembic import command
from app.core.ai_settings import AIClientSettings
from app.core.settings import Settings
from app.db.learning import SqlLearningRepository
from app.db.migrations import migration_config
from app.db.session import Database
from app.main import create_app
from app.services.catalog import seed_first_lesson
from tests.integration.test_accounts import auth as auth
from tests.integration.test_transfer_retrieval import clock as clock
from tests.integration.test_transfer_retrieval import investigated as investigated


@pytest.fixture(autouse=True)
def isolated_process_configuration(monkeypatch):
    for name in tuple(os.environ):
        if name.startswith("TRACE_") and name != "TRACE_TEST_POSTGRES_URL":
            monkeypatch.delenv(name, raising=False)


@pytest.fixture
def settings():
    raw = os.environ.get("TRACE_TEST_POSTGRES_URL", "")
    if not raw:
        pytest.fail("Set TRACE_TEST_POSTGRES_URL for this explicit disposable PostgreSQL suite")
    url = make_url(raw)
    if (
        url.drivername != "postgresql+psycopg"
        or url.host not in {"127.0.0.1", "localhost"}
        or url.username != "trace_test"
        or url.database != "trace_test"
    ):
        pytest.fail("PostgreSQL tests require the documented loopback trace_test database/user")
    schema = "trace_test_" + uuid4().hex
    admin = create_engine(url, hide_parameters=True)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        yield Settings(
            _env_file=None,
            environment="test",
            database_url=SecretStr(raw),
            database_schema=schema,
            cookie_secure=False,
            allow_insecure_local_cookies=True,
        )
    finally:
        if not re.fullmatch(r"trace_test_[0-9a-f]{32}", schema):
            raise RuntimeError("Refusing unsafe disposable-schema cleanup")
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def database(settings):
    database = Database(settings)
    config = migration_config("postgresql")
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    try:
        yield database
    finally:
        database.dispose()


@pytest.fixture
def learning_app(settings, database):
    seed_first_lesson(SqlLearningRepository(database))
    return create_app(
        settings, database, ai_settings=AIClientSettings(_env_file=None, mode="disabled")
    )


@pytest.fixture
def learner(learning_app):
    with TestClient(learning_app) as client:
        client.headers.update({"Origin": "http://localhost:3000", "X-Trace-Client": "learning-web"})
        assert client.post("/api/v1/learners/anonymous", json={}).status_code == 200
        yield client
