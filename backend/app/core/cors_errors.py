"""CORS on bounded error responses without bypassing transport or API admission."""

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class AllowedOriginErrorCORSMiddleware:
    def __init__(self, app: ASGIApp, *, allowed_origins: tuple[str, ...]) -> None:
        self.app = app
        self.allowed_origins = frozenset(origin.encode("ascii") for origin in allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        origins = [value for name, value in scope.get("headers", []) if name.lower() == b"origin"]
        origin = origins[0] if len(origins) == 1 and origins[0] in self.allowed_origins else None

        async def cors_error_send(message: Message) -> None:
            if message["type"] == "http.response.start" and message["status"] >= 400 and origin:
                headers = list(message.get("headers", []))
                names = {name.lower() for name, _ in headers}
                if b"access-control-allow-origin" not in names:
                    headers += [
                        (b"access-control-allow-origin", origin),
                        (b"access-control-allow-credentials", b"true"),
                    ]
                    if b"vary" not in names:
                        headers.append((b"vary", b"Origin"))
                    else:
                        headers = [
                            (name, value + b", Origin" if name.lower() == b"vary" else value)
                            for name, value in headers
                        ]
                if b"access-control-expose-headers" not in names:
                    headers.append((b"access-control-expose-headers", b"X-Request-ID"))
                message = {**message, "headers": headers}
            await send(message)

        # Never answer OPTIONS here. The transport guard and existing CORS
        # middleware must both accept a preflight before it can return success.
        await self.app(scope, receive, cors_error_send)
