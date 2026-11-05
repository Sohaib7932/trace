"""Leaderboard projection from real isolated verification and account histories."""

import base64
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event, select, text, update
from sqlalchemy.exc import OperationalError

from app.ai.providers.fake import FakeTutorProvider
from app.api.dependencies import get_account_service, get_notes_verifier
from app.auth.jwt import JwtVerifier
from app.db import models as m
from app.db.accounts import SqlAccountRepository
from app.db.learning import SqlLearningRepository
from app.services.accounts import AccountService
from app.services.catalog import LESSON_ID, seed_first_lesson, seed_transfer_lesson
from app.services.leaderboard import board_identifier
from app.services.learning import LearningService
from app.services.verification import VerificationService
from app.verification.asgi_notes import AsgiNotesVerifier
from tests.auth_fixtures import KeysFixture, SigningFixture, auth_settings
from tests.integration.test_custom_lessons import ready_lesson
from tests.integration.test_learning import attempt, post, predict, start, verify
from tests.integration.test_live_ai_http import api as api  # noqa: F401
from tests.integration.test_phase0_verification import PauseFirstObservation
from tests.integration.test_transfer_retrieval import (
    complete_original,
    finish_transfer,
    mapping,
    start_transfer,
)

URL = "/api/v1/leaderboard"


@pytest.fixture
def board(learner, learning_app):
    signer = SigningFixture()
    config = auth_settings(learning_app.state.settings)
    learning_app.state.settings = config
    learning_app.state.jwt_verifier = JwtVerifier(config, KeysFixture(signer))

    def sign_in(subject=None):
        subject = subject or str(uuid4())
        learner.headers["Authorization"] = "Bearer " + signer.token(
            {
                "sub": subject,
                "email": "private-account@example.test",
                "user_metadata": {"display_name": "Private provider name", "avatar_id": "secret"},
            }
        )
        response = learner.get("/api/v1/account/me")
        assert response.status_code == 200, response.text
        return subject, UUID(response.json()["user_id"])

    return learner, sign_in


def read(client, **params):
    response = client.get(URL, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def complete_both(client, database):
    complete_original(client)
    seed_transfer_lesson(SqlLearningRepository(database))
    session = start_transfer(client)
    assert predict(client, session).status_code == 201
    flat = mapping(client, session, "flat").json()
    assert verify(client, session, flat["id"]).json()["status"] == "failed"
    finish_transfer(client, session)


def test_global_ranking_distinct_problems_ties_and_private_projection(board, database):
    client, sign_in = board
    people = []
    for score in (2, 1, 2, 0):
        person = sign_in()
        people.append((person, score))
        if score == 2:
            complete_both(client, database)
        elif score == 1:
            complete_original(client)
    response = client.get(URL)
    body = response.json()
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, max-age=60"
    assert "Authorization" in response.headers["vary"]
    expected = sorted(((-score, account) for (_, account), score in people if score))
    assert [(e["user_id"], e["verified_count"]) for e in body["entries"]] == [
        (board_identifier(account), -negative) for negative, account in expected
    ]
    assert [e["rank"] for e in body["entries"]] == [1, 1, 3]
    assert body["me"] is None and body["next_cursor"] is None
    for entry in body["entries"]:
        assert set(entry) == {
            "rank",
            "user_id",
            "display_name",
            "avatar_id",
            "avatar_url",
            "verified_count",
            "is_me",
        }
        assert entry["display_name"] is entry["avatar_id"] is entry["avatar_url"] is None
        assert entry["is_me"] is False
        assert len(entry["user_id"]) == 64
    assert "private-account@example.test" not in response.text
    assert "Private provider name" not in response.text
    with database.session() as db:
        for model in (m.User, m.Learner, m.AuthSubject):
            for row in db.scalars(select(model)):
                assert str(row.id) not in response.text and row.id.hex not in response.text
        for subject in db.scalars(select(m.AuthSubject.subject)):
            assert subject not in response.text


def test_repeated_sessions_versions_and_verification_replays_count_once(board, database):
    client, sign_in = board
    sign_in()
    session = complete_original(client)
    runs = client.get(f"/api/v1/sessions/{session}/verifications").json()
    assert verify(client, session, runs[0]["attempt_id"]).json()["status"] == "passed"
    complete_original(client)
    repository = SqlLearningRepository(database)
    original = seed_first_lesson(repository)
    with repository.write() as store:
        store.publish(replace(original, id=uuid4(), version="1.1.0"))
    created = post(client, "/sessions", {"lesson_id": LESSON_ID, "version": "1.1.0"})
    version_session = created.json()["id"]
    assert predict(client, version_session).status_code == 201
    corrected = attempt(client, version_session, "content")
    assert verify(client, version_session, corrected["id"]).json()["status"] == "passed"
    body = read(client)
    assert body["entries"][0]["verified_count"] == 1
    assert body["entries"][0]["is_me"] is True
    assert body["me"] == {"rank": 1, "verified_count": 1}


@pytest.mark.parametrize("phase", ["draft", "prediction", "attempt", "failed", "error"])
def test_unfinished_and_unverified_work_does_not_count(board, learning_app, phase):
    client, sign_in = board
    sign_in()
    session = start(client)
    if phase != "draft":
        assert predict(client, session).status_code == 201
    if phase not in {"draft", "prediction"}:
        change = attempt(client, session)
        if phase == "error":

            class UnavailableVerifier:
                def observe(self, run_id, field):
                    raise RuntimeError("private dependency diagnostics")

            learning_app.dependency_overrides[get_notes_verifier] = UnavailableVerifier
        if phase in {"failed", "error"}:
            assert verify(client, session, change["id"]).json()["status"] == phase
    assert read(client)["entries"] == []
    assert read(client)["me"] is None


def test_pending_and_late_passed_abandoned_session_are_excluded(board, database):
    client, sign_in = board
    sign_in()
    session = start(client)
    predict(client, session)
    change = attempt(client, session, "content")
    owner = UUID(client.get("/api/v1/learners/me").json()["learner_id"])
    repository = SqlLearningRepository(database)
    gate = PauseFirstObservation(AsgiNotesVerifier(repository, 2))
    service = VerificationService(repository, gate, 2)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            service.verify, owner, UUID(session), UUID(change["id"]), str(uuid4())
        )
        try:
            assert gate.entered.wait(10)
            assert read(client)["entries"] == []
            LearningService(repository, FakeTutorProvider()).abandon(owner, UUID(session))
        finally:
            gate.release.set()
        assert pending.result(timeout=10).status == "passed"
    assert read(client)["entries"] == []


def test_zero_accounts_empty_board_and_inspection_preserves_guest_claim(board, database):
    client, sign_in = board
    # Real guest history is excluded until its existing learner is explicitly claimed.
    complete_original(client)
    _, account = sign_in()
    body = read(client)
    assert body["entries"] == [] and body["me"] is None and body["next_cursor"] is None
    with database.session() as db:
        assert db.get(m.AccountLearner, account) is None
    assert post(client, "/account/claim-anonymous", {}).status_code == 200
    claimed = read(client)
    assert len(claimed["entries"]) == 1
    assert claimed["entries"][0]["user_id"] == board_identifier(account)
    assert claimed["entries"][0]["verified_count"] == 1
    assert read(client)["entries"] == claimed["entries"]


def test_pagination_stable_tie_order_global_ranks_and_off_page_me(board, database):
    client, sign_in = board
    people = []
    for score in (2, 2, 1, 1, 1):
        people.append(sign_in())
        complete_both(client, database) if score == 2 else complete_original(client)
    expected = read(client)["entries"]
    viewer = max(
        account
        for _, account in people
        if board_identifier(account) in {entry["user_id"] for entry in expected[2:]}
    )
    subject = next(subject for subject, account in people if account == viewer)
    sign_in(subject)
    first = read(client, limit=2)
    assert first["me"] == {"rank": 3, "verified_count": 1}
    assert not any(row["is_me"] for row in first["entries"])
    assert first["next_cursor"]
    entries, page = first["entries"], first
    while page["next_cursor"]:
        page = read(client, cursor=page["next_cursor"], limit=2)
        assert page["generated_at"] == first["generated_at"]
        entries.extend(page["entries"])
    assert len({entry["user_id"] for entry in entries}) == 5
    assert [entry["user_id"] for entry in entries] == [entry["user_id"] for entry in expected]
    assert [entry["rank"] for entry in entries] == [1, 1, 3, 3, 3]
    assert sum(entry["is_me"] for entry in entries) == 1


def test_cursor_freezes_later_completions_registrations_and_history_claims(board, learning_app):
    client, sign_in = board
    first_person = sign_in()
    complete_original(client)
    second_person = sign_in()
    # This account exists at the cutoff but its first completion happens afterward.
    third_person = sign_in()
    complete_original(client)
    original = read(client, limit=1)
    cutoff = datetime.fromisoformat(original["generated_at"].replace("Z", "+00:00"))
    learning_app.state.clock = lambda: cutoff + timedelta(seconds=10)
    sign_in(second_person[0])
    complete_original(client)
    sign_in()
    complete_original(client)
    continued = read(client, cursor=original["next_cursor"], limit=50)
    assert continued["generated_at"] == original["generated_at"]
    assert continued["me"] is None  # new registration/completion cannot enter an old snapshot
    original_ids = {board_identifier(first_person[1]), board_identifier(third_person[1])}
    assert {original["entries"][0]["user_id"], continued["entries"][0]["user_id"]} == original_ids
    assert len(continued["entries"]) == 1 and continued["next_cursor"] is None
    assert len(read(client)["entries"]) == 4


def test_disabled_and_non_learner_accounts_are_not_exposed(board, database):
    client, sign_in = board
    disabled = sign_in()
    complete_original(client)
    disabled_token = client.headers["Authorization"]
    no_role = sign_in()
    complete_original(client)
    with database.session() as db, db.begin():
        db.execute(update(m.User).where(m.User.id == disabled[1]).values(status="disabled"))
        db.execute(delete(m.UserRole).where(m.UserRole.user_id == no_role[1]))
    assert client.get(URL).status_code == 403
    sign_in()
    assert read(client)["entries"] == []
    # Supplied disabled-account credentials fail closed, rather than becoming guest access.
    client.headers["Authorization"] = disabled_token
    assert client.get(URL).status_code == 403


@pytest.mark.parametrize("authorization", [None, "Bearer invalid", "Basic invalid"])
def test_missing_invalid_or_guest_only_authentication_rejected(board, authorization):
    client, _ = board
    if authorization is not None:
        client.headers["Authorization"] = authorization
    response = client.get(URL)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


@pytest.mark.parametrize("limit", ["0", "51", "-1", "abc"])
def test_invalid_page_sizes_use_standard_errors(board, limit):
    client, sign_in = board
    sign_in()
    response = client.get(URL, params={"limit": limit})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def encoded(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()


@pytest.mark.parametrize(
    "cursor",
    [
        "!",
        "",
        "a",
        encoded([]),
        encoded({}),
        encoded({"as_of": "2026-01-01T00:00:00", "offset": 0}),
        encoded({"as_of": "9999-01-01T00:00:00Z", "offset": 0}),
        encoded({"as_of": "2026-01-01T00:00:00Z", "offset": -1}),
        encoded({"as_of": "2026-01-01T00:00:00Z", "offset": True}),
        encoded({"as_of": "2026-01-01T00:00:00Z", "offset": 1_000_000_001}),
        encoded({"as_of": "2026-01-01T00:00:00Z", "offset": 0, "user_id": "private"}),
    ],
)
def test_invalid_cursor_is_rejected_without_echoing_input(board, cursor):
    client, sign_in = board
    sign_in()
    response = client.get(URL, params={"cursor": cursor})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "private" not in response.text


def test_account_rate_limit_and_database_failure_are_safe(
    board, database, learning_app, monkeypatch
):
    client, sign_in = board
    sign_in()
    fixed = datetime.now(UTC)
    learning_app.dependency_overrides[get_account_service] = lambda: AccountService(
        SqlAccountRepository(database), lambda: fixed
    )

    def unavailable(*args, **kwargs):
        raise OperationalError("private SQL", {}, RuntimeError("private connection"))

    monkeypatch.setattr(database, "consistent_read", unavailable)
    response = client.get(URL)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "dependency_unavailable"
    assert "private" not in response.text
    monkeypatch.undo()
    for _ in range(29):
        assert client.get(URL).status_code == 200
    limited = client.get(URL)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"


def test_aggregation_is_database_grouping_and_fixed_query_count(board, database):
    client, sign_in = board
    for _ in range(4):
        sign_in()
        complete_original(client)
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if "ranked_learners" in statement:
            statements.append(statement)

    event.listen(database.engine, "before_cursor_execute", capture)
    try:
        body = read(client)
    finally:
        event.remove(database.engine, "before_cursor_execute", capture)
    assert len(body["entries"]) == 4
    assert len(statements) == 2
    assert all(
        "SELECT DISTINCT" in sql and "GROUP BY" in sql and "rank() OVER" in sql
        for sql in statements
    )


def test_openapi_documents_contract_and_bearer_auth(learning_app):
    document = learning_app.openapi()
    route = document["paths"][URL]["get"]
    assert route["operationId"] == "get_leaderboard"
    assert route["security"] == [{"HTTPBearer": []}]
    assert {parameter["name"] for parameter in route["parameters"]} == {"cursor", "limit"}
    size = next(
        parameter["schema"] for parameter in route["parameters"] if parameter["name"] == "limit"
    )
    assert (size["default"], size["minimum"], size["maximum"]) == (20, 1, 50)
    assert {"200", "401", "403", "422", "429", "503"} <= set(route["responses"])
    assert set(document["components"]["schemas"]["LeaderboardEntry"]["properties"]) == {
        "rank",
        "user_id",
        "display_name",
        "avatar_id",
        "avatar_url",
        "verified_count",
        "is_me",
    }
    assert set(document["components"]["schemas"]["LeaderboardEntry"]["required"]) == {
        "rank",
        "user_id",
        "display_name",
        "avatar_id",
        "avatar_url",
        "verified_count",
        "is_me",
    }


def test_ai_answer_key_and_practice_completion_never_count(api):
    lesson_id = ready_lesson(api)
    view = api.client.get(f"/api/v1/custom-lessons/{lesson_id}").json()
    for challenge in view["challenges"]:
        response = api.client.post(
            f"/api/v1/custom-lessons/{lesson_id}/challenges/{challenge['id']}/answers",
            json={"selected_option": 1}
            if challenge["verification_mode"] == "answer_key"
            else {"text": "Validation runs before the handler."},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 200, response.text
        assert response.json()["correct"] is (
            True if challenge["verification_mode"] == "answer_key" else None
        )
    # The fixture's clock is frozen before account bootstrap; move past its registration.
    api.clock.advance(60)
    assert read(api.client)["entries"] == []
    assert read(api.client)["me"] is None


def test_duplicate_cursor_fields_and_excessively_long_values_are_rejected(board):
    client, sign_in = board
    sign_in()
    duplicate = (
        base64.urlsafe_b64encode(b'{"as_of":"2026-01-01T00:00:00Z","offset":0,"offset":1}')
        .rstrip(b"=")
        .decode()
    )
    for cursor in (duplicate, "a" * 513):
        response = client.get(URL, params={"cursor": cursor})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"


def test_claim_after_cutoff_cannot_change_an_existing_pagination(board, learning_app):
    client, sign_in = board
    complete_original(client)  # Unclaimed guest owns this verified completion.
    for _ in range(2):
        sign_in()
        complete_original(client)
    claimed_person = sign_in()
    first = read(client, limit=1)
    assert first["me"] is None and first["next_cursor"] is not None
    cutoff = datetime.fromisoformat(first["generated_at"].replace("Z", "+00:00"))
    learning_app.state.clock = lambda: cutoff + timedelta(seconds=10)
    assert post(client, "/account/claim-anonymous", {}).status_code == 200
    continued = read(client, cursor=first["next_cursor"], limit=50)
    assert len(continued["entries"]) == 1 and continued["me"] is None
    assert all(
        entry["user_id"] != board_identifier(claimed_person[1]) for entry in continued["entries"]
    )
    refreshed = read(client)
    assert len(refreshed["entries"]) == 3 and refreshed["me"] == {"rank": 1, "verified_count": 1}


@pytest.mark.parametrize("mutation", ["missing", "mismatched"])
def test_incomplete_verification_evidence_fails_closed(board, database, mutation):
    client, sign_in = board
    sign_in()
    complete_original(client)
    assert read(client)["me"] == {"rank": 1, "verified_count": 1}
    # Corruption boundary in the disposable test DB only: start from a genuine API
    # verification, then invalidate one check. Never synthesize a successful run.
    with database.session() as db, db.begin():
        if mutation == "missing":
            db.execute(text("DROP TRIGGER immutable_verification_checks_delete"))
            db.execute(
                delete(m.VerificationCheck).where(m.VerificationCheck.code == "stored_values")
            )
        else:
            db.execute(text("DROP TRIGGER immutable_verification_checks_update"))
            db.execute(
                update(m.VerificationCheck)
                .where(m.VerificationCheck.code == "stored_values")
                .values(matched=False)
            )
    body = read(client)
    assert body["entries"] == [] and body["me"] is None
