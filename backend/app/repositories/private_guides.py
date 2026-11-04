"""Persistence port for owned guide reservation, authorization facts and readback."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.schemas.private_guides import GuideContent, GuideCreate, GuideDetail


class PrivateGuideRepository(Protocol):
    def access(
        self, owner: UUID, issuer: str, subject: str
    ) -> tuple[bool, UUID | None, str | None, bool]: ...
    def reserve(
        self, owner: UUID, key: UUID, request: GuideCreate, now: datetime
    ) -> tuple[GuideDetail, bool]: ...
    def get(self, owner: UUID, identity: UUID, now: datetime) -> GuideDetail: ...
    def list(self, owner: UUID, now: datetime) -> tuple[GuideDetail, ...]: ...
    def finish(
        self,
        owner: UUID,
        identity: UUID,
        content: GuideContent | None,
        source: str | None,
        now: datetime,
        provenance: dict[str, str | None] | None = None,
    ) -> GuideDetail: ...
