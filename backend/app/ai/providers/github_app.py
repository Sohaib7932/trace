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

from app.ai.github_projects import GitHubUserToken
from app.core.ai_privacy import public_ai_question
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
        headers = {
            "Accept": "application/json" if oauth else "application/vnd.github+json",
        }
        # The OAuth exchange authenticates with its existing JSON body. An empty
        # `Bearer ` header is invalid on the wire and must not be sent there.
        # Ordinary REST calls still require their server-held bearer credential.
        try:
            if not oauth:
                headers["Authorization"] = "Bearer " + token.get_secret_value()
            with self.http.stream(
                method,
                host + path,
                headers=headers,
                json=body,
                timeout=min(5.0, self.remaining_seconds()),
            ) as response:
                if response.status_code == 429 or (
                    response.status_code == 403
                    and (
                        response.headers.get("X-RateLimit-Remaining") == "0"
                        or "Retry-After" in response.headers
                    )
                ):
                    raise ApplicationError(
                        "github_rate_limited",
                        "GitHub request allowance is exhausted. Try later.",
                        429,
                    )
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
        return self.exchange_authorization(code).access_token

    def exchange_authorization(self, code: str) -> GitHubUserToken:
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
        expiry = data.get("expires_in", 8 * 3600)
        if type(expiry) is not int or expiry <= 0:
            raise unavailable()
        return GitHubUserToken(access_token=SecretStr(token), expires_in=min(expiry, 8 * 3600))

    def user_id(self, token: SecretStr) -> int:
        result = self._json("GET", "/user", token)
        return github_id(result.get("id")) if isinstance(result, dict) else github_id(None)

    def accessible_installations(self, token: SecretStr) -> tuple[int, ...]:
        """Discover this App through the user's proof, including organization access."""
        # Numeric pagination is bounded and never follows provider-supplied URLs.
        # Account IDs need not match the user: collaborators and organization
        # members can have explicit access through this user-token endpoint.
        found: list[int] = []
        seen: set[int] = set()
        total: int | None = None
        for page in range(1, 5):
            result = self._json("GET", f"/user/installations?per_page=25&page={page}", token)
            if not isinstance(result, dict) or not isinstance(result.get("installations"), list):
                raise unavailable()
            rows = result["installations"]
            count = result.get("total_count")
            if type(count) is not int or not 0 <= count <= 100 or len(rows) > 25:
                raise unavailable()
            if total is not None and total != count:
                raise unavailable()
            total = count
            for row in rows:
                if not isinstance(row, dict):
                    raise unavailable()
                identity, app_id = github_id(row.get("id")), github_id(row.get("app_id"))
                if identity in seen:
                    raise unavailable()
                seen.add(identity)
                if app_id == self.settings.app_id:
                    found.append(identity)
            if len(seen) > total:
                raise unavailable()
            if len(seen) == total:
                return tuple(found)
            if len(rows) != 25:
                raise unavailable()
        raise unavailable()

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
        # Explicit numeric pagination; never follow an upstream Link URL.
        rows: list[dict[str, Any]] = []
        total = 0
        for page in range(1, 5):
            result = self._json(
                "GET",
                f"/user/installations/{installation_id}/repositories?per_page=25&page={page}",
                token,
            )
            if not isinstance(result, dict) or not isinstance(result.get("repositories"), list):
                raise unavailable()
            found = result["repositories"]
            count = result.get("total_count", len(found))
            if type(count) is not int or not 0 <= count <= 100 or len(found) > 25:
                raise ApplicationError("github_limit", "Select at most 100 repositories.", 422)
            if page > 1 and total != count:
                raise unavailable()
            total = count
            rows.extend(found)
            if len(rows) >= total:
                break
            if len(found) < 25:
                raise unavailable()
        if len(rows) != total:
            raise unavailable()
        repos = []
        identifiers: set[int] = set()
        for item in rows:
            if not isinstance(item, dict) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}",
                str(item.get("full_name", "")),
            ):
                raise unavailable()
            if type(item.get("private")) is not bool:
                raise unavailable()
            try:
                public_ai_question(item["full_name"])
            except ValueError:
                raise unavailable() from None
            identifier = github_id(item.get("id"))
            if identifier in identifiers:
                raise unavailable()
            identifiers.add(identifier)
            repos.append(
                RepositoryView(
                    repository_id=identifier,
                    full_name=item["full_name"],
                    private=item["private"],
                )
            )
        return repos

    @staticmethod
    def _repository_name(full_name: str) -> None:
        if not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", full_name
        ):
            raise unavailable()

    @staticmethod
    def _sha(sha: str) -> None:
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise unavailable()

    def repository(self, token: SecretStr, full_name: str) -> dict[str, Any]:
        self._repository_name(full_name)
        result = self._json("GET", f"/repos/{full_name}", token)
        if not isinstance(result, dict):
            raise unavailable()
        return result

    def tree(self, token: SecretStr, full_name: str, sha: str) -> dict[str, Any]:
        self._repository_name(full_name)
        self._sha(sha)
        # Deliberately nonrecursive: service traverses a bounded safe directory queue.
        result = self._json("GET", f"/repos/{full_name}/git/trees/{sha}", token)
        if (
            not isinstance(result, dict)
            or result.get("sha") != sha
            or not isinstance(result.get("tree"), list)
            or type(result.get("truncated")) is not bool
        ):
            raise unavailable()
        return result

    def history_page(
        self, token: SecretStr, full_name: str, sha: str, page: int
    ) -> list[dict[str, Any]]:
        self._repository_name(full_name)
        self._sha(sha)
        if type(page) is not int or not 1 <= page <= 3:
            raise unavailable()
        result = self._json(
            "GET", f"/repos/{full_name}/commits?sha={sha}&per_page=10&page={page}", token
        )
        if not isinstance(result, list) or len(result) > 10:
            raise unavailable()
        if any(not isinstance(item, dict) for item in result):
            raise unavailable()
        return result

    def commit_page(self, token: SecretStr, full_name: str, sha: str, page: int) -> dict[str, Any]:
        self._repository_name(full_name)
        self._sha(sha)
        if type(page) is not int or not 1 <= page <= 3:
            raise unavailable()
        result = self._json(
            "GET", f"/repos/{full_name}/commits/{sha}?per_page=25&page={page}", token
        )
        if (
            not isinstance(result, dict)
            or result.get("sha") != sha
            or not isinstance(result.get("files"), list)
            or len(result["files"]) > 25
        ):
            raise unavailable()
        return result

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
        # Installation tokens are opaque. GitHub's stateless JWT format is
        # longer than the former 512-character assumption. Bound the HTTP
        # header without imposing a provider token grammar or decoding it.
        if (
            not isinstance(token, str)
            or not token
            or len(token) > 4096
            or any(not 33 <= ord(character) <= 126 for character in token)
        ):
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
