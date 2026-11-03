"""Owned private guides; no publication, executable grading or learner history mutation."""

import hashlib
from collections.abc import Callable
from uuid import UUID

from app.ai.private_guides import GuideGenerator
from app.domain.accounts import AuthenticatedAccount
from app.domain.clock import Clock, utc_now
from app.domain.learning import LearningError
from app.repositories.private_guides import PrivateGuideRepository
from app.schemas.private_guides import GuideContent, GuideCreate, GuideDetail, GuideSummary


class PrivateGuideService:
    def __init__(
        self,
        repository: PrivateGuideRepository,
        generator: GuideGenerator,
        clock: Clock = utc_now,
        *,
        remaining_seconds: Callable[[], float] | None = None,
    ) -> None:
        self.repository, self.generator, self.clock = repository, generator, clock
        self.remaining_seconds = remaining_seconds

    def _authorize(self, auth: AuthenticatedAccount) -> UUID:
        if auth.identity.expires_at <= self.clock():
            raise LearningError("unauthenticated", "Account authorization expired.")
        exists, linked, status, learner = self.repository.access(
            auth.account.id, auth.identity.issuer, auth.identity.subject
        )
        if not exists or linked != auth.account.id:
            raise LearningError("unauthenticated", "Account authorization changed.")
        if status != "active" or not learner:
            raise LearningError("forbidden", "Guide access is unavailable.")
        return auth.account.id

    def create(self, auth: AuthenticatedAccount, key: UUID, body: GuideCreate) -> GuideDetail:
        request = GuideCreate.model_validate(body.model_dump(warnings=False))
        owner = self._authorize(auth)
        reserved, created = self.repository.reserve(owner, key, request, self.clock())
        if not created:
            return reserved
        try:
            timeout = min(20.0, self.remaining_seconds()) if self.remaining_seconds else 10.0
            if timeout <= 0:
                raise TimeoutError("Guide deadline exceeded")
            result = self.generator.generate(
                request,
                subject="private-guide:" + hashlib.sha256(str(owner).encode()).hexdigest(),
                timeout_seconds=timeout,
            )
            content = (
                GuideContent.model_validate(result[0].model_dump(warnings=False))
                if result
                else None
            )
            source = result[1] if result else None
            if source not in {None, "ai", "test_fixture"}:
                content, source = None, None
        except Exception:
            content, source = None, None
        try:
            self._authorize(auth)
        except LearningError:
            self.repository.finish(owner, reserved.id, None, None, self.clock())
            raise
        return self.repository.finish(
            owner,
            reserved.id,
            content,
            source,
            self.clock(),
            provenance=getattr(self.generator, "provenance", None),
        )

    def get(self, auth: AuthenticatedAccount, identity: UUID) -> GuideDetail:
        return self.repository.get(self._authorize(auth), identity, self.clock())

    def list(self, auth: AuthenticatedAccount) -> tuple[GuideSummary, ...]:
        return tuple(
            GuideSummary.model_validate(
                {
                    key: value
                    for key, value in item.model_dump(warnings=False).items()
                    if key in GuideSummary.model_fields
                }
            )
            for item in self.repository.list(self._authorize(auth), self.clock())
        )
