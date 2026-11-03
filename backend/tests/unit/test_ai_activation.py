"""Offline setup and activation without reading private developer files or making AI calls."""

import json
import os
from contextlib import contextmanager
from functools import partial

import httpx2
import pytest
from pydantic import SecretStr

from app.core import ai_activation as activation
from app.core.ai_settings import GEMINI_MODEL
from scripts import ai_setup_check, run_gemini

CANARY = "synthetic-private-activation-canary"


@pytest.fixture
def repository(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    (tmp_path / "backend").mkdir()
    return tmp_path


def configured(repository):
    (repository / ".env.local").write_text(
        "NEXT_PUBLIC_AI_MODE=real\n"
        "NEXT_PUBLIC_SITE_URL=http://localhost:3000\n"
        "NEXT_PUBLIC_API_BASE_URL=http://localhost:8000\n"
        "NEXT_PUBLIC_SUPABASE_URL=https://project-a.example.invalid\n"
        "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_synthetic\n",
        encoding="utf-8",
    )
    (repository / "backend" / ".env").write_text(
        "TRACE_SUPABASE_URL=https://project-a.example.invalid\n"
        "TRACE_SUPABASE_ISSUER=https://project-a.example.invalid/auth/v1\n"
        "TRACE_SUPABASE_JWKS_URL=https://project-a.example.invalid/auth/v1/.well-known/jwks.json\n"
        'TRACE_CORS_ORIGINS=["http://localhost:3000"]\n',
        encoding="utf-8",
    )
    (repository / "backend" / ".env.gemini").write_text(
        "GEMINI_API_KEY=" + CANARY + "\n", encoding="utf-8"
    )
    return repository


def diagnostic(repository, **kwargs):
    return activation.ai_setup_diagnostic(repository_root=repository, environ={}, **kwargs)


def test_missing_files_report_presence_and_unknown_running_process_without_network(
    repository, monkeypatch
):
    monkeypatch.setattr(activation, "backend_health", lambda **_: pytest.fail("Unexpected network"))
    report = diagnostic(repository)
    assert not report.frontend_env_file_exists
    assert not report.backend_env_file_exists
    assert not report.credential_file_exists and not report.credential_available
    assert report.frontend_next_start_mode == "mock"
    assert report.cli_process_ai_mode == "disabled"
    assert report.running_backend_ai_mode == report.frontend_running_build_mode == "unknown"
    assert report.backend_health == "not_checked"


def test_matching_configuration_is_reported_without_values_or_client_construction(
    repository, monkeypatch
):
    configured(repository)
    monkeypatch.setattr("app.main.create_app", lambda *a, **k: pytest.fail("Unexpected app"))
    report = diagnostic(repository)
    assert report.frontend_file_mode == "real"
    assert report.frontend_auth_config_valid and report.frontend_public_key_present
    assert report.credential_available and report.credential_file_valid
    assert report.backend_settings_valid
    assert report.supabase_project_compatibility == "match"
    assert (
        report.frontend_backend_host_compatibility == report.frontend_cors_compatibility == "match"
    )
    raw = report.model_dump_json()
    for forbidden in (
        CANARY,
        "project-a",
        "localhost",
        "sb_publishable_synthetic",
        str(repository),
    ):
        assert forbidden not in raw


@pytest.mark.parametrize(
    "mode,expected", [("real", "real"), ("mock", "mock"), ("", "mock"), ("REAL", "mock")]
)
def test_frontend_next_start_mode_is_explicitly_separate_from_unknown_built_mode(
    repository, mode, expected
):
    configured(repository)
    report = activation.ai_setup_diagnostic(
        repository_root=repository, environ={"NEXT_PUBLIC_AI_MODE": mode}
    )
    assert report.frontend_file_mode == "real"
    assert report.frontend_next_start_mode == expected
    assert report.frontend_running_build_mode == "unknown"


@pytest.mark.parametrize(
    "name,value",
    [
        ("NEXT_PUBLIC_GEMINI_API_KEY", CANARY),
        ("NEXT_PUBLIC_SUPABASE_SERVICE_ROLE_KEY", CANARY),
        ("NEXT_PUBLIC_PASSWORD", CANARY),
        ("NEXT_PUBLIC_API_KEY", CANARY),
        ("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", CANARY),
    ],
)
def test_unsafe_frontend_secret_variables_are_flagged_without_echo(repository, name, value):
    configured(repository)
    report = activation.ai_setup_diagnostic(repository_root=repository, environ={name: value})
    assert report.unsafe_frontend_secret_variables
    assert CANARY not in report.model_dump_json()


def test_llm_settings_in_general_backend_env_are_rejected_and_identified(repository):
    configured(repository)
    with (repository / "backend" / ".env").open("a", encoding="utf-8") as file:
        file.write("TRACE_LLM_MODE=gemini_free\n")
    report = diagnostic(repository)
    assert report.misplaced_backend_llm_variables
    assert not report.backend_settings_valid


@pytest.mark.parametrize(
    "replacement,field,expected",
    [
        (
            "NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000",
            "frontend_backend_host_compatibility",
            "mismatch",
        ),
        ("NEXT_PUBLIC_API_BASE_URL=", "frontend_backend_host_compatibility", "invalid"),
        ("NEXT_PUBLIC_SITE_URL=http://localhost:3999", "frontend_cors_compatibility", "mismatch"),
        (
            "NEXT_PUBLIC_SUPABASE_URL=https://project-b.example.invalid",
            "supabase_project_compatibility",
            "mismatch",
        ),
    ],
)
def test_url_and_project_mismatches_are_classified_without_outputting_urls(
    repository, replacement, field, expected
):
    configured(repository)
    name = replacement.split("=", 1)[0]
    path = repository / ".env.local"
    lines = [line for line in path.read_text().splitlines() if not line.startswith(name + "=")]
    path.write_text("\n".join(lines + [replacement]) + "\n", encoding="utf-8")
    report = diagnostic(repository)
    assert getattr(report, field) == expected
    assert "example.invalid" not in report.model_dump_json()


def test_missing_api_override_matches_browser_hostname_fallback(repository):
    configured(repository)
    path = repository / ".env.local"
    path.write_text(
        "\n".join(
            line
            for line in path.read_text().splitlines()
            if not line.startswith("NEXT_PUBLIC_API_BASE_URL=")
        )
    )
    assert diagnostic(repository).frontend_backend_host_compatibility == "match"


def test_wrong_nested_credential_file_is_detected_but_never_loaded(repository):
    nested = repository / "backend" / "backend"
    nested.mkdir()
    (nested / ".env.gemini").write_text("GEMINI_API_KEY=" + CANARY)
    report = diagnostic(repository)
    assert report.nested_credential_file_detected
    assert not report.credential_file_exists and not report.credential_available


@pytest.mark.parametrize(
    "content",
    [
        "GEMINI_API_KEY=\n",
        "OTHER_KEY=" + CANARY,
        "GEMINI_API_KEY=a\nGEMINI_API_KEY=b",
        'GEMINI_API_KEY="unterminated',
        "x" * 65537,
    ],
)
def test_invalid_credential_files_fail_safely(repository, content):
    (repository / "backend" / ".env.gemini").write_text(content, encoding="utf-8")
    with pytest.raises(activation.ActivationError) as error:
        activation.private_gemini_key(backend_root=repository / "backend", environ={})
    assert CANARY not in str(error.value)
    assert not diagnostic(repository).credential_available


def test_secret_loader_returns_secretstr_and_process_takes_precedence(repository):
    configured(repository)
    key = activation.private_gemini_key(
        backend_root=repository / "backend", environ={"GEMINI_API_KEY": "synthetic-process-canary"}
    )
    assert isinstance(key, SecretStr)
    assert key.get_secret_value() == "synthetic-process-canary"
    assert "synthetic-process-canary" not in str(key) + repr(key)


def test_explicit_launcher_uses_file_for_blank_process_key_and_restores_blank(repository):
    configured(repository)
    env = {"GEMINI_API_KEY": ""}
    with activation.activated_gemini_environment(
        confirm_free_tier_project=True, backend_root=repository / "backend", environ=env
    ):
        assert env["GEMINI_API_KEY"] == CANARY
    assert env == {"GEMINI_API_KEY": ""}


@pytest.mark.parametrize(
    "value",
    [
        CANARY,
        "AIzaSyntheticCredentialCanary",
        "sb_secret_synthetic",
        "sk-synthetic",
        "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.c2ln",
        "-----BEGIN PRIVATE KEY-----canary",
    ],
)
def test_innocuous_public_variable_names_do_not_hide_credential_like_values(repository, value):
    configured(repository)
    report = activation.ai_setup_diagnostic(
        repository_root=repository, environ={"NEXT_PUBLIC_DISPLAY_LABEL": value}
    )
    assert report.unsafe_frontend_secret_variables
    assert not report.ready_for_real_ai
    assert value not in report.model_dump_json()


@pytest.mark.parametrize(
    "value", [" ", "value with space", "\nprivate", "private\tvalue", "x" * 4097]
)
def test_unusable_process_credentials_are_rejected_without_values(repository, value):
    with pytest.raises(activation.ActivationError):
        activation.private_gemini_key(
            backend_root=repository / "backend", environ={"GEMINI_API_KEY": value}
        )


def test_no_google_key_or_unloaded_ai_example_fallback(repository):
    (repository / "backend" / "ai.env.example").write_text("TRACE_LLM_MODE=gemini_free")
    report = activation.ai_setup_diagnostic(
        repository_root=repository, environ={"GOOGLE_API_KEY": CANARY}
    )
    assert not report.credential_available
    assert report.cli_process_ai_mode == "disabled"


@pytest.mark.parametrize(
    "failure", [None, RuntimeError(CANARY), KeyboardInterrupt(), SystemExit(4)]
)
def test_activation_restores_every_changed_variable_and_preserves_limits(repository, failure):
    configured(repository)
    env = {
        "TRACE_LLM_MODE": "mock",
        "TRACE_LLM_SPEND_LIMIT_MICROUSD": "8",
        "TRACE_LLM_MAX_RETRIES": "2",
        "GEMINI_API_KEY": "original-process-canary",
        "TRACE_LLM_MAX_REQUEST_BYTES": "1024",
        "TRACE_LLM_MAX_INPUT_TOKENS": "512",
        "TRACE_LLM_MAX_OUTPUT_TOKENS": "128",
        "TRACE_LLM_TOTAL_TIMEOUT_SECONDS": "1",
        "TRACE_LLM_RESPONSE_TIMEOUT_SECONDS": "0.5",
        "TRACE_LLM_MAX_LIVE_REQUESTS_PER_PROCESS": "1",
    }
    before = dict(env)

    def run():
        with activation.activated_gemini_environment(
            confirm_free_tier_project=True, backend_root=repository / "backend", environ=env
        ) as settings:
            assert settings.mode == "gemini_free"
            assert settings.generation_model_id == settings.conversational_model_id == GEMINI_MODEL
            assert settings.spend_limit_microusd == settings.max_retries == 0
            assert settings.max_request_bytes == 1024 and settings.max_input_tokens == 512
            assert settings.max_output_tokens == 128 and settings.total_timeout_seconds == 1
            assert (
                settings.response_timeout_seconds == 0.5
                and settings.max_live_requests_per_process == 1
            )
            if failure is not None:
                raise failure

    if failure is None:
        run()
    else:
        with pytest.raises(type(failure)):
            run()
    assert env == before


def test_confirmation_and_invalid_bounds_leave_environment_unchanged(repository):
    configured(repository)
    env = {"TRACE_LLM_MAX_REQUEST_BYTES": "invalid-" + CANARY}
    for confirmed in (False, True):
        before = dict(env)
        with (
            pytest.raises(activation.ActivationError) as error,
            activation.activated_gemini_environment(
                confirm_free_tier_project=confirmed,
                backend_root=repository / "backend",
                environ=env,
            ),
        ):
            pytest.fail("Invalid configuration cannot activate")
        assert CANARY not in str(error.value)
        assert env == before


def test_optional_probe_is_fixed_loopback_bounded_and_never_sends_credentials(monkeypatch):
    observed = {}

    class Client:
        def __init__(self, **kwargs):
            observed.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        @contextmanager
        def stream(self, method, url):
            observed.update(method=method, url=url)
            yield httpx2.Response(200, content=b'{"status":"ready"}')

    monkeypatch.setattr(activation.httpx2, "Client", Client)
    assert activation.backend_health(port=8123) == "ready"
    assert observed == {
        "timeout": 2.0,
        "follow_redirects": False,
        "trust_env": False,
        "method": "GET",
        "url": "http://127.0.0.1:8123/api/v1/health/ready",
    }


@pytest.mark.parametrize("port,timeout", [(0, 2), (65536, 2), (True, 2), (8000, 0), (8000, 6)])
def test_invalid_probe_bounds_never_construct_client(monkeypatch, port, timeout):
    monkeypatch.setattr(activation.httpx2, "Client", lambda **_: pytest.fail("Unexpected client"))
    assert activation.backend_health(port=port, timeout_seconds=timeout) == "unreachable"


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (503, b"not ready", "not_ready"),
        (301, b"", "not_ready"),
        (200, b"bad json", "not_ready"),
        (200, b'{"status":"other"}', "not_ready"),
        (200, b"x" * 4097, "not_ready"),
    ],
)
def test_probe_rejects_bad_status_malformed_and_oversized_responses(
    monkeypatch, status, body, expected
):
    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        @contextmanager
        def stream(self, *args):
            yield httpx2.Response(status, content=body)

    monkeypatch.setattr(activation.httpx2, "Client", Client)
    assert activation.backend_health() == expected


def test_optional_probe_failure_and_explicit_diagnostic_port(repository, monkeypatch):
    def unavailable(**kwargs):
        raise RuntimeError(CANARY)

    monkeypatch.setattr(activation.httpx2, "Client", unavailable)
    assert activation.backend_health() == "unreachable"
    ports = []
    monkeypatch.setattr(
        activation, "backend_health", lambda **kwargs: ports.append(kwargs["port"]) or "ready"
    )
    assert diagnostic(repository, check_backend=True, port=8124).backend_health == "ready"
    assert ports == [8124]


def launcher_setup(repository, monkeypatch):
    configured(repository)
    monkeypatch.setattr(
        run_gemini,
        "activated_gemini_environment",
        partial(activation.activated_gemini_environment, backend_root=repository / "backend"),
    )
    monkeypatch.setattr(
        run_gemini,
        "ai_setup_diagnostic",
        partial(activation.ai_setup_diagnostic, repository_root=repository),
    )


def test_portable_check_is_offline_and_restores_process_environment(
    repository, monkeypatch, capsys
):
    launcher_setup(repository, monkeypatch)
    before = dict(os.environ)
    assert (
        run_gemini.main(
            ["--confirm-free-tier-project", "--check"],
            server=lambda _: pytest.fail("Unexpected server"),
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["cli_process_ai_mode"] == "gemini_free"
    assert report["running_backend_ai_mode"] == "unknown"
    assert report["backend_health"] == "not_checked"
    assert report["readiness_scope"] == "configuration_preflight_only"
    assert not report["live_provider_verified"]
    assert report["ready_for_real_ai"]
    assert CANARY not in json.dumps(report)
    assert dict(os.environ) == before


@pytest.mark.parametrize(
    "failure,code",
    [(None, 0), (ValueError(CANARY), 2), (KeyboardInterrupt(), 130), (SystemExit(4), 2)],
)
def test_portable_server_success_errors_and_interrupts_restore_environment(
    repository, monkeypatch, capsys, failure, code
):
    launcher_setup(repository, monkeypatch)
    before = dict(os.environ)

    def server(port):
        assert port == 8123 and os.environ["TRACE_LLM_MODE"] == "gemini_free"
        if failure is not None:
            raise failure

    assert run_gemini.main(["--confirm-free-tier-project", "--port", "8123"], server=server) == code
    assert CANARY not in str(capsys.readouterr())
    assert dict(os.environ) == before


def test_runner_never_allows_external_host_reload_or_access_logging(monkeypatch):
    observed = {}
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: observed.update(args=args, **kwargs))
    run_gemini._serve(8123)
    assert observed == {
        "args": ("app.main:create_app",),
        "factory": True,
        "host": "127.0.0.1",
        "port": 8123,
        "access_log": False,
        "log_level": "warning",
    }


@pytest.mark.parametrize("args", [["--host", CANARY], ["--port", CANARY], ["--port", "80"]])
def test_cli_parse_errors_never_echo_supplied_values(capsys, args):
    with pytest.raises(SystemExit) as error:
        run_gemini.main(args)
    assert error.value.code == 2
    assert CANARY not in str(capsys.readouterr())


def test_launcher_rejects_missing_confirmation_and_invalid_general_settings(
    repository, monkeypatch, capsys
):
    launcher_setup(repository, monkeypatch)
    before = dict(os.environ)
    assert run_gemini.main([], server=lambda _: pytest.fail("Unexpected server")) == 2
    (repository / "backend" / ".env").write_text("TRACE_LLM_MODE=gemini_free\n")
    assert (
        run_gemini.main(
            ["--confirm-free-tier-project"], server=lambda _: pytest.fail("Unexpected server")
        )
        == 2
    )
    assert CANARY not in str(capsys.readouterr())
    assert dict(os.environ) == before


def test_backend_profile_check_does_not_claim_frontend_mock_is_ready(
    repository, monkeypatch, capsys
):
    launcher_setup(repository, monkeypatch)
    monkeypatch.setenv("NEXT_PUBLIC_AI_MODE", "mock")
    assert (
        run_gemini.main(
            ["--confirm-free-tier-project", "--check"],
            server=lambda _: pytest.fail("Unexpected server"),
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["cli_process_ai_mode"] == "gemini_free"
    assert not report["ready_for_real_ai"]
    assert report["frontend_next_start_mode"] == "mock"
    assert report["readiness_scope"] == "configuration_preflight_only"


def test_diagnostic_cli_never_prints_exception_details(monkeypatch, capsys):
    def unavailable(**kwargs):
        raise ValueError(CANARY)

    monkeypatch.setattr(ai_setup_check, "ai_setup_diagnostic", unavailable)
    assert ai_setup_check.main([]) == 2
    assert CANARY not in str(capsys.readouterr())


def test_diagnostic_cli_reports_safe_structured_state(repository, monkeypatch, capsys):
    configured(repository)
    monkeypatch.setattr(
        ai_setup_check,
        "ai_setup_diagnostic",
        partial(activation.ai_setup_diagnostic, repository_root=repository),
    )
    assert ai_setup_check.main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["credential_available"] and report["backend_health"] == "not_checked"
    assert CANARY not in json.dumps(report)
