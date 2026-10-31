from uuid import UUID

from app.domain.accounts import Account, AccountStatus, Role, VerifiedIdentity
from app.domain.clock import Clock, utc_now
from app.domain.learning import LearningError
from app.repositories.accounts import AccountRepository
from app.services.identity import credential_digest


class AccountService:
    def __init__(self, repository: AccountRepository, clock: Clock = utc_now) -> None:
        self.repository, self.clock = repository, clock

    def bootstrap(self, identity: VerifiedIdentity) -> Account:
        with self.repository.write() as store:
            return store.bootstrap(identity, self.clock())

    def limit(self, account: Account, action: str) -> None:
        # Commit the counter independently so rejected claims also consume their quota.
        with self.repository.write() as store:
            allowed = store.allow_action(account.id, action, self.clock())
        if not allowed:
            raise LearningError("rate_limited", "Too many account requests. Try again in a minute.")

    def status(self, account: Account, raw: str | None) -> AccountStatus:
        with self.repository.read() as store:
            owner = store.ownership(account.id)
            guest = (
                store.credential(credential_digest(raw)) if raw and 32 <= len(raw) <= 128 else None
            )
            available = bool(guest and guest.revoked_at is None and guest.expires_at > self.clock())
            return AccountStatus(account, owner.learner_id if owner else None, available)

    def learner(self, account: Account) -> UUID:
        account.require_role("learner")
        with self.repository.write() as store:
            owner = store.ownership(account.id)
            return owner.learner_id if owner else store.create_learner(account.id, self.clock())

    def claim(self, account: Account, raw: str | None, key: str) -> UUID:
        account.require_role("learner")
        self.limit(account, "claim")
        with self.repository.write() as store:
            owner = store.ownership(account.id)
            # A receipt only permits this user's exact retry after the cookie was cleared.
            if owner and owner.claim_key == key:
                return owner.learner_id
            if not raw or not 32 <= len(raw) <= 128:
                raise LearningError("unauthenticated", "A valid anonymous credential is required.")
            credential = store.credential(credential_digest(raw))
            if not credential or credential.revoked_at or credential.expires_at <= self.clock():
                raise LearningError(
                    "unauthenticated", "The anonymous credential is no longer valid."
                )
            if owner:
                raise LearningError(
                    "conflict",
                    "This account already owns another learner history. "
                    "Neither history was changed.",
                )
            store.claim(account.id, credential, key, self.clock())
            return credential.learner_id

    def grant(self, user_id: UUID, role: Role, operator: str, reason: str) -> bool:
        if (
            role not in {"creator", "admin"}
            or not (1 <= len(operator.strip()) <= 200)
            or not (1 <= len(reason.strip()) <= 1000)
        ):
            raise ValueError("An elevated role, operator and reason are required.")
        with self.repository.write() as store:
            return store.grant(user_id, role, operator.strip(), reason.strip(), self.clock())
