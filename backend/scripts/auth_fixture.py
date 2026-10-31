"""Loopback-only Playwright Auth protocol fixture. Never imported by the application.

Ephemeral test users, link mailbox, refresh sessions and generated signing keys exist
only in memory. This is a controlled SDK integration test, not Supabase or Google.
"""

import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import jwt
import uvicorn
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

URL = "http://127.0.0.1:8001"
ORIGIN = "http://127.0.0.1:3100"


@dataclass
class FixtureUser:
    id: str
    email: str
    password: str
    confirmed: bool = False

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "aud": "authenticated",
            "role": "authenticated",
            "email": self.email,
            "email_confirmed_at": "2026-10-31T00:00:00Z" if self.confirmed else None,
            "created_at": "2026-10-31T00:00:00Z",
            "app_metadata": {"provider": "email", "providers": ["email"]},
            "user_metadata": {},
            "identities": [{"id": self.id, "provider": "email", "user_id": self.id}],
            "is_anonymous": False,
        }


def create_fixture() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[ORIGIN],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=[
            "authorization",
            "apikey",
            "content-type",
            "x-client-info",
            "x-supabase-api-version",
        ],
    )
    key = ec.generate_private_key(ec.SECP256R1())
    public = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    public.update(kid="ephemeral-browser-fixture", alg="ES256", use="sig", key_ops=["verify"])
    users: dict[str, FixtureUser] = {}
    refresh: dict[str, FixtureUser] = {}
    links: dict[str, tuple[FixtureUser, str]] = {}
    mailbox: dict[str, str] = {}
    refresh_count = 0

    def session(user: FixtureUser, ttl: int = 1800) -> dict[str, Any]:
        now = int(datetime.now(UTC).timestamp())
        token = jwt.encode(
            {
                "iss": URL + "/auth/v1",
                "aud": "authenticated",
                "sub": user.id,
                "iat": now,
                "exp": now + ttl,
                "role": "authenticated",
                "email": user.email,
                "session_id": str(uuid4()),
                "is_anonymous": False,
            },
            key,
            algorithm="ES256",
            headers={"kid": public["kid"]},
        )
        raw = secrets.token_urlsafe(32)
        refresh[raw] = user
        return {
            "access_token": token,
            "refresh_token": raw,
            "token_type": "bearer",
            "expires_in": ttl,
            "expires_at": now + ttl,
            "user": user.public(),
        }

    def authenticated(request: Request) -> FixtureUser:
        try:
            token = request.headers.get("authorization", "").removeprefix("Bearer ")
            claims = jwt.decode(
                token,
                key.public_key(),
                algorithms=["ES256"],
                audience="authenticated",
                issuer=URL + "/auth/v1",
            )
            return next(user for user in users.values() if user.id == claims["sub"])
        except (jwt.PyJWTError, StopIteration):
            raise HTTPException(401, "Invalid fixture session") from None

    def send_link(user: FixtureUser, kind: str, destination: str) -> None:
        parsed = urlsplit(destination)
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN or parsed.path != "/auth/callback":
            raise HTTPException(400, "Fixture redirect not allowed")
        raw = secrets.token_urlsafe(32)
        links[raw] = (user, kind)
        params = parse_qs(parsed.query)
        params.update(token_hash=[raw], type=[kind])
        mailbox[user.email] = urlunsplit(parsed._replace(query=urlencode(params, doseq=True)))

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"fixture": True}

    @app.get("/auth/v1/.well-known/jwks.json")
    def jwks() -> dict[str, Any]:
        return {"keys": [public]}

    @app.post("/auth/v1/signup")
    async def signup(request: Request) -> dict[str, Any]:
        body = await request.json()
        email = str(body.get("email", "")).lower()
        if not email.endswith("@example.test") or len(body.get("password", "")) < 12:
            raise HTTPException(400, "Only controlled test addresses are supported")
        user = users.setdefault(email, FixtureUser(str(uuid4()), email, body["password"]))
        send_link(user, "signup", request.query_params.get("redirect_to", ""))
        return user.public()

    @app.post("/auth/v1/verify")
    async def verify(request: Request) -> dict[str, Any]:
        body = await request.json()
        link = links.pop(body.get("token_hash", ""), None)
        if not link or body.get("type") != link[1]:
            raise HTTPException(403, "Expired or invalid fixture link")
        user, _ = link
        user.confirmed = True
        return session(user)

    @app.post("/auth/v1/token")
    async def token(request: Request) -> dict[str, Any]:
        nonlocal refresh_count
        body = await request.json()
        if request.query_params.get("grant_type") == "refresh_token":
            user = refresh.pop(body.get("refresh_token", ""), None)
            if not user:
                raise HTTPException(400, "Invalid fixture refresh token")
            refresh_count += 1
            return session(user)
        user = users.get(str(body.get("email", "")).lower())
        if not user or user.password != body.get("password") or not user.confirmed:
            raise HTTPException(400, "Invalid or unconfirmed fixture credentials")
        # A short initial access token exercises proxy refresh through the official SDK.
        return session(user, ttl=60)

    @app.get("/auth/v1/user")
    def get_user(request: Request) -> dict[str, Any]:
        return authenticated(request).public()

    @app.put("/auth/v1/user")
    async def update_user(request: Request) -> dict[str, Any]:
        user = authenticated(request)
        body = await request.json()
        if len(body.get("password", "")) < 12:
            raise HTTPException(422, "Fixture password too short")
        user.password = body["password"]
        return user.public()

    @app.post("/auth/v1/logout", status_code=204)
    def logout(request: Request) -> None:
        user = authenticated(request)
        for raw in list(refresh):
            if refresh[raw].id == user.id:
                del refresh[raw]

    @app.post("/auth/v1/recover")
    @app.post("/auth/v1/resend")
    async def recover(request: Request) -> dict[str, Any]:
        body = await request.json()
        user = users.get(str(body.get("email", "")).lower())
        if user:
            send_link(
                user,
                "signup" if request.url.path.endswith("resend") else "recovery",
                request.query_params.get("redirect_to", ""),
            )
        return {}

    @app.get("/fixture/mail")
    def mail(email: str) -> dict[str, str | None]:
        return {"link": mailbox.get(email)}

    @app.get("/fixture/stats")
    def stats() -> dict[str, int]:
        return {"refreshes": refresh_count}

    return app


if __name__ == "__main__":
    uvicorn.run(
        create_fixture(), host="127.0.0.1", port=8001, access_log=False, log_level="warning"
    )
