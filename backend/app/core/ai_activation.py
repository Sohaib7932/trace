"""Private local activation and offline diagnostics; never constructs an AI client."""

import argparse
import io
import json
import os
import re
from collections.abc import Iterator, Mapping, MutableMapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, NoReturn
from urllib.parse import SplitResult, urlsplit

import httpx2
from dotenv.parser import parse_stream
from pydantic import SecretStr

from app.core.ai_settings import GEMINI_MODEL, AIClientSettings
from app.core.settings import BACKEND_ROOT, Settings
from app.domain.lesson_spec.fields import Value

REPOSITORY_ROOT = BACKEND_ROOT.parent
_ENV_LIMIT = 65536
_ACTIVATION = {
    "TRACE_LLM_MODE": "gemini_free",
    "TRACE_LLM_PROVIDER_ID": "gemini",
    "TRACE_LLM_GENERATION_MODEL_ID": GEMINI_MODEL,
    "TRACE_LLM_CONVERSATIONAL_MODEL_ID": GEMINI_MODEL,
    "TRACE_LLM_CREDENTIAL_ENV_VAR": "GEMINI_API_KEY",
    "TRACE_LLM_FREE_TIER_PROJECT_CONFIRMED": "true",
    "TRACE_LLM_SPEND_LIMIT_MICROUSD": "0",
    "TRACE_LLM_MAX_COST_PER_ATTEMPT_MICROUSD": "0",
    "TRACE_LLM_MAX_RETRIES": "0",
}

type ModeState = Literal["real", "mock", "unset", "invalid"]
type Compatibility = Literal["match", "mismatch", "unknown", "invalid"]
type BackendHealth = Literal["not_checked", "ready", "not_ready", "unreachable"]


class ActivationError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Gemini activation is unavailable. Check the safe setup diagnostic.")


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # Unknown CLI arguments could contain an accidentally pasted credential.
        self.exit(2, "Invalid setup command. Use --help; never pass credentials as arguments.\n")


def loopback_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Invalid local port.") from None
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError("Invalid local port.")
    return port


@dataclass(frozen=True)
class _EnvFile:
    exists: bool
    valid: bool
    values: dict[str, str | None] = field(default_factory=dict, repr=False)


def _env_file(path: Path) -> _EnvFile:
    """Use the installed dotenv grammar without logging parser input or warnings."""
    try:
        if not path.exists():
            return _EnvFile(False, True)
        if not path.is_file() or path.stat().st_size > _ENV_LIMIT:
            return _EnvFile(True, False)
        raw = path.read_text(encoding="utf-8-sig")
        values: dict[str, str | None] = {}
        for binding in parse_stream(io.StringIO(raw)):
            if binding.error or (binding.key is not None and binding.key in values):
                return _EnvFile(True, False)
            if binding.key is not None:
                values[binding.key] = binding.value
        return _EnvFile(True, True, values)
    except Exception:
        return _EnvFile(True, False)


def private_gemini_key(
    *, backend_root: Path = BACKEND_ROOT, environ: Mapping[str, str] | None = None
) -> SecretStr:
    """Only the approved process variable or fixed backend credential file is read.

    A nonempty process value takes precedence. An empty string is treated as
    absent by this explicit launcher; a whitespace-only value is invalid. The
    resulting private value is installed temporarily before the provider starts.
    This does not change standalone GeminiCredentials' environment precedence.
    """
    env = os.environ if environ is None else environ
    key_file = _env_file(backend_root / ".env.gemini")
    if not key_file.valid or set(key_file.values) - {"GEMINI_API_KEY"}:
        raise ActivationError()
    raw = env.get("GEMINI_API_KEY") or key_file.values.get("GEMINI_API_KEY") or ""
    if not raw or len(raw) > 4096 or any(char.isspace() or ord(char) < 32 for char in raw):
        raise ActivationError()
    return SecretStr(raw)


def process_ai_settings(environ: Mapping[str, str]) -> AIClientSettings:
    # Supplying every field prevents BaseSettings from reading a different ambient
    # process when this helper is explicitly given an isolated mapping in tests.
    return AIClientSettings(
        _env_file=None,
        **{
            name: environ.get("TRACE_LLM_" + name.upper(), descriptor.default)
            for name, descriptor in AIClientSettings.model_fields.items()
        },
    )


@contextmanager
def activated_gemini_environment(
    *,
    confirm_free_tier_project: bool,
    backend_root: Path = BACKEND_ROOT,
    environ: MutableMapping[str, str] | None = None,
) -> Iterator[AIClientSettings]:
    """Opt in temporarily, preserve stricter limits, restore on every exit path."""
    if confirm_free_tier_project is not True:
        raise ActivationError()
    env = os.environ if environ is None else environ
    key = private_gemini_key(backend_root=backend_root, environ=env)
    changes = {**_ACTIVATION, "GEMINI_API_KEY": key.get_secret_value()}
    # Genuine Gemini responses can exceed the generic ten-second fixture/default
    # budget. Use the existing transport ceiling only when no tighter operator
    # response/total deadline has been supplied. Never raise an explicit cap.
    if "TRACE_LLM_RESPONSE_TIMEOUT_SECONDS" not in env:
        total = env.get("TRACE_LLM_TOTAL_TIMEOUT_SECONDS")
        try:
            response_budget = min(20.0, float(total)) if total is not None else 20.0
        except (ValueError, TypeError):
            raise ActivationError() from None
        changes["TRACE_LLM_RESPONSE_TIMEOUT_SECONDS"] = str(response_budget)
    trial = {**env, **changes}
    try:
        checked = process_ai_settings(trial)
    except Exception:
        raise ActivationError() from None
    previous = {name: env.get(name) for name in changes}
    try:
        env.update(changes)
        yield checked
    finally:
        for name, value in previous.items():
            if value is None:
                env.pop(name, None)
            else:
                env[name] = value


class AISetupDiagnostic(Value):
    schema_version: Literal["ai-setup-check-v1"] = "ai-setup-check-v1"
    readiness_scope: Literal["configuration_preflight_only"] = "configuration_preflight_only"
    live_provider_verified: Literal[False] = False
    ready_for_real_ai: bool
    frontend_env_file_exists: bool
    frontend_env_valid: bool
    frontend_file_mode: ModeState
    frontend_process_mode: ModeState
    frontend_next_start_mode: Literal["real", "mock", "unknown"]
    frontend_running_build_mode: Literal["unknown"] = "unknown"
    frontend_public_key_present: bool
    frontend_auth_config_valid: bool
    unsafe_frontend_secret_variables: bool
    backend_env_file_exists: bool
    backend_env_valid: bool
    backend_settings_valid: bool
    misplaced_backend_llm_variables: bool
    cli_process_ai_mode: Literal["disabled", "mock", "gemini_free", "invalid"]
    cli_process_ai_config_valid: bool
    cli_process_approved_models: bool
    cli_process_free_tier_confirmed: bool
    running_backend_ai_mode: Literal["unknown"] = "unknown"
    credential_file_exists: bool
    credential_available: bool
    credential_file_valid: bool
    nested_credential_file_detected: bool
    frontend_backend_host_compatibility: Compatibility
    supabase_project_compatibility: Compatibility
    frontend_cors_compatibility: Compatibility
    backend_health: BackendHealth = "not_checked"


def _mode(value: str | None) -> ModeState:
    if value is None or value == "":
        return "unset"
    if value == "real":
        return "real"
    return "mock" if value == "mock" else "invalid"


def _url(value: str | None) -> SplitResult | None:
    try:
        parsed = urlsplit(value or "")
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or (
                parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            )
        ):
            return None
        _ = parsed.port  # Validate malformed/out-of-range ports without emitting the value.
        return parsed
    except Exception:
        return None


def _origin(url: SplitResult) -> tuple[str, str | None, int]:
    return url.scheme, url.hostname, url.port or (443 if url.scheme == "https" else 80)


def _unsafe_frontend(values: Mapping[str, str | None], key: SecretStr | None) -> bool:
    for name, value in values.items():
        if not name.startswith("NEXT_PUBLIC_"):
            continue
        # Supplement name checks with conservative value guards. This is not a
        # guarantee that arbitrary secrets can be recognized by their spelling.
        if value and (
            value.startswith(
                ("AIza", "sb_secret_", "sk-", "sk_live_", "sk_test_", "ghp_", "github_pat_")
            )
            or "PRIVATE KEY-----" in value
            or (
                value.startswith("eyJ")
                and re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", value)
            )
            or (key is not None and key.get_secret_value() in value)
        ):
            return True
        if name == "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY":
            if value and not value.startswith("sb_publishable_"):
                return True
        elif any(
            marker in name.upper()
            for marker in (
                "SECRET",
                "PASSWORD",
                "TOKEN",
                "CREDENTIAL",
                "SERVICE_ROLE",
                "API_KEY",
                "GEMINI",
            )
        ):
            return True
    return False


def backend_health(*, port: int = 8000, timeout_seconds: float = 2.0) -> BackendHealth:
    """Optional fixed-loopback SQL readiness probe, never an authenticated AI call."""
    if type(port) is not int or not 1024 <= port <= 65535 or not 0 < timeout_seconds <= 5:
        return "unreachable"
    try:
        with (
            httpx2.Client(
                timeout=timeout_seconds, follow_redirects=False, trust_env=False
            ) as client,
            client.stream("GET", f"http://127.0.0.1:{port}/api/v1/health/ready") as response,
        ):
            if response.status_code != 200:
                return "not_ready"
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > 4096:
                    return "not_ready"
            try:
                return "ready" if json.loads(body) == {"status": "ready"} else "not_ready"
            except (ValueError, TypeError):
                return "not_ready"
    except Exception:
        return "unreachable"


def ai_setup_diagnostic(
    *,
    repository_root: Path = REPOSITORY_ROOT,
    environ: Mapping[str, str] | None = None,
    check_backend: bool = False,
    port: int = 8000,
) -> AISetupDiagnostic:
    env = os.environ if environ is None else environ
    backend = repository_root / "backend"
    front_file, backend_file = (
        _env_file(repository_root / ".env.local"),
        _env_file(backend / ".env"),
    )
    key_file = _env_file(backend / ".env.gemini")
    frontend = {
        **front_file.values,
        **{k: v for k, v in env.items() if k.startswith("NEXT_PUBLIC_")},
    }
    try:
        key = private_gemini_key(backend_root=backend, environ=env)
    except Exception:
        key = None
    key_present = key is not None
    try:
        ai = process_ai_settings(env)
    except Exception:
        ai = None
    try:
        settings = Settings(_env_file=backend / ".env")
    except Exception:
        settings = None
    site = _url(frontend.get("NEXT_PUBLIC_SITE_URL"))
    api = _url(frontend.get("NEXT_PUBLIC_API_BASE_URL"))
    auth = _url(frontend.get("NEXT_PUBLIC_SUPABASE_URL"))
    back_auth = _url(settings.supabase_url) if settings else None
    public_key = frontend.get("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY") or ""
    api_compatibility: Compatibility = "unknown"
    if site:
        if "NEXT_PUBLIC_API_BASE_URL" not in frontend:
            api_compatibility = "match"  # The real adapter derives the browser hostname.
        elif api:
            api_compatibility = "match" if api.hostname == site.hostname else "mismatch"
        else:
            api_compatibility = "invalid"
    project: Compatibility = "unknown"
    if auth and back_auth:
        project = "match" if _origin(auth) == _origin(back_auth) else "mismatch"
    cors: Compatibility = "unknown"
    if settings and site:
        cors = (
            "match"
            if any(_origin(site) == _origin(urlsplit(o)) for o in settings.cors_origins)
            else "mismatch"
        )
    file_mode, process_mode = (
        _mode(front_file.values.get("NEXT_PUBLIC_AI_MODE")),
        _mode(env.get("NEXT_PUBLIC_AI_MODE")),
    )
    next_mode = process_mode if "NEXT_PUBLIC_AI_MODE" in env else file_mode
    unsafe_frontend = _unsafe_frontend(frontend, key)
    frontend_auth_valid = bool(
        site and auth and public_key.startswith("sb_publishable_") and front_file.valid
    )
    health = backend_health(port=port) if check_backend else "not_checked"
    return AISetupDiagnostic(
        ready_for_real_ai=bool(
            front_file.valid
            and next_mode == "real"
            and frontend_auth_valid
            and not unsafe_frontend
            and settings is not None
            and backend_file.valid
            and key_present
            and ai is not None
            and ai.mode == "gemini_free"
            and api_compatibility == project == cors == "match"
            and health in {"not_checked", "ready"}
        ),
        frontend_env_file_exists=front_file.exists,
        frontend_env_valid=front_file.valid,
        frontend_file_mode=file_mode,
        frontend_process_mode=process_mode,
        frontend_next_start_mode="unknown"
        if not front_file.valid
        else "real"
        if next_mode == "real"
        else "mock",
        frontend_public_key_present=bool(public_key),
        frontend_auth_config_valid=frontend_auth_valid,
        unsafe_frontend_secret_variables=unsafe_frontend,
        backend_env_file_exists=backend_file.exists,
        backend_env_valid=backend_file.valid,
        backend_settings_valid=settings is not None and backend_file.valid,
        misplaced_backend_llm_variables=any(
            name.startswith("TRACE_LLM_") for name in backend_file.values
        ),
        cli_process_ai_mode=ai.mode if ai else "invalid",
        cli_process_ai_config_valid=ai is not None,
        cli_process_approved_models=bool(
            ai
            and ai.generation_model_id == GEMINI_MODEL
            and ai.conversational_model_id == GEMINI_MODEL
        ),
        cli_process_free_tier_confirmed=bool(ai and ai.free_tier_project_confirmed),
        credential_file_exists=key_file.exists,
        credential_available=key_present,
        credential_file_valid=key_file.valid
        and not bool(set(key_file.values) - {"GEMINI_API_KEY"}),
        nested_credential_file_detected=(backend / "backend" / ".env.gemini").is_file(),
        frontend_backend_host_compatibility=api_compatibility,
        supabase_project_compatibility=project,
        frontend_cors_compatibility=cors,
        backend_health=health,
    )
