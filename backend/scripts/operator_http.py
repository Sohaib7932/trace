"""Bounded operator HTTP: fixed public target, private token, no automatic replay."""

import json
import math
import os
import re
from collections.abc import Callable
from time import monotonic
from types import TracebackType
from typing import Self
from uuid import UUID

import httpx2
from pydantic import SecretStr

BACKEND_ORIGIN = "https://trace-backend-1lio.onrender.com"
FRONTEND_ORIGIN = "https://trace-ten-mu.vercel.app"
TOKEN_VARIABLE = "TRACE_OPERATOR_ACCESS_TOKEN"
GATEWAY_VARIABLE = "TRACE_OPERATOR_USE_GATEWAY"
MAX_RESPONSE_BYTES = 262144
MAX_REQUEST_BYTES = 16384
MAX_REQUESTS = 32
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_GET = (
    r"/api/v1/account/me",
    r"/api/v1/custom-lessons/languages",
    rf"/api/v1/custom-lessons/requests/{_UUID}",
    rf"/api/v1/custom-lessons/{_UUID}",
    rf"/api/v1/admin/knowledge/revisions/{_UUID}",
)
_POST = (
    "/api/v1/custom-lessons/requests",
    "/api/v1/admin/knowledge/import-reviewed-corpus",
    "/api/v1/admin/knowledge/publications",
)
_ERRORS = frozenset(
    {
        "credential_unavailable",
        "invalid_operation",
        "deadline_exceeded",
        "unauthenticated",
        "forbidden",
        "not_found",
        "conflict",
        "rate_limited",
        "request_rejected",
        "upstream_unavailable",
        "transport_unavailable",
        "invalid_response",
        "response_too_large",
        "redirect_rejected",
    }
)


class OperatorHTTPError(RuntimeError):
    """Only fixed categories cross the operator console boundary."""

    def __init__(self, code: str, *, outcome_unknown: bool = False) -> None:
        self.code = code if code in _ERRORS else "invalid_response"
        self.outcome_unknown = outcome_unknown
        super().__init__(self.code)


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _constant(_: str) -> object:
    raise ValueError


class OperatorHTTP:
    def __init__(
        self,
        token: SecretStr,
        *,
        transport: httpx2.BaseTransport | None = None,
        clock: Callable[[], float] = monotonic,
        deadline_seconds: float = 90.0,
        use_gateway: bool = False,
    ) -> None:
        if (
            not isinstance(token, SecretStr)
            or not re.fullmatch(
                r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token.get_secret_value()
            )
            or len(token.get_secret_value()) > 16384
        ):
            raise OperatorHTTPError("credential_unavailable")
        if not math.isfinite(deadline_seconds) or not 0 < deadline_seconds <= 90:
            raise OperatorHTTPError("invalid_operation")
        self._clock, self._deadline = clock, clock() + deadline_seconds
        self._origin = FRONTEND_ORIGIN if use_gateway else BACKEND_ORIGIN
        self._requests = 0
        self._client = httpx2.Client(
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            verify=True,
            timeout=10.0,
            headers={
                "Authorization": "Bearer " + token.get_secret_value(),
                "Origin": FRONTEND_ORIGIN,
                "X-Trace-Client": "learning-web",
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "Cache-Control": "no-store",
            },
        )

    @classmethod
    def from_environment(cls) -> Self:
        gateway = os.environ.get(GATEWAY_VARIABLE, "0")
        if gateway not in {"0", "1"}:
            raise OperatorHTTPError("invalid_operation")
        return cls(SecretStr(os.environ.get(TOKEN_VARIABLE, "")), use_gateway=gateway == "1")

    def remaining_seconds(self) -> float:
        return max(0.0, self._deadline - self._clock())

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, object] | None = None,
        idempotency_key: UUID | None = None,
    ) -> object:
        allowed = (method == "GET" and any(re.fullmatch(pattern, path) for pattern in _GET)) or (
            method == "POST" and path in _POST
        )
        if (
            not allowed
            or self._requests >= MAX_REQUESTS
            or (method == "GET" and (body is not None or idempotency_key is not None))
        ):
            raise OperatorHTTPError("invalid_operation")
        if idempotency_key is not None and not isinstance(idempotency_key, UUID):
            raise OperatorHTTPError("invalid_operation")
        remaining = self.remaining_seconds()
        if remaining <= 0:
            raise OperatorHTTPError("deadline_exceeded")
        try:
            content = None if body is None else json.dumps(body, allow_nan=False).encode("utf-8")
        except (ValueError, TypeError, OverflowError):
            raise OperatorHTTPError("invalid_operation") from None
        if content is not None and len(content) > MAX_REQUEST_BYTES:
            raise OperatorHTTPError("invalid_operation")
        headers = {"Content-Type": "application/json"} if content is not None else {}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = str(idempotency_key)
        unknown = method == "POST"
        try:
            self._requests += 1
            with self._client.stream(
                method,
                self._origin + path,
                content=content,
                headers=headers,
                timeout=min(10.0, remaining),
            ) as response:
                if 300 <= response.status_code < 400:
                    raise OperatorHTTPError("redirect_rejected", outcome_unknown=unknown)
                if response.status_code >= 400:
                    code = {
                        401: "unauthenticated",
                        403: "forbidden",
                        404: "not_found",
                        409: "conflict",
                        429: "rate_limited",
                    }.get(
                        response.status_code,
                        "upstream_unavailable"
                        if response.status_code >= 500
                        else "request_rejected",
                    )
                    raise OperatorHTTPError(
                        code, outcome_unknown=unknown and response.status_code >= 500
                    )
                if not 200 <= response.status_code < 300:
                    raise OperatorHTTPError("invalid_response", outcome_unknown=unknown)
                if (
                    response.headers.get("content-type", "").split(";")[0].strip()
                    != "application/json"
                ):
                    raise OperatorHTTPError("invalid_response", outcome_unknown=unknown)
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise OperatorHTTPError("invalid_response", outcome_unknown=unknown)
                data = bytearray()
                for chunk in response.iter_bytes():
                    if self.remaining_seconds() <= 0:
                        raise OperatorHTTPError("deadline_exceeded", outcome_unknown=unknown)
                    if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise OperatorHTTPError("response_too_large", outcome_unknown=unknown)
                    data.extend(chunk)
                result: object = json.loads(
                    data, object_pairs_hook=_object, parse_constant=_constant
                )
                if not isinstance(result, (dict, list)):
                    raise OperatorHTTPError("invalid_response", outcome_unknown=unknown)
                return result
        except OperatorHTTPError:
            raise
        except (httpx2.HTTPError, OSError):
            raise OperatorHTTPError("transport_unavailable", outcome_unknown=unknown) from None
        except (ValueError, TypeError, RecursionError, UnicodeError):
            raise OperatorHTTPError("invalid_response", outcome_unknown=unknown) from None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
