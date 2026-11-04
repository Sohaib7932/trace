"""Authenticated encryption for owner-bound GitHub user credentials only.

The independent key is configured privately by the App owner. Ciphertext is
never an API field; context binding rejects another owner's copied ciphertext.
"""

import json
from datetime import datetime
from uuid import UUID

from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.core.errors import ApplicationError
from app.repositories.github_projects import GitHubAuthorizationGrant


def reauthorize() -> ApplicationError:
    return ApplicationError(
        "github_reauthorization_required", "Reconnect GitHub to refresh access.", 409
    )


class GitHubCredentialVault:
    def __init__(self, key: SecretStr) -> None:
        self._cipher = Fernet(key.get_secret_value().encode("ascii"))

    def encrypt(
        self,
        owner: UUID,
        installation: int,
        user_id: int,
        token: SecretStr,
        expires_at: datetime,
    ) -> str:
        value = token.get_secret_value()
        if not value or len(value) > 512:
            raise reauthorize()
        payload = json.dumps(
            {
                "owner": str(owner),
                "installation": installation,
                "user": user_id,
                "token": value,
                "expires_at": expires_at.isoformat(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return self._cipher.encrypt(payload).decode("ascii")

    def decrypt(self, grant: GitHubAuthorizationGrant) -> SecretStr:
        if grant.token_ciphertext is None or len(grant.token_ciphertext) > 4096:
            raise reauthorize()
        try:
            payload = json.loads(self._cipher.decrypt(grant.token_ciphertext.encode("ascii")))
            if (
                not isinstance(payload, dict)
                or payload.get("owner") != str(grant.owner_id)
                or payload.get("installation") != grant.installation_id
                or payload.get("user") != grant.github_user_id
                or grant.credential_expires_at is None
                or payload.get("expires_at") != grant.credential_expires_at.isoformat()
                or not isinstance(payload.get("token"), str)
                or not 0 < len(payload["token"]) <= 512
            ):
                raise ValueError()
            return SecretStr(payload["token"])
        except Exception:
            raise reauthorize() from None
