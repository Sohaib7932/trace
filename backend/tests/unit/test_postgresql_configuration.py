"""Configuration/lineage checks require neither a server nor real credentials."""

import hashlib
import runpy
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateIndex

from app.core.settings import Settings
from app.db.migrations import migration_config
from app.db.models import HintOperation
from app.db.session import Database


def production(**changes):
    values = dict(
        environment="production",
        database_url="postgresql+psycopg://trace:controlled-placeholder@db.example/trace?sslmode=verify-full",
        database_schema="trace",
        cors_origins=("https://trace.example",),
        supabase_url="https://project.supabase.co",
        supabase_issuer="https://project.supabase.co/auth/v1",
        supabase_jwks_url="https://project.supabase.co/auth/v1/.well-known/jwks.json",
    )
    return Settings(_env_file=None, **(values | changes))


def test_complete_production_profile_is_explicit_and_keeps_secret_hidden():
    settings = production()
    assert settings.environment == "production" and settings.database_max_overflow == 0
    assert "controlled-placeholder" not in repr(settings)


@pytest.mark.parametrize(
    "changes",
    [
        {"database_url": "sqlite+pysqlite:///:memory:"},
        {"database_url": "postgresql+psycopg://trace:placeholder@db.example/trace?sslmode=require"},
        {"database_schema": "public"},
        {"database_schema": "pg_catalog"},
        {"database_schema": "bad;drop schema public"},
        {"cookie_secure": False},
        {"allow_insecure_local_cookies": True},
        {"auth_allow_insecure_loopback": True},
        {"log_level": "DEBUG"},
        {"supabase_url": "", "supabase_issuer": "", "supabase_jwks_url": ""},
        {"cors_origins": ("http://trace.example",)},
        {"cors_origins": ("https://localhost",)},
        {"database_pool_size": 0},
        {"database_max_overflow": 17},
    ],
)
def test_production_fails_closed_for_unsafe_configuration(changes):
    with pytest.raises(ValidationError) as error:
        production(**changes)
    assert "controlled-placeholder" not in str(error.value)


def test_postgresql_engine_has_bounded_pool_without_opening_a_connection():
    database = Database(production())
    try:
        assert database.engine.pool.size() == 4
        assert database.engine.pool.checkedout() == 0
        assert database.engine.dialect.name == "postgresql"
    finally:
        database.dispose()


def test_each_lineage_loads_only_its_baseline_and_has_the_same_latest_head():
    local = ScriptDirectory.from_config(migration_config("sqlite"))
    hosted = ScriptDirectory.from_config(migration_config("postgresql"))
    assert local.get_heads() == hosted.get_heads()
    assert local.get_revision("0007_tutor_reservations").down_revision == "0006_candidate_lifecycle"
    assert hosted.get_revision("0007_tutor_reservations").down_revision is None


def test_all_seven_historical_migration_bytes_are_preserved():
    root = Path(__file__).resolve().parents[2] / "alembic"
    baseline = runpy.run_path(str(root / "postgresql_versions/pg_0007_baseline.py"))
    expected = baseline["HISTORICAL_SHA256"]
    assert len(expected) == 7
    for name, digest in expected.items():
        assert hashlib.sha256((root / "versions" / name).read_bytes()).hexdigest() == digest


def test_pending_hint_unique_index_is_partial_in_both_dialects():
    index = next(
        i for i in HintOperation.__table__.indexes if i.name == "uq_hint_operations_pending_session"
    )
    for dialect in (postgresql.dialect(), sqlite.dialect()):
        assert "WHERE status = 'pending'" in str(CreateIndex(index).compile(dialect=dialect))
