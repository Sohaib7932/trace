"""Operator-owned authentication resources close on every recovery outcome."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from scripts import reconcile_ai_controls as command


@pytest.mark.parametrize("failure", [None, "verify", "reconcile", "close"])
def test_owned_verifier_closes_before_database_and_errors_are_sanitized(
    failure, monkeypatch, capsys
):
    events = []
    operation_id, account_id = uuid4(), uuid4()
    monkeypatch.setattr(
        command.sys, "argv", ["reconcile", "provider", str(operation_id), "--confirm-stopped"]
    )
    monkeypatch.setenv("TRACE_DATABASE_URL", "synthetic-explicit-operator-target")
    monkeypatch.setattr(command, "AccountingSettings", lambda **_: SimpleNamespace(mode="durable"))
    monkeypatch.setattr(command, "Settings", lambda **_: object())
    monkeypatch.setattr(
        command, "Database", lambda _: SimpleNamespace(dispose=lambda: events.append("dispose"))
    )
    monkeypatch.setattr(command.getpass, "getpass", lambda _: "synthetic-private-token-canary")

    class Verifier:
        def __init__(self, settings):
            pass

        def verify(self, token):
            assert token == "synthetic-private-token-canary"
            events.append("verify")
            if failure == "verify":
                raise RuntimeError("synthetic-private-error-canary")
            return object()

        def close(self):
            events.append("close")
            if failure == "close":
                raise RuntimeError("synthetic-private-error-canary")

    def reconcile(kind, target, actor):
        assert (kind, target, actor) == ("provider", operation_id, account_id)
        events.append("reconcile")
        if failure == "reconcile":
            raise RuntimeError("synthetic-private-error-canary")

    account = SimpleNamespace(id=account_id, require_role=lambda role: None)
    monkeypatch.setattr(command, "JwtVerifier", Verifier)
    monkeypatch.setattr(command, "SqlAccountRepository", lambda _: object())
    monkeypatch.setattr(
        command, "AccountService", lambda _: SimpleNamespace(bootstrap=lambda _: account)
    )
    monkeypatch.setattr(command, "SqlAIControls", lambda _: SimpleNamespace(reconcile=reconcile))

    assert command.main() == (0 if failure is None else 1)
    assert events[-2:] == ["close", "dispose"]
    output = capsys.readouterr()
    assert "synthetic-private" not in output.out + output.err
