"""Fresh authorization reads use existing disposable SQL fixtures and no writes."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.accounts import SqlAccountRepository
from app.db.feedback_release import SqlFeedbackReleaseRepository
from app.db.learning import SqlLearningRepository
from app.domain.accounts import Account, Principal, VerifiedIdentity
from app.domain.learning import LearningError, LearningSession
from app.services.accounts import AccountService
from app.services.catalog import seed_first_lesson

NOW = datetime(2035, 1, 1, tzinfo=UTC)


def context(database, mode):
    learning = SqlLearningRepository(database)
    lesson = seed_first_lesson(learning)
    accounts = AccountService(SqlAccountRepository(database), lambda: NOW)
    credential = account = None
    token_hash = uuid4().hex + uuid4().hex
    if mode == "guest":
        with learning.write() as store:
            credential = store.create_identity(token_hash, NOW + timedelta(hours=1))
        learner_id = credential.learner_id
    else:
        account = accounts.bootstrap(
            VerifiedIdentity("https://auth.example.test", str(uuid4()), NOW + timedelta(hours=1))
        )
        learner_id = accounts.learner(account)
    session = LearningSession(
        uuid4(), learner_id, lesson.id, "awaiting_prediction", str(uuid4()), NOW, None
    )
    with learning.write() as store:
        store.add_session(session)
    return SimpleNamespace(
        principal=Principal(learner_id, NOW + timedelta(hours=1), account, credential),
        session=session,
        accounts=accounts,
        token_hash=token_hash,
        repository=SqlFeedbackReleaseRepository(database),
    )


@pytest.fixture(params=["guest", "account"])
def source(database, request):
    return context(database, request.param)


def read(source, at=NOW):
    with source.repository.read(source.principal, source.session.id, at) as observed:
        return observed.auth


def test_current_authorization_and_owned_records_share_one_read_only_scope(source, database):
    statements = []

    def capture(conn, cursor, statement, parameters, ctx, many):
        statements.append(statement)

    event.listen(database.engine, "before_cursor_execute", capture)
    try:
        with source.repository.read(source.principal, source.session.id, NOW) as observed:
            assert observed.session == source.session
            assert observed.lesson.id == source.session.lesson_version_id
            assert (
                observed.learning.owned_session(source.principal.learner_id, source.session.id)
                == source.session
            )
            assert observed.auth.observed_at == NOW
            assert observed.auth.principal_expires_at == source.principal.expires_at
            assert observed.auth.valid_until == source.principal.expires_at
            assert observed.auth.learner_id == source.principal.learner_id
            assert observed.auth.mode == ("account" if source.principal.account else "guest")
            assert len(observed.auth.identity_fingerprint) == 64
            assert source.token_hash not in observed.auth.model_dump_json()
    finally:
        event.remove(database.engine, "before_cursor_execute", capture)
    assert statements and all(
        statement.lstrip().upper().startswith("SELECT") for statement in statements
    )
    assert all("write_gate" not in statement.lower() for statement in statements)


@pytest.mark.parametrize(
    "kind", ["bare", "both", "expired", "exact_expiry", "naive", "wrong_id", "malformed"]
)
def test_invalid_principals_are_rejected_before_database_reads(source, database, kind):
    principal = source.principal
    if kind == "bare":
        principal = Principal(principal.learner_id, principal.expires_at)
    elif kind == "both":
        account = principal.account or Account(uuid4(), NOW, "active", ("learner",))
        with SqlLearningRepository(database).write() as store:
            credential = store.create_identity("b" * 64, NOW + timedelta(hours=1))
        principal = replace(principal, account=account, credential=credential)
    elif kind == "expired":
        principal = replace(principal, expires_at=NOW - timedelta(seconds=1))
    elif kind == "exact_expiry":
        principal = replace(principal, expires_at=NOW)
    elif kind == "naive":
        principal = replace(principal, expires_at=NOW.replace(tzinfo=None))
    elif kind == "wrong_id":
        principal = replace(principal, learner_id="not-a-server-uuid")
    else:
        principal = None
    statements = []

    def capture(conn, cursor, statement, parameters, ctx, many):
        statements.append(statement)

    event.listen(database.engine, "before_cursor_execute", capture)
    try:
        with (
            pytest.raises(LearningError) as error,
            source.repository.read(principal, source.session.id, NOW),
        ):
            pass
    finally:
        event.remove(database.engine, "before_cursor_execute", capture)
    assert error.value.code == "unauthenticated" and statements == []


def assert_rejected_before_sql(source, database, principal, session_id, now, expected):
    statements = []

    def capture(conn, cursor, statement, parameters, ctx, many):
        statements.append(statement)

    event.listen(database.engine, "before_cursor_execute", capture)
    try:
        with (
            pytest.raises(LearningError) as error,
            source.repository.read(principal, session_id, now),
        ):
            pytest.fail("Invalid authentication must not expose an authorized read scope")
    finally:
        event.remove(database.engine, "before_cursor_execute", capture)
    assert error.value.code == expected
    assert statements == []


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("lookalike", "unauthenticated"),
        ("account_id", "unauthenticated"),
        ("roles_container", "unauthenticated"),
        ("role_value", "unauthenticated"),
        ("disabled", "forbidden"),
        ("missing_learner", "forbidden"),
    ],
)
def test_malformed_or_ineligible_account_snapshots_fail_before_any_source_read(
    database, mutation, expected
):
    source = context(database, "account")
    account = source.principal.account
    if mutation == "lookalike":
        account = SimpleNamespace(**account.__dict__)
    elif mutation == "account_id":
        account = replace(account, id=str(account.id))
    elif mutation == "roles_container":
        account = replace(account, roles=["learner"])
    elif mutation == "role_value":
        account = replace(account, roles=("learner", 1))
    elif mutation == "disabled":
        account = replace(account, status="disabled")
    else:
        account = replace(account, roles=("creator",))
    principal = replace(source.principal, account=account)
    assert_rejected_before_sql(source, database, principal, source.session.id, NOW, expected)


@pytest.mark.parametrize(
    "mutation", ["lookalike", "credential_id", "owner", "revoked", "expired", "naive_expiry"]
)
def test_malformed_or_expired_guest_snapshots_cannot_reach_source_queries(database, mutation):
    source = context(database, "guest")
    credential = source.principal.credential
    if mutation == "lookalike":
        credential = SimpleNamespace(**credential.__dict__)
    elif mutation == "credential_id":
        credential = replace(credential, id=str(credential.id))
    elif mutation == "owner":
        credential = replace(credential, learner_id=uuid4())
    elif mutation == "revoked":
        credential = replace(credential, revoked_at=NOW)
    elif mutation == "expired":
        credential = replace(credential, expires_at=NOW)
    else:
        credential = replace(credential, expires_at=NOW.replace(tzinfo=None))
    principal = replace(source.principal, credential=credential)
    assert_rejected_before_sql(
        source, database, principal, source.session.id, NOW, "unauthenticated"
    )


@pytest.mark.parametrize("mutation", ["session_text", "naive_clock", "clock_text"])
def test_feedback_read_does_not_coerce_session_identity_or_authorization_clock(
    source, database, mutation
):
    session_id, now = source.session.id, NOW
    if mutation == "session_text":
        session_id = str(session_id)
    elif mutation == "naive_clock":
        now = NOW.replace(tzinfo=None)
    else:
        now = NOW.isoformat()
    assert_rejected_before_sql(
        source, database, source.principal, session_id, now, "unauthenticated"
    )


@pytest.mark.parametrize("kind", ["foreign", "missing"])
def test_foreign_and_missing_session_lookups_have_same_sanitized_result(source, database, kind):
    session_id = uuid4()
    if kind == "foreign":
        other = context(database, "guest")
        session_id = other.session.id
    with (
        pytest.raises(LearningError) as error,
        source.repository.read(source.principal, session_id, NOW),
    ):
        pass
    assert (error.value.code, str(error.value)) == ("not_found", "Session not found.")


@pytest.mark.parametrize("mutation", ["disabled", "role_removed", "created_at_changed", "missing"])
def test_account_storage_is_reread_instead_of_trusting_snapshot(database, monkeypatch, mutation):
    source = context(database, "account")
    user_id = source.principal.account.id
    with database.session() as session, session.begin():
        if mutation == "disabled":
            session.execute(update(m.User).where(m.User.id == user_id).values(status="disabled"))
        elif mutation == "role_removed":
            session.execute(delete(m.UserRole).where(m.UserRole.user_id == user_id))
        elif mutation == "created_at_changed":
            session.execute(
                update(m.User)
                .where(m.User.id == user_id)
                .values(created_at=NOW + timedelta(seconds=1))
            )
    if mutation == "missing":
        original = Session.get

        def missing(session, entity, *args, **kwargs):
            return None if entity is m.User else original(session, entity, *args, **kwargs)

        monkeypatch.setattr(Session, "get", missing)
    with pytest.raises(LearningError) as error:
        read(source)
    assert error.value.code == (
        "forbidden" if mutation in {"disabled", "role_removed"} else "unauthenticated"
    )


def test_account_identity_fingerprint_ignores_activity_metadata_and_binds_subjects(database):
    source = context(database, "account")
    original = read(source)
    user_id = source.principal.account.id
    with database.session() as session, session.begin():
        session.execute(
            update(m.User).where(m.User.id == user_id).values(updated_at=NOW + timedelta(seconds=1))
        )
        session.execute(
            update(m.AuthSubject)
            .where(m.AuthSubject.user_id == user_id)
            .values(last_seen_at=NOW + timedelta(seconds=1))
        )
    assert (
        read(source, NOW + timedelta(seconds=1)).identity_fingerprint
        == original.identity_fingerprint
    )
    with database.session() as session, session.begin():
        session.add(
            m.AuthSubject(
                issuer="https://another-auth.example.test",
                subject=str(uuid4()),
                user_id=user_id,
                created_at=NOW + timedelta(seconds=2),
                last_seen_at=NOW + timedelta(seconds=2),
            )
        )
    assert (
        read(source, NOW + timedelta(seconds=2)).identity_fingerprint
        != original.identity_fingerprint
    )


@pytest.mark.parametrize("kind", ["missing", "changed"])
def test_missing_or_changed_account_mapping_cannot_use_a_previous_principal(
    database, monkeypatch, kind
):
    source = context(database, "account")
    original = Session.get

    def changed(session, entity, *args, **kwargs):
        if entity is m.AccountLearner:
            return None if kind == "missing" else SimpleNamespace(learner_id=uuid4())
        return original(session, entity, *args, **kwargs)

    monkeypatch.setattr(Session, "get", changed)
    with pytest.raises(LearningError) as error:
        read(source)
    assert error.value.code == "unauthenticated"


def test_missing_immutable_subject_binding_cannot_authorize_account(database, monkeypatch):
    source = context(database, "account")
    original = Session.scalars

    def missing(session, statement, *args, **kwargs):
        if statement.column_descriptions[0].get("entity") is m.AuthSubject:
            return iter(())
        return original(session, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "scalars", missing)
    with pytest.raises(LearningError) as error:
        read(source)
    assert error.value.code == "unauthenticated"


@pytest.mark.parametrize("kind", ["missing", "revoked", "expired", "claimed", "owner_changed"])
def test_guest_storage_is_current_and_claimed_history_cannot_be_read_as_guest(database, kind):
    source = context(database, "guest")
    credential = source.principal.credential
    if kind == "claimed":
        account = source.accounts.bootstrap(
            VerifiedIdentity("https://auth.example.test", str(uuid4()), NOW + timedelta(hours=1))
        )
        with source.accounts.repository.write() as store:
            store.claim(account.id, credential, str(uuid4()), NOW)
    else:
        with database.session() as session, session.begin():
            if kind == "missing":
                session.execute(
                    delete(m.LearnerCredential).where(m.LearnerCredential.id == credential.id)
                )
            elif kind == "revoked":
                session.execute(
                    update(m.LearnerCredential)
                    .where(m.LearnerCredential.id == credential.id)
                    .values(revoked_at=NOW)
                )
            elif kind == "expired":
                session.execute(
                    update(m.LearnerCredential)
                    .where(m.LearnerCredential.id == credential.id)
                    .values(expires_at=NOW)
                )
            else:
                another = m.Learner(created_at=NOW)
                session.add(another)
                session.flush()
                session.execute(
                    update(m.LearnerCredential)
                    .where(m.LearnerCredential.id == credential.id)
                    .values(learner_id=another.id)
                )
    with pytest.raises(LearningError) as error:
        read(source)
    assert error.value.code == "unauthenticated"


def test_guest_fingerprint_binds_exact_token_identity_but_not_harmless_renewal(database):
    source = context(database, "guest")
    original = read(source)
    credential_id = source.principal.credential.id
    with database.session() as session, session.begin():
        session.execute(
            update(m.LearnerCredential)
            .where(m.LearnerCredential.id == credential_id)
            .values(expires_at=NOW + timedelta(hours=2))
        )
    assert read(source).identity_fingerprint == original.identity_fingerprint
    with database.session() as session, session.begin():
        session.execute(
            update(m.LearnerCredential)
            .where(m.LearnerCredential.id == credential_id)
            .values(token_hash="c" * 64)
        )
    assert read(source).identity_fingerprint != original.identity_fingerprint


def test_fresh_guest_deadline_honors_shorter_storage_expiry_without_changing_identity(database):
    source = context(database, "guest")
    original = read(source)
    expires_at = NOW + timedelta(seconds=5)
    with database.session() as session, session.begin():
        session.execute(
            update(m.LearnerCredential)
            .where(m.LearnerCredential.id == source.principal.credential.id)
            .values(expires_at=expires_at)
        )
    current = read(source, NOW + timedelta(seconds=1))
    assert current.valid_until == expires_at < original.valid_until
    assert current.identity() == original.identity()


def test_claimed_history_is_denied_even_if_a_guest_snapshot_appears_unrevoked(
    database, monkeypatch
):
    source = context(database, "guest")
    credential = source.principal.credential
    account = source.accounts.bootstrap(
        VerifiedIdentity("https://auth.example.test", str(uuid4()), NOW + timedelta(hours=1))
    )
    with source.accounts.repository.write() as store:
        store.claim(account.id, credential, str(uuid4()), NOW)
    original = Session.get

    def unrevoked(session, entity, *args, **kwargs):
        current = original(session, entity, *args, **kwargs)
        if entity is m.LearnerCredential and current is not None:
            return SimpleNamespace(
                learner_id=current.learner_id, revoked_at=None, expires_at=current.expires_at
            )
        return current

    # No historical rows/triggers are rewritten to manufacture this corrupt read.
    monkeypatch.setattr(Session, "get", unrevoked)
    with pytest.raises(LearningError) as error:
        read(source)
    assert error.value.code == "unauthenticated"


def test_authentication_failure_precedes_even_a_missing_session(source):
    principal = replace(source.principal, expires_at=NOW)
    with pytest.raises(LearningError) as error, source.repository.read(principal, uuid4(), NOW):
        pass
    assert error.value.code == "unauthenticated"


def test_storage_errors_are_sanitized_and_read_scope_closes(source, database):
    def unavailable(*_):
        raise OperationalError("PRIVATE_AUTH_DATABASE", {}, RuntimeError("PRIVATE_AUTH_DATABASE"))

    event.listen(database.engine, "before_cursor_execute", unavailable)
    try:
        with pytest.raises(LearningError) as error:
            read(source)
    finally:
        event.remove(database.engine, "before_cursor_execute", unavailable)
    assert error.value.code == "dependency_unavailable"
    assert "PRIVATE_AUTH_DATABASE" not in str(error.value)
    # A fresh scope is usable and never retains a failed read transaction.
    assert read(source).learner_id == source.principal.learner_id
