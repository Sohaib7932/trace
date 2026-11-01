"""A real populated 0004 fixture, upgraded only through its supplied test connection."""

import json
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select, text

from alembic import command
from app.api.dependencies import get_notes_verifier
from app.auth.jwt import JwtVerifier
from app.core.settings import Settings
from app.db import models as m
from app.db.learning import SqlLearningRepository, SqlLearningStore, snapshot
from app.db.migrations import migration_config
from app.db.session import Database
from app.domain.learning import Credential, VerificationRun
from app.main import create_app
from app.services.catalog import seed_first_lesson, seed_transfer_lesson
from app.services.identity import COOKIE_NAME
from tests.auth_fixtures import KeysFixture, SigningFixture, auth_settings
from tests.conftest import migrate
from tests.integration.test_learning import attempt, post, predict, progress, start, verify
from tests.integration.test_transfer_retrieval import (
    MutableClock,
    finish_transfer,
    journey,
    mapping,
    start_transfer,
)
from tests.unit.test_legacy_baseline import LESSON_HASHES, QUESTION_HASHES

ACCOUNT_TABLES = {
    "users",
    "auth_subjects",
    "user_roles",
    "role_grant_events",
    "account_learners",
    "account_action_limits",
}
ACCOUNT_GUARDS = {
    "account_owner_exclusive",
    "account_credential_insert",
    "account_credential_update",
    "preserve_account_learners",
    "immutable_account_learners",
    "preserve_auth_subjects",
    "immutable_auth_subjects",
    "preserve_role_grant_events",
    "immutable_role_grant_events",
}


def records(connection, names):
    return {
        name: sorted(
            json.dumps(dict(row), sort_keys=True, default=str)
            for row in connection.execute(text(f'SELECT * FROM "{name}"')).mappings()
        )
        for name in names
    }


def schema(connection):
    return {
        (row.type, row.name): row.sql
        for row in connection.execute(
            text(
                "SELECT type,name,sql FROM sqlite_master "
                "WHERE type IN ('table','trigger','index') AND name NOT LIKE 'sqlite_%'"
            )
        )
    }


def assert_integrity(connection, revision):
    assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    assert connection.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == revision


def test_populated_0004_upgrade_preserves_history_constraints_and_account_claim(tmp_path):
    path = tmp_path / "populated-pre-0005.db"
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr(f"sqlite+pysqlite:///{path}"),
        cookie_secure=False,
        allow_insecure_local_cookies=True,
    )
    database = Database(settings)
    clock = MutableClock()
    try:
        migrate(database, "0004_transfer_retrieval")
        repository = SqlLearningRepository(database)
        seed_first_lesson(repository)
        seed_transfer_lesson(repository)
        app = create_app(settings, database, clock)

        def historical_credential(store, token_hash):
            row = store.session.scalar(
                select(m.LearnerCredential).where(
                    m.LearnerCredential.token_hash == token_hash,
                )
            )
            return snapshot(Credential, row) if row else None

        # Only the historical lookup differs: current ownership joins require 0005.
        # All actual HTTP validation, writes, readbacks and orchestration remain real.
        with TestClient(app) as client, TestClient(app) as second_guest:
            client.headers.update(
                {"Origin": "http://localhost:3000", "X-Trace-Client": "learning-web"}
            )
            with patch.object(SqlLearningStore, "credential", historical_credential):
                assert client.post("/api/v1/learners/anonymous", json={}).status_code == 200
                owner = client.get("/api/v1/learners/me").json()["learner_id"]
                raw_cookie = client.cookies.get(COOKIE_NAME)
                original = start(client)
                assert predict(client, original).status_code == 201
                wrong = attempt(client, original)
                assert verify(client, original, wrong["id"]).json()["status"] == "failed"
                assert (
                    post(
                        client, f"/sessions/{original}/hints", {"attempt_id": wrong["id"]}
                    ).status_code
                    == 201
                )
                correction = attempt(client, original, "content")

                class Interrupted:
                    def observe(self, run_id, field):
                        raise RuntimeError("Controlled pre-upgrade interruption")

                app.dependency_overrides[get_notes_verifier] = lambda: Interrupted()
                assert verify(client, original, correction["id"]).json()["status"] == "error"
                del app.dependency_overrides[get_notes_verifier]
                assert verify(client, original, correction["id"]).json()["status"] == "passed"
                transfer = start_transfer(client)
                assert predict(client, transfer).status_code == 201
                flat = mapping(client, transfer, "flat").json()
                assert verify(client, transfer, flat["id"]).json()["status"] == "failed"
                finish_transfer(client, transfer)
                clock.now += timedelta(days=1)
                checkpoints = journey(client)["checkpoints"]
                for selection in ["a", "b"]:
                    assert (
                        post(
                            client,
                            f"/retrievals/{checkpoints[0]['id']}/attempts",
                            {
                                "selection": selection,
                                "reasoning": "Keep my original response.",
                            },
                        ).status_code
                        == 201
                    )
                clock.now += timedelta(days=6)
                assert (
                    post(
                        client, f"/retrievals/{checkpoints[1]['id']}/attempts", {"selection": "c"}
                    ).status_code
                    == 201
                )
                # Preserve an unfinished session as well as completed/revised history.
                pending = start(client)
                assert predict(client, pending).status_code == 201
                pending_attempt = attempt(client, pending)
                with repository.write() as store:
                    store.add_run(
                        VerificationRun(
                            uuid4(),
                            UUID(pending),
                            UUID(pending_attempt["id"]),
                            "pending",
                            str(uuid4()),
                            clock(),
                        )
                    )
                second_guest.headers.update(client.headers)
                assert second_guest.post("/api/v1/learners/anonymous", json={}).status_code == 200
                separate = start(second_guest)
                assert predict(second_guest, separate).status_code == 201
                separate_progress = progress(second_guest, separate)
                before_progress = {
                    sid: progress(client, sid) for sid in [original, transfer, pending]
                }
                before_journey = journey(client)

            names = set(m.Base.metadata.tables) - ACCOUNT_TABLES
            config = migration_config()
            with database.engine.begin() as connection:
                assert_integrity(connection, "0004_transfer_retrieval")
                before = records(connection, names)
                old_schema = schema(connection)
                assert len([key for key in old_schema if key[0] == "trigger"]) == 33
                assert {
                    status
                    for (status,) in connection.execute(
                        text("SELECT DISTINCT status FROM verification_runs")
                    )
                } == {"passed", "failed", "error", "pending"}
                config.attributes["connection"] = connection
                with pytest.raises(RuntimeError, match="discard transfer history"):
                    command.downgrade(config, "0003_constraint_names")
                assert records(connection, names) == before
                command.upgrade(config, "0005_account_identity")
                command.check(config)
                assert_integrity(connection, "0005_account_identity")
                assert records(connection, names) == before
                upgraded = schema(connection)
                assert all(upgraded[key] == sql for key, sql in old_schema.items())
                assert {name for kind, name in upgraded if kind == "table"} == set(
                    m.Base.metadata.tables
                ) | {"alembic_version"}
                assert {name for kind, name in upgraded if kind == "trigger"} == {
                    name for kind, name in old_schema if kind == "trigger"
                } | ACCOUNT_GUARDS
                assert (
                    dict(
                        connection.execute(
                            text("SELECT lesson_id,content_hash FROM lesson_versions")
                        ).all()
                    )
                    == LESSON_HASHES
                )
                assert (
                    dict(
                        connection.execute(
                            text("SELECT question_id,question_hash FROM retrieval_checkpoints")
                        ).all()
                    )
                    == QUESTION_HASHES
                )
                assert all(
                    connection.scalar(text(f'SELECT COUNT(*) FROM "{table}"')) == 0
                    for table in ACCOUNT_TABLES
                )

            assert {sid: progress(client, sid) for sid in before_progress} == before_progress
            assert journey(client) == before_journey
            assert progress(second_guest, separate) == separate_progress
            signer = SigningFixture()
            config_auth = auth_settings(settings)
            app.state.settings = config_auth
            app.state.jwt_verifier = JwtVerifier(config_auth, KeysFixture(signer))
            client.headers["Authorization"] = "Bearer " + signer.token()
            claim_key = str(uuid4())
            claimed = post(client, "/account/claim-anonymous", {}, claim_key)
            assert claimed.status_code == 200 and claimed.json() == {
                "learner_id": owner,
                "claimed": True,
            }
            assert client.cookies.get(COOKIE_NAME) is None
            assert post(client, "/account/claim-anonymous", {}, claim_key).json() == claimed.json()
            assert {sid: progress(client, sid) for sid in before_progress} == before_progress
            assert journey(client) == before_journey
            assert progress(second_guest, separate) == separate_progress
            with database.engine.begin() as connection:
                assert records(connection, names - {"learner_credentials"}) == {
                    name: rows for name, rows in before.items() if name != "learner_credentials"
                }
                assert (
                    connection.scalar(text("SELECT learner_id FROM account_learners"))
                    == UUID(owner).hex
                )
                original_credentials = {
                    row["id"]: row for row in map(json.loads, before["learner_credentials"])
                }
                claimed_credentials = records(connection, {"learner_credentials"})
                for row in map(json.loads, claimed_credentials["learner_credentials"]):
                    previous = original_credentials[row["id"]]
                    if row["learner_id"] == UUID(owner).hex:
                        assert row["revoked_at"] is not None
                        assert {k: v for k, v in row.items() if k != "revoked_at"} == {
                            k: v for k, v in previous.items() if k != "revoked_at"
                        }
                    else:
                        assert row == previous
                after_claim = records(connection, set(m.Base.metadata.tables))
                config.attributes["connection"] = connection
                with pytest.raises(RuntimeError, match="downgrade refused"):
                    command.downgrade(config, "0004_transfer_retrieval")
                assert records(connection, set(m.Base.metadata.tables)) == after_claim
                assert_integrity(connection, "0005_account_identity")
            with TestClient(app) as old_guest:
                old_guest.cookies.set(COOKIE_NAME, raw_cookie)
                assert old_guest.get("/api/v1/learners/me").status_code == 401
    finally:
        database.dispose()
