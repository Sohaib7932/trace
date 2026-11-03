"""Pinned GitHub App REST adapter; never clone, execute, write repositories or follow URLs."""

import base64
import json
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
from pydantic import SecretStr

from app.core.errors import ApplicationError
from app.core.github_errors import unavailable
from app.core.github_settings import GitHubSettings
from app.schemas.github_projects import RepositoryView

_REQUEST_DEADLINE: ContextVar[float | None] = ContextVar("github_request_deadline", default=None)


def omitted_file() -> ApplicationError:
    return ApplicationError(
        "github_file_omitted", "This file exceeds supported ingestion bounds.", 422
    )


def github_id(value: object) -> int:
    if type(value) is not int or not 0 < value <= 2**63 - 1:
        raise unavailable()
    return value


class GitHubAppClient:
    def __init__(
        self, settings: GitHubSettings, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.settings = settings
        self.http = httpx.Client(
            transport=transport,
            timeout=5,
            follow_redirects=False,
            trust_env=False,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Accept-Encoding": "identity",
            },
        )

    def close(self) -> None:
        self.http.close()

    @contextmanager
    def deadline(self, remaining: float) -> Iterator[None]:
        marker = _REQUEST_DEADLINE.set(time.monotonic() + min(30, remaining))
        try:
            yield
        finally:
            _REQUEST_DEADLINE.reset(marker)

    def remaining_seconds(self) -> float:
        deadline = _REQUEST_DEADLINE.get()
        remaining = deadline - time.monotonic() if deadline is not None else 30.0
        if remaining <= 0:
            raise ApplicationError("github_timeout", "GitHub request timed out.", 504)
        return remaining

    def _json(
        self,
        method: str,
        path: str,
        token: SecretStr,
        *,
        body: dict[str, object] | None = None,
        oauth: bool = False,
    ) -> Any:
        if self.settings.mode != "enabled":
            raise unavailable()
        # No client-controlled host, redirect, request method or arbitrary route.
        host = "https://github.com" if oauth else "https://api.github.com"
        if oauth and (method != "POST" or path != "/login/oauth/access_token"):
            raise unavailable()
        if not path.startswith("/") or ".." in path or "#" in path:
            raise unavailable()
        try:
            with self.http.stream(
                method,
                host + path,
                headers={
                    "Authorization": "Bearer " + token.get_secret_value(),
                    "Accept": "application/json" if oauth else "application/vnd.github+json",
                },
                json=body,
                timeout=min(5.0, self.remaining_seconds()),
            ) as response:
                if response.status_code not in {200, 201}:
                    raise unavailable()
                if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                    # Reject before HTTPX can inflate attacker-controlled repository
                    # text beyond the bounded response budget.
                    raise unavailable()
                limit = 16384 if oauth else 262144
                wire = bytearray()
                for part in response.iter_bytes():
                    wire.extend(part)
                    self.remaining_seconds()
                    if len(wire) > limit:
                        if re.fullmatch(r"/repos/[^/]+/[^/]+/git/blobs/[0-9a-f]{40}", path):
                            raise omitted_file()
                        raise unavailable()
                return json.loads(wire)
        except ApplicationError:
            raise
        except Exception:
            raise unavailable() from None

    def app_token(self) -> SecretStr:
        now = datetime.now(UTC)
        try:
            return SecretStr(
                jwt.encode(
                    {
                        "iat": now - timedelta(seconds=30),
                        "exp": now + timedelta(minutes=5),
                        "iss": str(self.settings.app_id),
                    },
                    self.settings.private_key.get_secret_value(),
                    algorithm="RS256",
                )
            )
        except Exception:
            raise unavailable() from None

    def exchange(self, code: str) -> SecretStr:
        data = self._json(
            "POST",
            "/login/oauth/access_token",
            SecretStr(""),
            body={
                "client_id": self.settings.client_id,
                "client_secret": self.settings.client_secret.get_secret_value(),
                "code": code,
                "redirect_uri": self.settings.callback_url,
            },
            oauth=True,
        )
        token = data.get("access_token") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token or len(token) > 512:
            raise unavailable()
        return SecretStr(token)

    def user_id(self, token: SecretStr) -> int:
        result = self._json("GET", "/user", token)
        return github_id(result.get("id")) if isinstance(result, dict) else github_id(None)

    def validate_installation(self, installation_id: int) -> None:
        result = self._json("GET", f"/app/installations/{installation_id}", self.app_token())
        if not isinstance(result, dict):
            raise unavailable()
        permissions = result.get("permissions")
        if (
            result.get("id") != installation_id
            or result.get("app_id") != self.settings.app_id
            or result.get("repository_selection") != "selected"
            or result.get("suspended_at")
            or not isinstance(permissions, dict)
            or permissions.get("contents") != "read"
            or permissions.get("pull_requests") != "read"
            or any(value != "read" for value in permissions.values())
            or set(permissions) - {"contents", "metadata", "pull_requests"}
        ):
            raise ApplicationError(
                "github_permissions", "Use a selected-repository read-only installation.", 403
            )

    def accessible_repositories(
        self, token: SecretStr, installation_id: int
    ) -> list[RepositoryView]:
        result = self._json(
            "GET", f"/user/installations/{installation_id}/repositories?per_page=100", token
        )
        if not isinstance(result, dict) or not isinstance(result.get("repositories"), list):
            raise unavailable()
        rows = result["repositories"]
        total = result.get("total_count", len(rows))
        if type(total) is not int or not 0 <= total <= 100 or len(rows) > 100:
            raise ApplicationError("github_limit", "Select at most 100 repositories.", 422)
        repos = []
        for item in rows:
            if not isinstance(item, dict) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}",
                str(item.get("full_name", "")),
            ):
                raise unavailable()
            if type(item.get("private")) is not bool:
                raise unavailable()
            repos.append(
                RepositoryView(
                    repository_id=github_id(item.get("id")),
                    full_name=item["full_name"],
                    private=item["private"],
                )
            )
        return repos

    def repository_token(self, installation_id: int, repository_id: int) -> SecretStr:
        self.validate_installation(installation_id)
        result = self._json(
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            self.app_token(),
            body={
                "repository_ids": [repository_id],
                "permissions": {"contents": "read", "pull_requests": "read", "metadata": "read"},
            },
        )
        token = result.get("token") if isinstance(result, dict) else None
        if not isinstance(token, str) or not token or len(token) > 512:
            raise unavailable()
        return SecretStr(token)

    def commit(self, token: SecretStr, full_name: str, sha: str) -> dict[str, Any]:
        result = self._json("GET", f"/repos/{full_name}/commits/{sha}", token)
        if not isinstance(result, dict) or result.get("sha") != sha:
            raise unavailable()
        return result

    def pull_requests(self, token: SecretStr, full_name: str, sha: str) -> list[dict[str, Any]]:
        result = self._json("GET", f"/repos/{full_name}/commits/{sha}/pulls?per_page=5", token)
        if not isinstance(result, list) or len(result) > 5:
            raise unavailable()
        return result

    def content(
        self, token: SecretStr, full_name: str, path: str, sha: str, *, blob_sha: str
    ) -> str:
        # Read the actual blob identified by the pinned commit, never the
        # Contents API which may resolve a safe-looking symlink into a secret.
        if not re.fullmatch(r"[0-9a-f]{40}", blob_sha):
            raise unavailable()
        result = self._json("GET", f"/repos/{full_name}/git/blobs/{blob_sha}", token)
        if (
            not isinstance(result, dict)
            or result.get("sha") != blob_sha
            or type(result.get("size")) is not int
            or result["size"] < 0
        ):
            raise unavailable()
        if result["size"] > 32768 or result.get("encoding") != "base64":
            raise omitted_file()
        try:
            raw = base64.b64decode(result["content"].replace("\n", ""), validate=True)
        except Exception:
            raise unavailable() from None
        if len(raw) > 32768:
            raise omitted_file()
        try:
            return raw.decode("utf-8")
        except UnicodeError:
            raise omitted_file() from None
