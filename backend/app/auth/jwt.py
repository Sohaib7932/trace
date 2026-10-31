"""Supabase public-key verification. Untrusted headers only select a configured JWKS key."""

import json
from datetime import UTC, datetime
from threading import Lock
from typing import Any, Protocol
from uuid import UUID

import httpx2
import jwt
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from app.core.settings import Settings
from app.domain.accounts import VerifiedIdentity
from app.domain.clock import Clock, utc_now
from app.domain.learning import LearningError


class JwksSource(Protocol):
    def fetch(self) -> dict[str, Any]: ...


class HttpJwksSource:
    def __init__(self, url: str) -> None:
        self.url = url

    def fetch(self) -> dict[str, Any]:
        # No redirects, token-derived URLs, auth headers, or provider private keys.
        with (
            httpx2.Client(timeout=3, follow_redirects=False, trust_env=False) as client,
            client.stream("GET", self.url) as response,
        ):
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > 65536:
                    raise ValueError("JWKS response too large")
        value: Any = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError("Invalid JWKS")
        return value


class JwtVerifier:
    def __init__(
        self, settings: Settings, source: JwksSource | None = None, clock: Clock = utc_now
    ) -> None:
        self.settings, self.clock = settings, clock
        self.source = source or HttpJwksSource(settings.supabase_jwks_url)
        self._keys: dict[str, jwt.PyJWK] = {}
        self._expires = 0.0
        self._last_refresh = float("-inf")
        self._lock = Lock()

    def _key(self, kid: str) -> jwt.PyJWK:
        with self._lock:
            now = self.clock().timestamp()
            expired = now >= self._expires
            if expired and now - self._last_refresh < 5:
                raise LearningError(
                    "dependency_unavailable", "Authentication keys are unavailable. Retry shortly."
                )
            if expired or (kid not in self._keys and now - self._last_refresh >= 5):
                self._last_refresh = now
                try:
                    data = self.source.fetch()
                    raw_keys = data.get("keys")
                    if not isinstance(raw_keys, list) or not 1 <= len(raw_keys) <= 16:
                        raise ValueError("Asymmetric signing keys required")
                    keys: dict[str, jwt.PyJWK] = {}
                    for raw in raw_keys:
                        if not isinstance(raw, dict) or raw.get("alg") not in {"ES256", "RS256"}:
                            continue
                        name = raw.get("kid")
                        if (
                            not isinstance(name, str)
                            or not 1 <= len(name) <= 200
                            or name in keys
                            or raw.get("use", "sig") != "sig"
                            or raw.get("key_ops", ["verify"]) != ["verify"]
                            or any(field in raw for field in ("d", "p", "q", "k"))
                        ):
                            raise ValueError("Invalid public key")
                        key = jwt.PyJWK.from_dict(raw)
                        public = key.key
                        if not (
                            key.algorithm_name == "ES256"
                            and isinstance(public, ec.EllipticCurvePublicKey)
                            and isinstance(public.curve, ec.SECP256R1)
                            or key.algorithm_name == "RS256"
                            and isinstance(public, rsa.RSAPublicKey)
                            and public.key_size >= 2048
                        ):
                            raise ValueError("Invalid asymmetric key")
                        keys[name] = key
                    if not keys:
                        raise ValueError("Configure asymmetric signing keys in Supabase")
                    self._keys = keys
                    self._expires = now + self.settings.auth_jwks_cache_seconds
                except (httpx2.HTTPError, ValueError, TypeError, jwt.PyJWTError):
                    # Never use an expired cache after an outage. No exception/token is logged.
                    self._expires = 0
                    raise LearningError(
                        "dependency_unavailable",
                        "Authentication keys are unavailable. "
                        "Check provider configuration or retry.",
                    ) from None
            selected = self._keys.get(kid)
            if selected is None:
                raise LearningError("unauthenticated", "The sign-in token is invalid.")
            return selected

    def verify(self, token: str) -> VerifiedIdentity:
        if not self.settings.supabase_issuer:
            raise LearningError(
                "dependency_unavailable", "Account authentication is not configured."
            )
        try:
            if len(token) > 16384:
                raise ValueError("Token too large")
            header = jwt.get_unverified_header(token)
            alg, kid = header.get("alg"), header.get("kid")
            if (
                alg not in {"ES256", "RS256"}
                or not isinstance(kid, str)
                or not 1 <= len(kid) <= 200
                or header.get("crit")
                or header.get("typ", "JWT") != "JWT"
            ):
                raise ValueError("Invalid header")
            key = self._key(kid)
            if key.algorithm_name != alg:
                raise ValueError("Algorithm mismatch")
            claims = jwt.decode(
                token,
                key.key,
                algorithms=[alg],
                audience=self.settings.supabase_audience,
                issuer=self.settings.supabase_issuer,
                options={
                    "require": ["iss", "aud", "sub", "exp", "iat", "role"],
                    "verify_exp": False,
                    "verify_nbf": False,
                    "verify_iat": False,
                },
            )
            now = self.clock().timestamp()
            for name in ("exp", "iat", "nbf"):
                if name in claims and type(claims[name]) is not int:
                    raise ValueError("Invalid claim type")
            if (
                claims["exp"] <= now
                or claims["iat"] > now
                or claims.get("nbf", 0) > now
                or claims["exp"] <= claims["iat"]
                or claims["role"] != "authenticated"
                or claims.get("is_anonymous", False) is not False
                or not isinstance(claims["sub"], str)
                or str(UUID(claims["sub"])) != claims["sub"]
            ):
                raise ValueError("Invalid access claims")
            return VerifiedIdentity(
                claims["iss"], claims["sub"], datetime.fromtimestamp(claims["exp"], UTC)
            )
        except (jwt.PyJWTError, ValueError, TypeError, OverflowError, KeyError):
            raise LearningError(
                "unauthenticated", "Your sign-in session is invalid or expired. Sign in again."
            ) from None

    def authorization(self, value: str) -> VerifiedIdentity:
        parts = value.split(" ")
        if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
            raise LearningError(
                "unauthenticated", "A valid Bearer authorization header is required."
            )
        return self.verify(parts[1])
