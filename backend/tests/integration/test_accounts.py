import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError

from alembic import command
from app.auth.jwt import JwtVerifier
from app.db import models as m
from app.db.accounts import SqlAccountRepository, SqlAccountStore
from app.db.migrations import migration_config
from app.domain.learning import LearningError
from app.services.accounts import AccountService
from app.services.identity import COOKIE_NAME
from tests.auth_fixtures import KeysFixture, SigningFixture, auth_settings
from tests.integration.test_learning import post, progress, start
from tests.integration.test_transfer_retrieval import (
    clock as clock,
)
from tests.integration.test_transfer_retrieval import (
    complete_original,
    finish_transfer,
    journey,
)
from tests.integration.test_transfer_retrieval import (
    investigated as investigated,
)


@pytest.fixture
def auth(learning_app):
    signer, other = SigningFixture(), SigningFixture(kid="other")
    config = auth_settings(learning_app.state.settings)
    learning_app.state.settings = config
    learning_app.state.jwt_verifier = JwtVerifier(config, KeysFixture(signer, other))
    return signer, other


def authorize(client, signer):
    client.headers["Authorization"] = "Bearer " + signer.token(
        {"email": "same@example.test", "user_metadata": {"role": "admin", "roles": ["creator"]}}
    )


def account_service(database):
    return AccountService(SqlAccountRepository(database))


def test_bootstrap_roles_subject_mapping_and_no_email_merge(learner, auth, database):
    authorize(learner, auth[0])
    first = learner.get("/api/v1/account/me")
    assert first.status_code == 200 and first.headers["cache-control"] == "no-store"
    body = first.json()
    assert body["roles"] == ["learner"] and body["learner_id"] is None
    assert body["anonymous_history_available"] is True
    assert learner.get("/api/v1/account/me/learner").json() == {"learner_id": None}
    assert learner.get("/api/v1/account/me").json()["user_id"] == body["user_id"]
    authorize(learner, auth[1])
    second = learner.get("/api/v1/account/me").json()
    assert second["user_id"] != body["user_id"]
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(m.User)) == 2
        assert db.scalar(select(func.count()).select_from(m.AuthSubject)) == 2
        assert db.scalars(select(m.UserRole.role)).all() == ["learner", "learner"]
        assert db.scalar(select(func.count()).select_from(m.AccountLearner)) == 0
    assert "same@example.test" not in first.text


def test_concurrent_first_login_and_learner_creation_are_idempotent(auth, database):
    verifier = JwtVerifier(auth_settings(database_settings(database)), KeysFixture(auth[0]))
    identity = verifier.verify(auth[0].token())

    def bootstrap(_):
        service = account_service(database)
        user = service.bootstrap(identity)
        return user.id, service.learner(user)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(bootstrap, range(8)))
    assert len(set(results)) == 1
    with database.session() as db:
        for model in (m.User, m.AuthSubject, m.UserRole, m.AccountLearner, m.Learner):
            assert db.scalar(select(func.count()).select_from(model)) == 1


def database_settings(database):
    from app.core.settings import Settings

    return Settings(_env_file=None)


def learning_snapshot(database):
    names = (
        "learners",
        "lesson_versions",
        "learning_sessions",
        "predictions",
        "attempts",
        "tutor_interactions",
        "verification_runs",
        "verification_checks",
        "learning_events",
        "runtime_notes",
        "runtime_tasks",
        "retrieval_checkpoints",
        "retrieval_attempts",
    )
    with database.engine.connect() as connection:
        return {
            name: sorted(
                json.dumps(dict(row), default=str, sort_keys=True)
                for row in connection.execute(text(f"SELECT * FROM {name}")).mappings()
            )
            for name in names
        }


def test_populated_module_3_upgrade_claim_preserves_every_history_row(
    learner, auth, database, investigated, clock
):
    finish_transfer(learner, investigated)
    clock.now += timedelta(days=1)
    review = journey(learner)["checkpoints"][0]
    assert (
        post(
            learner,
            f"/retrievals/{review['id']}/attempts",
            {"selection": "b", "reasoning": "Follow the body schema at each JSON level."},
        ).status_code
        == 201
    )
    before = learning_snapshot(database)
    saved_progress = progress(learner, investigated)
    original_cookie = learner.cookies.get(COOKIE_NAME)
    config = migration_config()
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0004_transfer_retrieval")
        assert not connection.scalar(text("SELECT COUNT(*) FROM sqlite_master WHERE name='users'"))
        command.upgrade(config, "head")
        command.check(config)
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    assert learning_snapshot(database) == before
    assert progress(learner, investigated) == saved_progress
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(m.AccountLearner)) == 0
    authorize(learner, auth[0])
    key = str(uuid4())
    claimed = post(learner, "/account/claim-anonymous", {}, key)
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["claimed"] is True
    assert learner.cookies.get(COOKIE_NAME) is None
    assert learning_snapshot(database) == before
    assert progress(learner, investigated) == saved_progress
    assert post(learner, "/account/claim-anonymous", {}, key).json() == claimed.json()
    with database.session() as db:
        credentials = db.scalars(select(m.LearnerCredential)).all()
        assert credentials and all(row.revoked_at for row in credentials)
        assert db.scalar(select(m.AccountLearner.learner_id)) == UUID(claimed.json()["learner_id"])
    # Another device has no guest cookie and resumes solely through the verified subject.
    with TestClient(learner.app) as device:
        authorize(device, auth[0])
        assert device.get(f"/api/v1/sessions/{investigated}/progress").json() == saved_progress
    learner.headers.pop("Authorization")
    learner.cookies.set(COOKIE_NAME, original_cookie)
    assert learner.get("/api/v1/learners/me").status_code == 401
    authorize(learner, auth[1])
    assert post(learner, "/account/claim-anonymous", {}).status_code == 401
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        with pytest.raises(RuntimeError, match="downgrade refused"):
            command.downgrade(config, "0004_transfer_retrieval")
    assert learning_snapshot(database) == before


def test_new_authenticated_learner_without_cookie_can_learn_and_resume(learner, auth, database):
    learner.cookies.clear()
    authorize(learner, auth[0])
    first = learner.get("/api/v1/learners/me")
    assert first.status_code == 200
    assert "set-cookie" not in first.headers
    session = complete_original(learner)
    saved = progress(learner, session)
    assert learner.post("/api/v1/learners/anonymous", json={}).json() == first.json()
    with TestClient(learner.app) as device:
        authorize(device, auth[0])
        assert device.get(f"/api/v1/sessions/{session}/progress").json() == saved
        authorize(device, auth[1])
        assert device.get(f"/api/v1/sessions/{session}/progress").status_code == 404
    assert learner.post("/api/v1/learners/me/revoke", json={}).status_code == 409


@pytest.mark.parametrize("kind", ["missing", "invalid", "expired", "revoked"])
def test_claim_rejects_unusable_guest_credentials(learner, auth, database, kind):
    if kind == "missing":
        learner.cookies.clear()
    elif kind == "invalid":
        learner.cookies.clear()
        learner.cookies.set(COOKIE_NAME, "x" * 43)
    else:
        with database.session() as db, db.begin():
            values = (
                {"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
                if kind == "expired"
                else {"revoked_at": datetime.now(UTC)}
            )
            db.execute(update(m.LearnerCredential).values(**values))
    authorize(learner, auth[0])
    assert post(learner, "/account/claim-anonymous", {}).status_code == 401
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(m.AccountLearner)) == 0


def test_existing_account_history_conflict_leaves_both_histories_untouched(learner, auth, database):
    guest = start(learner)
    authorize(learner, auth[0])
    account = start(learner)
    before = learning_snapshot(database)
    response = post(learner, "/account/claim-anonymous", {})
    assert response.status_code == 409 and "Neither history" in response.text
    assert learning_snapshot(database) == before
    assert progress(learner, account)
    learner.headers.pop("Authorization")
    assert progress(learner, guest)


def test_claim_rollback_after_revocation_preserves_guest(learner, auth, database, monkeypatch):
    guest = start(learner)
    authorize(learner, auth[0])
    original = SqlAccountStore.claim

    def fail(self, *args):
        original(self, *args)
        raise OperationalError("private SQL", {}, RuntimeError("private"))

    monkeypatch.setattr(SqlAccountStore, "claim", fail)
    response = post(learner, "/account/claim-anonymous", {})
    assert response.status_code == 503 and "private" not in response.text
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(m.AccountLearner)) == 0
        assert db.scalar(select(m.LearnerCredential.revoked_at)) is None
    learner.headers.pop("Authorization")
    assert progress(learner, guest)


@pytest.mark.parametrize("same_user", [False, True])
def test_concurrent_claims_have_one_owner(learner, auth, database, same_user):
    raw = learner.cookies.get(COOKIE_NAME)
    verifier = learner.app.state.jwt_verifier
    users = [
        account_service(database).bootstrap(verifier.verify(signer.token()))
        for signer in (auth[0], auth[0] if same_user else auth[1])
    ]
    key = str(uuid4())

    def claim(user):
        try:
            return account_service(database).claim(user, raw, key)
        except LearningError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(claim, users))
    if same_user:
        assert result[0] == result[1] and isinstance(result[0], UUID)
    else:
        assert sum(isinstance(value, UUID) for value in result) == 1
        assert "unauthenticated" in result
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(m.AccountLearner)) == 1


def test_claim_and_role_api_validate_origin_body_and_ids(learner, auth):
    assert learner.get("/api/v1/account/me").status_code == 401
    authorize(learner, auth[0])
    for headers in [{"Origin": "https://evil.example"}, {"X-Trace-Client": "other"}]:
        assert (
            learner.post("/api/v1/account/claim-anonymous", json={}, headers=headers).status_code
            == 403
        )
    assert learner.post("/api/v1/account/claim-anonymous", json={}).status_code == 422
    for body in [{"learner_id": str(uuid4())}, {"role": "admin"}, {"credential": "private"}]:
        assert post(learner, "/account/claim-anonymous", body).status_code == 422
    assert learner.post("/api/v1/account/me", json={"role": "admin"}).status_code == 405
    assert learner.post("/api/v1/account/roles", json={"role": "admin"}).status_code == 404
    assert learner.get("/api/v1/account/me").json()["roles"] == ["learner"]
    response = learner.options(
        "/api/v1/account/me",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert (
        response.status_code == 200
        and "authorization" in response.headers["access-control-allow-headers"].lower()
    )


@pytest.mark.parametrize("header", ["Bearer forged", "Basic x", "Bearer ", "Bearer a b"])
def test_supplied_invalid_auth_never_downgrades_even_on_public_lesson(learner, auth, header):
    learner.headers["Authorization"] = header
    for path in ["/learners/me", "/account/me", "/lessons/fastapi-payload-mismatch"]:
        assert learner.get("/api/v1" + path).status_code == 401
    assert learner.post("/api/v1/learners/anonymous", json={}).status_code == 401


def test_bearer_tokens_and_provider_errors_never_logged(learner, auth):
    output = io.StringIO()
    learner.app.state.logger.handlers[0].setStream(output)
    token = auth[0].token()
    learner.headers["Authorization"] = "Bearer " + token
    assert learner.get("/api/v1/account/me").status_code == 200
    learner.headers["Authorization"] = "Bearer " + token + "forged"
    assert learner.get("/api/v1/account/me").status_code == 401
    assert token not in output.getvalue() and "Bearer" not in output.getvalue()


def test_operator_grants_roles_and_immutable_audit(learner, auth, database):
    authorize(learner, auth[0])
    user_id = UUID(learner.get("/api/v1/account/me").json()["user_id"])
    service = account_service(database)
    user = service.bootstrap(learner.app.state.jwt_verifier.verify(auth[0].token()))
    with pytest.raises(LearningError):
        user.require_role("creator")
    assert service.grant(user_id, "creator", "local-operator", "Approved creator access")
    assert not service.grant(user_id, "creator", "local-operator", "Already approved")
    assert service.grant(user_id, "admin", "local-operator", "Approved administrator")
    roles = learner.get("/api/v1/account/me").json()["roles"]
    assert roles == ["admin", "creator", "learner"]
    service.bootstrap(learner.app.state.jwt_verifier.verify(auth[0].token())).require_role("admin")
    with database.session() as db:
        assert len(db.scalars(select(m.RoleGrantEvent)).all()) == 2
    for statement in [
        update(m.RoleGrantEvent).values(reason="tamper"),
        m.RoleGrantEvent.__table__.delete(),
    ]:
        with pytest.raises(IntegrityError), database.session() as db, db.begin():
            db.execute(statement)
    for role, operator, reason in [
        ("learner", "op", "reason"),
        ("admin", "", "reason"),
        ("creator", "op", ""),
    ]:
        with pytest.raises(ValueError):
            service.grant(user_id, role, operator, reason)
    with pytest.raises(LearningError):
        service.grant(uuid4(), "creator", "op", "reason")


def test_disabled_account_and_subject_identity_cannot_be_reassigned(learner, auth, database):
    authorize(learner, auth[0])
    user = UUID(learner.get("/api/v1/account/me").json()["user_id"])
    with pytest.raises(IntegrityError), database.session() as db, db.begin():
        db.execute(update(m.AuthSubject).values(subject=str(uuid4())))
    with database.session() as db, db.begin():
        db.execute(update(m.User).where(m.User.id == user).values(status="disabled"))
    assert learner.get("/api/v1/account/me").status_code == 403


def test_account_claim_guards_and_database_failure(learner, auth, database):
    authorize(learner, auth[0])
    assert post(learner, "/account/claim-anonymous", {}).status_code == 200
    with database.session() as db:
        owner = db.scalar(select(m.AccountLearner))
        learner_id = owner.learner_id
    statements = [
        update(m.AccountLearner).values(claim_key=str(uuid4())),
        m.AccountLearner.__table__.delete(),
        update(m.LearnerCredential).values(revoked_at=None),
        update(m.LearnerCredential).values(expires_at=datetime.now(UTC)),
        m.LearnerCredential.__table__.insert().values(
            id=uuid4(),
            learner_id=learner_id,
            token_hash="f" * 64,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC),
        ),
    ]
    for statement in statements:
        with pytest.raises(IntegrityError), database.session() as db, db.begin():
            db.execute(statement)

    def unavailable(*_):
        raise OperationalError("private", {}, RuntimeError("private"))

    event.listen(database.engine, "before_cursor_execute", unavailable)
    try:
        response = learner.get("/api/v1/account/me")
        assert response.status_code == 503 and "private" not in response.text
    finally:
        event.remove(database.engine, "before_cursor_execute", unavailable)


def test_claim_rate_limit_counts_failed_claims_and_resets(learner, auth, database):
    from tests.auth_fixtures import AuthClock

    authorize(learner, auth[0])
    user = account_service(database).bootstrap(
        learner.app.state.jwt_verifier.verify(auth[0].token())
    )
    clock = AuthClock()
    service = AccountService(SqlAccountRepository(database), clock)
    for _ in range(30):
        with pytest.raises(LearningError) as error:
            service.claim(user, None, str(uuid4()))
        assert error.value.code == "unauthenticated"
    with pytest.raises(LearningError) as error:
        service.claim(user, None, str(uuid4()))
    assert error.value.code == "rate_limited"
    clock.advance(61)
    service.limit(user, "claim")
    service.limit(user, "inspect")
