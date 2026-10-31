import asyncio
import logging
import re
import time
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import error_response

SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, logger: logging.Logger) -> None:
        self.app, self.logger = app, logger

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        supplied = next(
            (v.decode("latin-1") for k, v in scope["headers"] if k.lower() == b"x-request-id"), ""
        )
        request_id = supplied if SAFE_REQUEST_ID.fullmatch(supplied) else str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        started, status = time.monotonic(), 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [
                    (k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"
                ] + [(b"x-request-id", request_id.encode("ascii"))]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            route = getattr(scope.get("route"), "path", None)
            self.logger.info(
                "request_complete",
                extra={
                    "request_id": request_id,
                    "method": scope["method"],
                    "route": route,
                    "status_code": status,
                    "duration_ms": round((time.monotonic() - started) * 1000, 2),
                },
            )


class RequestLimitsMiddleware:
    """Bound JSON request buffering and execution; convert unexpected failures safely."""

    def __init__(
        self, app: ASGIApp, max_bytes: int, timeout_seconds: float, logger: logging.Logger
    ) -> None:
        self.app, self.max_bytes, self.timeout_seconds = app, max_bytes, timeout_seconds
        self.logger = logger

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        response_started = False

        async def track_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        request_id = scope["state"]["request_id"]
        try:
            async with asyncio.timeout(self.timeout_seconds):
                body = bytearray()
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    body.extend(message.get("body", b""))
                    if len(body) > self.max_bytes:
                        response = error_response(
                            request_id, "request_too_large", "Request body is too large.", 413
                        )
                        await response(scope, receive, send)
                        return
                    if not message.get("more_body", False):
                        break
                replayed = False

                async def replay() -> Message:
                    nonlocal replayed
                    if not replayed:
                        replayed = True
                        return {"type": "http.request", "body": bytes(body), "more_body": False}
                    return await receive()

                await self.app(scope, replay, track_send)
        except Exception as exc:
            if response_started:
                raise
            timeout = isinstance(exc, TimeoutError)
            self.logger.error(
                "request_failed",
                extra={
                    "request_id": request_id,
                    "error_type": "timeout" if timeout else "internal",
                },
            )
            response = error_response(
                request_id,
                "request_timeout" if timeout else "internal_error",
                "Request timed out." if timeout else "An internal error occurred.",
                504 if timeout else 500,
            )
            await response(scope, receive, send)
