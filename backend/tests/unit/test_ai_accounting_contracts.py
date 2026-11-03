"""Strict durable scope policies, metadata bounds and secret-free operational startup."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ai.accounting import ProviderAttempt, ProviderUsage
from app.core.accounting_settings import AccountingSettings
from scripts import run_production
from tests.unit.test_postgresql_configuration import production


@pytest.mark.parametrize(
    "values",
    [
        {"mode": "durable"},
        {"mode": "durable", "scope": ""},
        {"mode": "durable", "scope": "s", "max_attempts": 101},
        {"max_attempts": True},
        {"max_in_flight": 0},
        {"max_in_flight": 1, "max_subject_in_flight": 2},
        {"api_key": "private-credential-canary"},
    ],
)
def test_invalid_accounting_configuration_fails_without_secret_values(values):
    with pytest.raises(ValidationError) as error:
        AccountingSettings(_env_file=None, **values)
    assert "private-credential-canary" not in str(error.value)


def test_numeric_environment_limits_are_explicit_and_stable(monkeypatch):
    monkeypatch.setenv("TRACE_ACCOUNTING_MODE", "durable")
    monkeypatch.setenv("TRACE_ACCOUNTING_SCOPE", "pilot-approved-v1")
    monkeypatch.setenv("TRACE_ACCOUNTING_MAX_ATTEMPTS", "20")
    settings = AccountingSettings(_env_file=None)
    assert settings.policy().max_attempts == 20 and settings.policy().scope == "pilot-approved-v1"


@pytest.mark.parametrize(
    "extra",
    [
        {"prompt": "private-canary"},
        {"response": "private-canary"},
        {"input_tokens": -1},
        {"input_tokens": True},
        {"provider_duration_ms": 1_000_000_001},
    ],
)
def test_usage_rejects_raw_content_and_unbounded_data(extra):
    with pytest.raises(ValidationError) as error:
        ProviderUsage(status="success", **extra)
    assert "private-canary" not in str(error.value)


def test_provider_attempt_does_not_accept_a_client_question_or_account():
    with pytest.raises(ValidationError):
        ProviderAttempt(
            id=uuid4(),
            capability="tutor",
            model_id="gemini-3.5-flash-lite",
            subject_hash="a" * 64,
            estimated_input_bytes=1,
            question="untrusted",
            account_id=uuid4(),
        )


@pytest.mark.parametrize("proxy", ["", "*", "0.0.0.0/0", "::/0", "proxy.example", "127.0.0.1,"])
def test_production_startup_refuses_unapproved_proxy_trust(proxy, monkeypatch, capsys):
    monkeypatch.setattr(run_production, "Settings", lambda **_: production())
    monkeypatch.setenv("TRACE_ACCOUNTING_MODE", "durable")
    monkeypatch.setenv("TRACE_ACCOUNTING_SCOPE", "proxy-policy-test")
    monkeypatch.setenv("TRACE_TRUSTED_PROXY_IPS", proxy)
    monkeypatch.setattr(
        run_production.uvicorn, "run", lambda *_args, **_kwargs: pytest.fail("Server started")
    )
    assert run_production.main() == 2
    assert "configuration is invalid" in capsys.readouterr().err


def test_production_startup_trusts_only_the_explicit_proxy_network(monkeypatch):
    calls = []
    monkeypatch.setattr(run_production, "Settings", lambda **_: production())
    monkeypatch.setenv("TRACE_ACCOUNTING_MODE", "durable")
    monkeypatch.setenv("TRACE_ACCOUNTING_SCOPE", "proxy-policy-test")
    monkeypatch.setenv("TRACE_TRUSTED_PROXY_IPS", "127.0.0.1/32, ::1/128")
    monkeypatch.setattr(run_production.uvicorn, "run", lambda *args, **kwargs: calls.append(kwargs))
    assert run_production.main() == 0
    assert calls[0]["forwarded_allow_ips"] == "127.0.0.1/32,::1/128"
    assert calls[0]["proxy_headers"] is True and calls[0]["workers"] == 1


@pytest.mark.parametrize("mode", ["memory", "durable"])
def test_production_startup_requires_durable_shared_admission(mode, monkeypatch, capsys):
    monkeypatch.setattr(run_production, "Settings", lambda **_: production())
    monkeypatch.setenv("TRACE_TRUSTED_PROXY_IPS", "127.0.0.1/32")
    monkeypatch.setenv("TRACE_ACCOUNTING_MODE", mode)
    monkeypatch.delenv("TRACE_ACCOUNTING_SCOPE", raising=False)
    monkeypatch.setattr(
        run_production.uvicorn, "run", lambda *_args, **_kwargs: pytest.fail("Server started")
    )
    assert run_production.main() == 2
    assert "configuration is invalid" in capsys.readouterr().err
