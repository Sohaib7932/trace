"""Versioned authoritative retrieval port shared by file and durable knowledge."""

from typing import Protocol, runtime_checkable

from app.schemas.support import SupportMatch, SupportQuestion
from app.support.versioning import ApprovedSupportPassageVersion


class SupportSnapshot(Protocol):
    @property
    def available(self) -> bool: ...
    @property
    def manifest_sha256(self) -> str | None: ...
    def retrieve(self, question: SupportQuestion) -> tuple[SupportMatch, ...]: ...
    def resolve(self, match: SupportMatch) -> ApprovedSupportPassageVersion | None: ...
    def reconstruct(self, version: ApprovedSupportPassageVersion) -> SupportMatch | None: ...


@runtime_checkable
class VersionedSupportKnowledge(Protocol):
    def snapshot(self, *, audience: str = "public_customer") -> SupportSnapshot: ...
