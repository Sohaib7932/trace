"""Bounded, unauthenticated GET/HEAD/OPTIONS checks; offline plan by default.

No learner writes, credentials, database access, provider calls, redirects or
proxy-environment trust. Only allowlisted response metadata reaches stdout.
"""

import argparse
import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Literal, Never

import httpx

from scripts.operator_http import BACKEND_ORIGIN, FRONTEND_ORIGIN

PREFLIGHTS_PER_ROUTE = 30
MAX_BODY = 8192
MAX_SECONDS = 120.0
ROUTES = ("/api/v1/account/me", "/api/v1/custom-lessons")
SAFE_CODES = frozenset(
    {
        "https_required",
        "unauthenticated",
        "unsafe_request",
        "dependency_unavailable",
        "method_not_allowed",
        "not_found",
        "validation_error",
        "internal_error",
    }
)


@dataclass(frozen=True)
class Observation:
    check: str
    attempted: bool
    http_status: int | None
    error_category: str | None
    cors_origin_exact: bool
    cors_credentials: bool
    passed: bool


@dataclass(frozen=True)
class Report:
    observations: tuple[Observation, ...]

    def safe_summary(self) -> dict[str, object]:
        checks = Counter(item.check for item in self.observations)
        return {
            "mode": "read_only_probe",
            "passed": (
                len(self.observations) == 68
                and checks["preflight_account"] == PREFLIGHTS_PER_ROUTE
                and checks["preflight_custom"] == PREFLIGHTS_PER_ROUTE
                and all(item.passed for item in self.observations)
            ),
            "attempted_requests": sum(item.attempted for item in self.observations),
            "required_preflights_per_route": PREFLIGHTS_PER_ROUTE,
            "error_categories": dict(
                Counter(item.error_category for item in self.observations if item.error_category)
            ),
            "observations": [asdict(item) for item in self.observations],
            "provider_calls": 0,
            "learner_writes": 0,
            "production_configuration_changes": 0,
        }


def _body_metadata(raw: bytes) -> tuple[str | None, str | None]:
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        return None, None
    if not isinstance(value, dict):
        return None, None
    error = value.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    category = code if isinstance(code, str) and code in SAFE_CODES else "other" if code else None
    health = value.get("status")
    return category, health if health in ("alive", "ready") else None


def probe(
    *,
    transport: httpx.BaseTransport | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Report:
    deadline = clock() + MAX_SECONDS
    observations: list[Observation] = []

    def observe(
        check: str,
        method: Literal["GET", "HEAD", "OPTIONS"],
        path: str,
        *,
        extra: dict[str, str] | None = None,
        plain_http: bool = False,
        expected: tuple[int, ...] = (200,),
        foreign_origin: bool = False,
        expected_health: str | None = None,
    ) -> None:
        remaining = deadline - clock()
        if remaining <= 0:
            observations.append(Observation(check, False, None, "deadline", False, False, False))
            return
        headers = {
            "Origin": "https://untrusted.example" if foreign_origin else FRONTEND_ORIGIN,
            "Connection": "close",
        }
        headers.update(extra or {})
        origin = BACKEND_ORIGIN.replace("https://", "http://", 1) if plain_http else BACKEND_ORIGIN
        try:
            # A fresh client/connection samples rotating edge hops, not only a
            # single successful keepalive connection. No user cookie jar exists.
            with (
                httpx.Client(
                    transport=transport,
                    timeout=httpx.Timeout(min(5.0, remaining), connect=min(2.0, remaining)),
                    follow_redirects=False,
                    trust_env=False,
                ) as client,
                client.stream(method, origin + path, headers=headers) as response,
            ):
                raw = bytearray()
                for chunk in response.iter_bytes():
                    if clock() >= deadline:
                        observations.append(
                            Observation(
                                check,
                                True,
                                response.status_code,
                                "deadline",
                                False,
                                False,
                                False,
                            )
                        )
                        return
                    if len(raw) + len(chunk) > MAX_BODY:
                        observations.append(
                            Observation(
                                check,
                                True,
                                response.status_code,
                                "oversized_response",
                                False,
                                False,
                                False,
                            )
                        )
                        return
                    raw.extend(chunk)
                code, health = _body_metadata(bytes(raw))
                exact = response.headers.get_list("access-control-allow-origin") == [
                    FRONTEND_ORIGIN
                ]
                credentials = response.headers.get_list("access-control-allow-credentials") == [
                    "true"
                ]
                passed = response.status_code in expected and code != "https_required"
                if plain_http:
                    passed = passed and response.headers.get("location") == BACKEND_ORIGIN + path
                elif foreign_origin:
                    passed = passed and "access-control-allow-origin" not in response.headers
                else:
                    passed = passed and exact and credentials
                if expected_health is not None:
                    passed = passed and health == expected_health
                if expected == (401,):
                    passed = passed and code == "unauthenticated"
                if method == "OPTIONS" and not foreign_origin:
                    methods = {
                        item.strip().upper()
                        for item in response.headers.get("access-control-allow-methods", "").split(
                            ","
                        )
                    }
                    allowed = {
                        item.strip().lower()
                        for item in response.headers.get("access-control-allow-headers", "").split(
                            ","
                        )
                    }
                    passed = (
                        passed
                        and code is None
                        and "GET" in methods
                        and {"authorization", "content-type", "x-trace-client"} <= allowed
                    )
                observations.append(
                    Observation(check, True, response.status_code, code, exact, credentials, passed)
                )
        except httpx.TimeoutException:
            observations.append(Observation(check, True, None, "timeout", False, False, False))
        except Exception:
            # Exceptions can embed URLs, headers or bodies. Never interpolate one.
            observations.append(Observation(check, True, None, "transport", False, False, False))

    preflight = {
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization,content-type,x-trace-client",
    }
    for route in ROUTES:
        for _ in range(PREFLIGHTS_PER_ROUTE):
            observe(
                "preflight_account" if route == ROUTES[0] else "preflight_custom",
                "OPTIONS",
                route,
                extra=preflight,
            )
    observe("health_live", "GET", "/api/v1/health/live", expected_health="alive")
    observe("health_ready", "GET", "/api/v1/health/ready", expected_health="ready")
    observe("account_unauthenticated", "GET", ROUTES[0], expected=(401,))
    observe("custom_unauthenticated", "GET", ROUTES[1], expected=(401,))
    observe("head_live", "HEAD", "/api/v1/health/live", expected=(200, 405))
    observe(
        "foreign_origin",
        "OPTIONS",
        ROUTES[0],
        extra=preflight,
        expected=(400, 403),
        foreign_origin=True,
    )
    spoofed = {
        "X-Forwarded-Proto": "https",
        "X-Forwarded-For": "203.0.113.9",
        "Forwarded": "for=203.0.113.9;proto=https",
    }
    observe(
        "http_forwarding_spoof",
        "GET",
        ROUTES[0],
        extra=spoofed,
        plain_http=True,
        expected=(301, 302, 307, 308),
    )
    observe(
        "https_forwarding_spoof",
        "GET",
        ROUTES[0],
        extra={**spoofed, "X-Forwarded-Proto": "http"},
        expected=(401,),
    )
    return Report(tuple(observations))


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        self.exit(2, "Invalid command arguments.\n")


def main(argv: list[str] | None = None) -> int:
    parser = SafeParser(description=__doc__)
    parser.add_argument(
        "--probe", action="store_true", help="Run the fixed read-only public checks."
    )
    args = parser.parse_args(argv)
    if not args.probe:
        print(
            json.dumps(
                {
                    "mode": "offline_plan",
                    "network_requests": 0,
                    "preflights_per_route": 30,
                    "provider_calls": 0,
                    "learner_writes": 0,
                }
            )
        )
        return 0
    result = probe().safe_summary()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
