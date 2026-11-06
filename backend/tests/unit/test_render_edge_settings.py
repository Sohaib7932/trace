"""Render scheme mode is an explicit platform trust decision, disabled otherwise."""

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.core.accounting_settings import AccountingSettings
from app.core.render_edge_settings import RenderEdgeSettings
from app.main import create_app
from scripts import run_production
from tests.unit.test_platform_resources import production_settings


def edge_settings(**changes):
    values = dict(
        mode="enabled",
        hostname="fixture-trace.onrender.com",
        trusted_private_perimeter_confirmed=True,
        render="true",
        render_service_type="web",
        render_service_id="srv-fixture",
        render_external_hostname="fixture-trace.onrender.com",
    )
    values.update(changes)
    return RenderEdgeSettings(_env_file=None, **values)


def test_default_profile_is_disabled_without_render_runtime():
    assert RenderEdgeSettings(_env_file=None).mode == "disabled"
    assert RenderEdgeSettings(_env_file=None).trusted_private_perimeter_confirmed is False


@pytest.mark.parametrize(
    "changes",
    [
        {"trusted_private_perimeter_confirmed": False},
        {"render": ""},
        {"render": "false"},
        {"render_service_type": "pserv"},
        {"render_service_type": "worker"},
        {"render_service_id": ""},
        {"render_service_id": "not-a-service"},
        {"render_external_hostname": "other.onrender.com"},
        {"hostname": ""},
        {"hostname": "https://fixture-trace.onrender.com"},
        {"hostname": "fixture-trace.onrender.com:443"},
        {"hostname": "fixture-trace.onrender.com.evil.invalid"},
        {"hostname": "*.onrender.com"},
        {"hostname": "Fixture-trace.onrender.com"},
        {"hostname": "private-canary"},
        {"mode": "automatic"},
    ],
)
def test_enabled_profile_rejects_missing_or_inconsistent_platform_metadata(changes):
    with pytest.raises(ValidationError) as error:
        edge_settings(**changes)
    assert "private-canary" not in str(error.value)


@pytest.mark.parametrize("environment", ["development", "test"])
def test_enabled_profile_is_production_only_before_resources_open(settings, environment):
    with (
        patch("app.main.Database", side_effect=AssertionError("must not allocate")),
        pytest.raises(ValueError, match="production-only"),
    ):
        create_app(
            settings.model_copy(update={"environment": environment}),
            render_edge_settings=edge_settings(),
        )


def test_named_render_environment_markers_load_without_other_configuration(monkeypatch):
    values = {
        "TRACE_RENDER_EDGE_MODE": "enabled",
        "TRACE_RENDER_EDGE_HOSTNAME": "fixture-trace.onrender.com",
        "TRACE_RENDER_EDGE_TRUSTED_PRIVATE_PERIMETER_CONFIRMED": "true",
        "RENDER": "true",
        "RENDER_SERVICE_TYPE": "web",
        "RENDER_SERVICE_ID": "srv-fixture",
        "RENDER_EXTERNAL_HOSTNAME": "fixture-trace.onrender.com",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    assert RenderEdgeSettings(_env_file=None) == edge_settings()


@pytest.mark.parametrize("enabled", [False, True])
def test_launcher_retains_exact_client_allowlist_and_avoids_double_proxy_parse(
    monkeypatch, enabled
):
    unchanged = "10.29.182.31/32,10.26.211.78/32"
    monkeypatch.setenv("TRACE_TRUSTED_PROXY_IPS", unchanged)
    profile = edge_settings() if enabled else RenderEdgeSettings(_env_file=None)
    with (
        patch.object(run_production, "Settings", return_value=production_settings()),
        patch.object(
            run_production,
            "AccountingSettings",
            return_value=AccountingSettings(_env_file=None, mode="durable", scope="launcher-test"),
        ),
        patch.object(run_production, "RenderEdgeSettings", return_value=profile),
        patch.object(run_production.uvicorn, "run") as run,
    ):
        assert run_production.main() == 0
    assert run.call_args.kwargs["forwarded_allow_ips"] == unchanged
    assert run.call_args.kwargs["proxy_headers"] is (not enabled)
    assert run.call_args.args == (
        (
            "scripts.run_production:create_render_production_app"
            if enabled
            else "app.main:create_app"
        ),
    )


@pytest.mark.parametrize("value", ["", "*", "0.0.0.0/0", "::/0", "10.0.0.1,,10.0.0.2"])
def test_existing_no_wildcard_client_trust_rule_is_preserved(monkeypatch, value):
    monkeypatch.setenv("TRACE_TRUSTED_PROXY_IPS", value)
    with pytest.raises(ValueError):
        run_production._trusted_proxy_ips()
