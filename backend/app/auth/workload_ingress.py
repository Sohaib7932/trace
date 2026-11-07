"""Bounded verification of Trace's pinned Vercel production workload identity."""

from __future__ import annotations

import asyncio
import math
import re
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from hmac import compare_digest
from threading import Condition, Lock
from typing import Any, Literal, Protocol

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth.jwks_http import HttpJwksSource
from app.core.errors import error_response
from app.core.https_middleware import HEALTH_PATHS
from app.domain.clock import utc_now

AUTH = b"x-trace-ingress-authorization"
VERIFIED = b"x-trace-ingress-verified"
_INGRESS_PREFIX = b"x-trace-ingress-"
_OWNER = "sohaibp11-1003"
_PROJECT = "trace"
_ISSUER_BASE = "https://oidc.vercel.com"
_KID = re.compile(r"[A-Za-z0-9._-]{1,200}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\Z")
_OWNER_ID = re.compile(r"(?:team|user)_[A-Za-z0-9_-]{1,140}\Z")
_PROJECT_ID = re.compile(r"prj_[A-Za-z0-9_-]{1,140}\Z")
_IDENTITY_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_PRIVATE_JWK = frozenset({"d", "p", "q", "dp", "dq", "qi", "oth", "k"})

type IssuerMode = Literal["team", "global"]


class IngressFailure(Exception):
    def __init__(self, *, unavailable: bool = False) -> None:
        self.status_code = 503 if unavailable else 403
        self.code = "ingress_unavailable" if unavailable else "ingress_rejected"
        self.message = (
            "Authenticated ingress is unavailable."
            if unavailable
            else "Authenticated ingress was rejected."
        )
        super().__init__(self.message)


@dataclass(frozen=True)
class IngressConfig:
    issuer_mode: IssuerMode
    identity_sha256: str
    jwks_cache_seconds: int = 300

    def __post_init__(self) -> None:
        if (
            self.issuer_mode not in {"team", "global"}
            or not isinstance(self.identity_sha256, str)
            or not _IDENTITY_DIGEST.fullmatch(self.identity_sha256)
            or type(self.jwks_cache_seconds) is not int
            or not 1 <= self.jwks_cache_seconds <= 300
        ):
            raise ValueError("Invalid pinned workload ingress configuration")

    @property
    def issuer(self) -> str:
        return f"{_ISSUER_BASE}/{_OWNER}" if self.issuer_mode == "team" else _ISSUER_BASE

    @property
    def audience(self) -> str:
        return f"https://vercel.com/{_OWNER}"

    @property
    def subject(self) -> str:
        return f"owner:{_OWNER}:project:{_PROJECT}:environment:production"

    @property
    def jwks_url(self) -> str:
        return self.issuer + "/.well-known/jwks"

    def matches_identity(self, owner_id: object, project_id: object) -> bool:
        if (
            not isinstance(owner_id, str)
            or not _OWNER_ID.fullmatch(owner_id)
            or not isinstance(project_id, str)
            or not _PROJECT_ID.fullmatch(project_id)
        ):
            return False
        digest = sha256(f"{owner_id}\n{project_id}".encode()).hexdigest()
        return compare_digest(digest, self.identity_sha256)


class JwksSource(Protocol):
    def fetch(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class VerifiedWorkload:
    expires_at: datetime


class WorkloadVerifier:
    def __init__(
        self,
        config: IngressConfig,
        source: JwksSource | None = None,
        clock: Callable[[], datetime] = utc_now,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        async_timeout_seconds: float = 4.0,
    ) -> None:
        if (
            type(async_timeout_seconds) not in {int, float}
            or not math.isfinite(async_timeout_seconds)
            or not 0 < async_timeout_seconds <= 4
        ):
            raise ValueError("Invalid bounded workload verification deadline")
        self.async_timeout_seconds = async_timeout_seconds
        self._workers = Condition()
        self._executor = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="trace-ingress-verify"
        )
        self._pending: set[Future[VerifiedWorkload]] = set()
        self._disposed = False
        self.config = config
        self.source = (
            source if source is not None else HttpJwksSource(config.jwks_url, timeout_seconds=3)
        )
        self.clock, self.monotonic = clock, monotonic
        self._owns_source = source is None
        self._keys: dict[str, jwt.PyJWK] = {}
        self._expires = 0.0
        self._last_refresh = float("-inf")
        self._lock = Lock()
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def stop_admission(self) -> None:
        with self._workers:
            self._closed = True

    def _finished(self, future: Future[VerifiedWorkload]) -> None:
        with self._workers:
            self._pending.discard(future)
            self._workers.notify_all()

    async def verify_async(self, token: str) -> VerifiedWorkload:
        # Reserve synchronously BEFORE submission. At most four actual/queued
        # workers exist; canceling the HTTP waiter never cancels their futures.
        with self._workers:
            if self._closed or len(self._pending) >= 4:
                raise IngressFailure(unavailable=True)
            try:
                future = self._executor.submit(self.verify, token)
            except RuntimeError:
                raise IngressFailure(unavailable=True) from None
            self._pending.add(future)
            future.add_done_callback(self._finished)
        wrapped = asyncio.wrap_future(future)
        # A canceled/timed-out waiter must not leave an unobserved late worker
        # exception on its event loop. Actual ownership remains in _pending.
        wrapped.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            async with asyncio.timeout(self.async_timeout_seconds):
                return await asyncio.shield(wrapped)
        except TimeoutError:
            raise IngressFailure(unavailable=True) from None

    def wait_for_idle(self, timeout: float | None = None) -> bool:
        end = time.monotonic() + timeout if timeout is not None else None
        with self._workers:
            if not self._workers.wait_for(lambda: not self._pending, timeout):
                return False
        wait = getattr(self.source, "wait_for_idle", None)
        remaining = max(0, end - time.monotonic()) if end is not None else None
        return bool(wait(remaining)) if callable(wait) else True

    def close(self) -> None:
        # Owner invokes off-loop AFTER its bounded shutdown grace. This final
        # drain can wait for actual source/OS cleanup; it never detaches work.
        self.stop_admission()
        with self._workers:
            if self._disposed:
                return
        self._executor.shutdown(wait=True, cancel_futures=False)
        self.wait_for_idle(None)
        if self._owns_source:
            close = getattr(self.source, "close", None)
            if callable(close):
                close()
        with self._lock:
            self._keys.clear()
            self._expires = 0
        with self._workers:
            self._disposed = True

    def _key(self, kid: str) -> jwt.PyJWK:
        with self._lock:
            if self._closed:
                raise IngressFailure(unavailable=True)
            now = self.monotonic()
            expired = now >= self._expires
            if expired or kid not in self._keys:
                if now - self._last_refresh < 5:
                    raise IngressFailure(unavailable=expired)
                self._last_refresh = now
                try:
                    data = self.source.fetch()
                    raw_keys = data.get("keys")
                    if not isinstance(raw_keys, list) or not 1 <= len(raw_keys) <= 16:
                        raise ValueError
                    keys: dict[str, jwt.PyJWK] = {}
                    for raw in raw_keys:
                        if (
                            not isinstance(raw, dict)
                            or raw.get("kty") != "RSA"
                            or raw.get("alg", "RS256") != "RS256"
                        ):
                            raise ValueError
                        name = raw.get("kid")
                        if (
                            not isinstance(name, str)
                            or not _KID.fullmatch(name)
                            or name in keys
                            or raw.get("use", "sig") != "sig"
                            or raw.get("key_ops", ["verify"]) != ["verify"]
                            or _PRIVATE_JWK.intersection(raw)
                        ):
                            raise ValueError
                        key = jwt.PyJWK.from_dict(raw, algorithm="RS256")
                        if not isinstance(key.key, rsa.RSAPublicKey) or key.key.key_size < 2048:
                            raise ValueError
                        keys[name] = key
                    self._keys = keys
                    self._expires = self.monotonic() + self.config.jwks_cache_seconds
                except Exception:
                    if expired:
                        self._keys.clear()
                        self._expires = 0
                    raise IngressFailure(unavailable=True) from None
            selected = self._keys.get(kid)
            if selected is None:
                raise IngressFailure()
            return selected

    def verify(self, token: str) -> VerifiedWorkload:
        if self._closed:
            raise IngressFailure(unavailable=True)
        try:
            if not isinstance(token, str) or len(token) > 16384 or not _TOKEN.fullmatch(token):
                raise ValueError
            header = jwt.get_unverified_header(token)
            if (
                set(header) != {"alg", "kid", "typ"}
                or header.get("alg") != "RS256"
                or header.get("typ") != "JWT"
                or not isinstance(header.get("kid"), str)
                or not _KID.fullmatch(header["kid"])
            ):
                raise ValueError
            key = self._key(header["kid"])
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                issuer=self.config.issuer,
                audience=self.config.audience,
                options={
                    "require": [
                        "iss",
                        "aud",
                        "sub",
                        "iat",
                        "nbf",
                        "exp",
                        "owner",
                        "owner_id",
                        "project",
                        "project_id",
                        "environment",
                    ],
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )
            if any(type(claims[name]) is not int for name in ("iat", "nbf", "exp")):
                raise ValueError
            now = self.clock()
            if now.tzinfo is None:
                raise IngressFailure(unavailable=True)
            at = now.timestamp()
            if (
                claims["iat"] > at
                or claims["nbf"] > at
                or claims["exp"] <= at
                or not 0 < claims["exp"] - claims["iat"] <= 7200
                or claims["nbf"] >= claims["exp"]
                or claims["aud"] != self.config.audience
                or claims["sub"] != self.config.subject
                or claims["owner"] != _OWNER
                or claims["project"] != _PROJECT
                or claims["environment"] != "production"
                or not self.config.matches_identity(claims["owner_id"], claims["project_id"])
            ):
                raise ValueError
            if self._closed:
                raise IngressFailure(unavailable=True)
            return VerifiedWorkload(datetime.fromtimestamp(claims["exp"], UTC))
        except IngressFailure:
            raise
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, OverflowError):
            raise IngressFailure() from None
        except Exception:
            raise IngressFailure(unavailable=True) from None


def _bare_health_probe(scope: Scope) -> bool:
    if (
        scope.get("method") not in {"GET", "HEAD"}
        or scope.get("path") not in HEALTH_PATHS
        or scope.get("query_string", b"")
    ):
        return False
    headers = [(name.lower(), value) for name, value in scope.get("headers", [])]
    lengths = [value for name, value in headers if name == b"content-length"]
    return not any(
        name in {b"authorization", b"cookie", b"transfer-encoding"} for name, _ in headers
    ) and lengths in ([], [b"0"])


class AuthenticatedIngressMiddleware:
    """Establish HTTPS from workload proof and preserve the server's client address.

    Workload identity is a reusable Bearer credential. The gateway must keep it
    private and build a fresh upstream request. Learner identity stays separate.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        verifier_factory: Callable[[], WorkloadVerifier],
        required: bool,
    ) -> None:
        self.app, self.verifier_factory, self.required = app, verifier_factory, required

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket" and self.required:
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        verified = False

        async def send_with_evidence(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != VERIFIED
                    and not (verified and key.lower() == b"cache-control")
                ]
                if verified:
                    headers.extend(((VERIFIED, b"1"), (b"cache-control", b"no-store")))
                message = {**message, "headers": headers}
            await send(message)

        proof = [
            (key.lower(), value)
            for key, value in scope.get("headers", [])
            if key.lower().startswith(_INGRESS_PREFIX)
        ]
        if not proof and (not self.required or _bare_health_probe(scope)):
            await self.app(scope, receive, send_with_evidence)
            return
        try:
            if len(proof) != 1 or proof[0][0] != AUTH:
                raise IngressFailure()
            authorization = proof[0][1]
            if not authorization.startswith(b"Bearer ") or len(authorization) > 16391:
                raise IngressFailure()
            token = authorization[7:].decode("ascii")
            if not _TOKEN.fullmatch(token):
                raise IngressFailure()
            verifier = self.verifier_factory()
            if not isinstance(verifier, WorkloadVerifier) or verifier.closed:
                raise IngressFailure(unavailable=True)
            identity = await verifier.verify_async(token)
            if verifier.closed:
                raise IngressFailure(unavailable=True)
            if verifier.clock() >= identity.expires_at:
                raise IngressFailure()
        except (IngressFailure, UnicodeError) as error:
            failure = error if isinstance(error, IngressFailure) else IngressFailure()
        except Exception:
            failure = IngressFailure(unavailable=True)
        else:
            verified = True
            scope = dict(scope)
            scope["scheme"] = "https"
            scope["headers"] = [
                (key, value) for key, value in scope.get("headers", []) if key.lower() != AUTH
            ]
            await self.app(scope, receive, send_with_evidence)
            return

        response = error_response(
            scope.get("state", {}).get("request_id", "unavailable"),
            failure.code,
            failure.message,
            failure.status_code,
        )
        await response(scope, receive, send_with_evidence)
