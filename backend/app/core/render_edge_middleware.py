"""Render-only scheme interpretation over an operator-confirmed private perimeter.

This policy relies on documented public-edge protocol normalization; it is not a
cryptographic identity for private callers. Never use this policy to trust XFF,
Forwarded, Host, or a private address as an authenticated client identity.
"""

import logging
from contextlib import suppress
from ipaddress import ip_address

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import error_response
from app.core.render_edge_settings import RenderEdgeSettings

_RAW_TRANSPORT = "trace_raw_transport"
_HEALTH = frozenset({"/api/v1/health/live", "/api/v1/health/ready"})


class RawSocketCaptureMiddleware:
    """Launcher-only wrapper BEFORE stock Uvicorn proxy processing, never HTTP data."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in {"http", "websocket"}:
            scope = dict(scope)
            scope["state"] = dict(scope.get("state", {}))
            scope["state"][_RAW_TRANSPORT] = {
                "client": scope.get("client"),
                "scheme": scope.get("scheme"),
            }
        await self.app(scope, receive, send)


def _local_health(scope: Scope) -> bool:
    raw = scope.get("state", {}).get(_RAW_TRANSPORT)
    if (
        not isinstance(raw, dict)
        or raw.get("scheme") != "http"
        or scope["type"] != "http"
        or scope.get("method") not in {"GET", "HEAD"}
        or scope.get("path") not in _HEALTH
        or scope.get("query_string", b"")
    ):
        return False
    headers = [(name.lower(), value) for name, value in scope.get("headers", [])]
    lengths = [value for name, value in headers if name == b"content-length"]
    if any(
        name in {b"authorization", b"cookie", b"transfer-encoding", b"x-forwarded-proto"}
        for name, _ in headers
    ) or lengths not in ([], [b"0"]):
        return False
    peer = raw.get("client")
    if isinstance(peer, tuple) and len(peer) == 2 and isinstance(peer[0], str):
        with suppress(ValueError):
            return ip_address(peer[0]).is_loopback
    return False


class RenderEdgeSchemeMiddleware:
    def __init__(
        self, app: ASGIApp, *, settings: RenderEdgeSettings, logger: logging.Logger | None = None
    ) -> None:
        if settings.mode != "enabled":
            raise ValueError("Render edge scheme middleware requires the explicit enabled profile")
        self.app, self.hostname = app, settings.hostname.encode("ascii")
        self.logger = logger

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        if _local_health(scope):
            # Keep the unchanged HTTPS guard's genuine loopback exception; do
            # not inherit a client identity rewritten by forwarded headers.
            scope["client"] = scope["state"][_RAW_TRANSPORT]["client"]
            scope["scheme"] = "http"
            await self.app(scope, receive, send)
            return
        headers = [(name.lower(), value) for name, value in scope.get("headers", [])]
        proto = [value for name, value in headers if name == b"x-forwarded-proto"]
        hosts = [value for name, value in headers if name == b"host"]
        if proto == [b"https"] and hosts == [self.hostname]:
            scope["scheme"] = "wss" if scope["type"] == "websocket" else "https"
            # Deliberately preserve scope.client, user Authorization and all
            # ownership/rate-limit semantics from the unchanged trusted-XFF path.
            await self.app(scope, receive, send)
            return
        if self.logger is not None:
            reason = (
                "missing_proto"
                if not proto
                else "duplicate_proto"
                if len(proto) != 1
                else "insecure_proto"
                if proto != [b"https"]
                else "invalid_host"
            )
            self.logger.warning("render_transport_rejected", extra={"error_type": reason})
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        response = error_response(
            scope.setdefault("state", {}).get("request_id", "unavailable"),
            "https_required",
            "A secure HTTPS connection is required.",
            400,
        )
        response.headers["Cache-Control"] = "no-store"
        await response(scope, receive, send)
