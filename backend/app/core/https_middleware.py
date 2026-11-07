"""Production transport boundary after the server's explicit proxy allowlist.

Raw forwarded headers are deliberately ignored here. Only the ASGI scheme set
by the server is authoritative. Local container health probes carry no credentials.
"""

from contextlib import suppress
from ipaddress import ip_address

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import error_response

HEALTH_PATHS = frozenset({"/api/v1/health/live", "/api/v1/health/ready"})


class ProductionHTTPSMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"} or scope.get("scheme") in {"https", "wss"}:
            await self.app(scope, receive, send)
            return
        peer = scope.get("client")
        loopback = False
        if peer:
            with suppress(ValueError):
                loopback = ip_address(peer[0]).is_loopback
        if (
            scope["type"] == "http"
            and scope.get("method") in {"GET", "HEAD"}
            and scope.get("path") in HEALTH_PATHS
            and loopback
        ):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        request_id = scope.setdefault("state", {}).get("request_id", "unavailable")
        response = error_response(
            request_id, "https_required", "A secure HTTPS connection is required.", 400
        )
        response.headers["Cache-Control"] = "no-store"
        await response(scope, receive, send)
