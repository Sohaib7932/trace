import hashlib
import secrets
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from app.domain.learning import Credential, LearningError
from app.repositories.learning import LearningRepository

COOKIE_NAME = "trace_learner"
COOKIE_PATH = "/api/v1"


def credential_digest(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class IdentityService:
    def __init__(self, repository: LearningRepository, lifetime_seconds: int) -> None:
        self.repository, self.lifetime_seconds = repository, lifetime_seconds

    def authenticate(self, raw: str | None) -> Credential:
        if raw and 32 <= len(raw) <= 128:
            with self.repository.read() as store:
                credential = store.credential(credential_digest(raw))
                if (
                    credential
                    and credential.revoked_at is None
                    and credential.expires_at > datetime.now(UTC)
                ):
                    return credential
        raise LearningError("unauthenticated", "A valid anonymous learner credential is required.")

    def bootstrap(self, raw: str | None) -> tuple[Credential, str | None]:
        try:
            credential = self.authenticate(raw)
            now = datetime.now(UTC)
            if credential.expires_at - now > timedelta(seconds=self.lifetime_seconds / 2):
                return credential, None
            assert raw is not None
            with self.repository.write() as store:
                now = datetime.now(UTC)
                current = store.credential(credential_digest(raw))
                if current is None or current.revoked_at is not None or current.expires_at <= now:
                    raise LearningError("unauthenticated", "The credential is no longer valid.")
                if current.expires_at - now <= timedelta(seconds=self.lifetime_seconds / 2):
                    current = replace(
                        current, expires_at=now + timedelta(seconds=self.lifetime_seconds)
                    )
                    store.renew(current.id, current.expires_at)
                return current, raw  # Only reissue the existing HttpOnly cookie, never JSON.
        except LearningError as exc:
            if exc.code != "unauthenticated":
                raise
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(seconds=self.lifetime_seconds)
        with self.repository.write() as store:
            return store.create_identity(credential_digest(token), expires_at), token

    def revoke(self, credential: Credential) -> None:
        with self.repository.write() as store:
            store.revoke(credential.id, datetime.now(UTC))
