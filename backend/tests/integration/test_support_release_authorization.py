"""Late authorization failures must withhold quotations and release evidence."""

import io
import json
import logging
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, update

from app.api.dependencies import (
    get_account_service,
    get_http_support_service,
    get_knowledge_service,
)
from app.core.accounting_settings import AccountingSettings
from app.core.logging import JsonFormatter
from app.db import knowledge_models as k
from app.db import models as m
from app.db.accounts import SqlAccountRepository
from app.domain.learning import LearningError
from app.services.accounts import AccountService
from tests.integration.test_live_ai_http import api as api  # noqa: F401
from tests.integration.test_live_ai_http import support


@pytest.fixture
def release_events(api):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    api.app.state.logger.addHandler(handler)
    try:
        yield stream
    finally:
        api.app.state.logger.removeHandler(handler)
        handler.close()


def user_id(api):
    with api.database.session() as session:
        identifier = session.scalar(
            select(m.AuthSubject.user_id).where(m.AuthSubject.subject == api.signer.subject)
        )
    assert identifier is not None
    return identifier


def assert_withheld(api, response, stream, status, *, provider_calls=1):
    assert response.status_code == status, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == ("unauthenticated" if status == 401 else "forbidden")
    assert len(api.provider.calls) == provider_calls
    # Error envelopes never contain a support reference or its underlying quote.
    for document in api.state.package.documents:
        for passage in document.passages:
            assert passage.text not in response.text
    with api.database.session() as session:
        assert session.scalar(select(func.count()).select_from(k.KnowledgeReceiptRow)) == 0
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert not [event for event in events if event["event"] == "support_answer_released"]
    assert not [event for event in events if event["event"] == "ai_delivery"]


def test_expiry_after_authentication_but_before_worker_prevents_any_provider_call(
    api, release_events
):
    original_factory = api.app.dependency_overrides[get_http_support_service]

    def expire_before_worker():
        # This dependency runs after authentication and before operation admission.
        api.clock.advance(1801)
        return original_factory()

    api.app.dependency_overrides[get_http_support_service] = expire_before_worker
    response = support(api)
    assert_withheld(api, response, release_events, 401, provider_calls=0)


def test_jwt_expiry_during_provider_work_withholds_answer_and_release_receipt(api, release_events):
    api.provider.callback = lambda: api.clock.advance(1801)
    response = support(api)
    assert api.knowledge.available  # This is authorization expiry, not stale documentation.
    assert_withheld(api, response, release_events, 401)


@pytest.mark.parametrize("change", ["disabled", "learner_role_removed"])
def test_database_authority_changes_during_provider_work_prevent_release(
    api, release_events, change
):
    def change_authority():
        identifier = user_id(api)
        with api.database.session() as session, session.begin():
            if change == "disabled":
                session.execute(
                    update(m.User).where(m.User.id == identifier).values(status="disabled")
                )
            else:
                # A privileged mutation of this disposable fixture simulates revocation.
                session.execute(
                    delete(m.UserRole).where(
                        m.UserRole.user_id == identifier, m.UserRole.role == "learner"
                    )
                )

    api.provider.callback = change_authority
    response = support(api)
    assert_withheld(api, response, release_events, 403)


def test_changed_account_identity_after_provider_cannot_release_another_principals_answer(
    api, release_events
):
    service = AccountService(SqlAccountRepository(api.database))
    changed, different_id = [False], uuid4()

    def bootstrap(identity):
        account = service.bootstrap(identity)
        return replace(account, id=different_id) if changed[0] else account

    api.app.dependency_overrides[get_account_service] = lambda: SimpleNamespace(bootstrap=bootstrap)
    api.provider.callback = lambda: changed.__setitem__(0, True)
    response = support(api)
    assert_withheld(api, response, release_events, 401)


@pytest.mark.parametrize("code,status", [("unauthenticated", 401), ("forbidden", 403)])
def test_final_receipt_authorization_failure_is_not_converted_to_success_or_logged_release(
    api, release_events, code, status
):
    # Isolate the HTTP release boundary: shared admission/storage integrity has
    # its own actual SQLite/PostgreSQL tests. This fault occurs before any receipt write.
    api.app.state.accounting_settings = AccountingSettings(
        _env_file=None, mode="durable", scope="synthetic-support-release-fault"
    )
    authorize = Mock(
        side_effect=LearningError(code, "synthetic-private-receipt-authorization-error")
    )
    api.app.dependency_overrides[get_knowledge_service] = lambda: SimpleNamespace(
        authorize_release=authorize
    )
    response = support(api)
    authorize.assert_called_once()
    assert authorize.call_args.args[0].response.status == "answered"
    assert_withheld(api, response, release_events, status)
    assert "synthetic-private-receipt-authorization-error" not in response.text
    assert "synthetic-private-receipt-authorization-error" not in release_events.getvalue()
