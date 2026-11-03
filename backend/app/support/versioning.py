"""Internal immutable provenance for the operator-reviewed support manifest.

These are not HTTP schemas or a document ingestion API. Existing authored
passages are the chunks: no normalization, splitting or overlap is performed.
"""

import hashlib
import json
from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from app.domain.lesson_spec.fields import Digest, Items, LocalId, Value, Version
from app.repositories.support_knowledge import ApprovedSupportKnowledge
from app.schemas.support import SupportDocument, SupportMatch, SupportQuestion
from app.schemas.support_readiness import ReadinessCode
from app.services.support_readiness import support_document_digest

type SnapshotIssueCode = (
    ReadinessCode
    | Literal["package_unavailable", "invalid_package", "unsupported_audience", "source_revoked"]
)


def canonical_digest(value: object) -> str:
    """Hash explicit internal metadata without rewriting approved source copy."""
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


class SupportSnapshotIssue(Value):
    model_config = ConfigDict(revalidate_instances="always")

    code: SnapshotIssueCode
    source_id: LocalId | None = None


class ApprovedSupportPassageVersion(Value):
    """Identity of exact approved text, independent of an index's stored text."""

    model_config = ConfigDict(revalidate_instances="always")

    source_id: LocalId
    revision: Version
    document_sha256: Digest
    passage_id: LocalId
    passage_sha256: Digest
    chunk_id: Digest
    chunker_version: Literal["authored-passages-v1"] = "authored-passages-v1"
    chunk_ordinal: int = Field(ge=0, le=7)
    overlap_characters: int = Field(default=0, ge=0, le=0)
    audience: Literal["public_customer"] = "public_customer"

    @model_validator(mode="after")
    def identity_integrity(self) -> "ApprovedSupportPassageVersion":
        expected = canonical_digest(self.model_dump(exclude={"chunk_id"}, mode="json"))
        if self.chunk_id != expected:
            raise ValueError("Chunk identity must bind exact source-version provenance")
        return self


class ApprovedSupportSourceVersion(Value):
    model_config = ConfigDict(revalidate_instances="always")

    revision: Version
    document_sha256: Digest
    reviewed_by: LocalId
    reviewed_at: AwareDatetime
    valid_until: AwareDatetime
    audience: Literal["public_customer"] = "public_customer"
    document: SupportDocument = Field(repr=False)
    passages: Items[ApprovedSupportPassageVersion] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def source_integrity(self) -> "ApprovedSupportSourceVersion":
        if (
            self.document.approval != "approved_customer_safe"
            or support_document_digest(self.document) != self.document_sha256
            or self.valid_until <= self.reviewed_at
            or len(self.passages) != len(self.document.passages)
        ):
            raise ValueError("Version provenance must match approved source content and review")
        for ordinal, (passage, version) in enumerate(
            zip(self.document.passages, self.passages, strict=True)
        ):
            if (
                version.source_id != self.document.source_id
                or version.revision != self.revision
                or version.document_sha256 != self.document_sha256
                or version.passage_id != passage.passage_id
                or version.chunk_ordinal != ordinal
                or version.passage_sha256
                != hashlib.sha256(passage.text.encode("utf-8")).hexdigest()
            ):
                raise ValueError("Passage provenance must match exact authored text")
        return self


class SupportKnowledgeSnapshot(Value):
    """One immutable eligible manifest, with bounded safe readiness diagnostics.

    A snapshot is authoritative only for its evaluation instant. Callers releasing
    a provider result must reconstruct its references through a *fresh* snapshot.
    Review expiry or revocation cannot be bypassed by retaining an older object.
    """

    model_config = ConfigDict(revalidate_instances="always")

    schema_version: Literal["support-knowledge-snapshot-v1"] = "support-knowledge-snapshot-v1"
    status: Literal["prepared", "unavailable"]
    evaluated_at: AwareDatetime
    package_revision: Version | None = None
    manifest_sha256: Digest | None = None
    sources: Items[ApprovedSupportSourceVersion] = Field(default=(), max_length=32, repr=False)
    issues: Items[SupportSnapshotIssue] = Field(default=(), max_length=65)

    @model_validator(mode="after")
    def manifest_integrity(self) -> "SupportKnowledgeSnapshot":
        if self.status == "unavailable":
            if self.sources or self.manifest_sha256 is not None or not self.issues:
                raise ValueError("Unavailable snapshots cannot expose eligible source content")
            return self
        if not self.sources or self.issues or self.package_revision is None:
            raise ValueError("Prepared snapshots require a complete issue-free approved manifest")
        source_ids = tuple(source.document.source_id for source in self.sources)
        if source_ids != tuple(sorted(set(source_ids))):
            raise ValueError("Manifest sources must be unique and canonically ordered")
        ApprovedSupportKnowledge(tuple(source.document for source in self.sources))
        if any(
            source.revision != self.package_revision
            or source.reviewed_at > self.evaluated_at
            or source.valid_until <= self.evaluated_at
            for source in self.sources
        ):
            raise ValueError("Every source must be current and pinned to the package revision")
        if self.manifest_sha256 != self.content_digest():
            raise ValueError("Manifest digest must bind the approved source-version metadata")
        return self

    def content_digest(self) -> str:
        return canonical_digest(
            {
                "schema_version": self.schema_version,
                "package_revision": self.package_revision,
                "sources": [source.model_dump(mode="json") for source in self.sources],
            }
        )

    @property
    def available(self) -> bool:
        return self.status == "prepared"

    def retrieve(self, question: SupportQuestion) -> tuple[SupportMatch, ...]:
        return ApprovedSupportKnowledge(tuple(source.document for source in self.sources)).retrieve(
            question
        )

    def resolve(self, match: SupportMatch) -> ApprovedSupportPassageVersion | None:
        """Hydrate an index result only if all its fields match authoritative copy."""
        checked = SupportMatch.model_validate(match.model_dump(warnings=False))
        for source in self.sources:
            if source.document.source_id != checked.source_id:
                continue
            for passage, version in zip(source.document.passages, source.passages, strict=True):
                if (
                    checked.passage_id == passage.passage_id
                    and checked.text == passage.text
                    and checked.title == source.document.title
                    and checked.approval == source.document.approval
                ):
                    return version
        return None

    def reconstruct(self, version: ApprovedSupportPassageVersion) -> SupportMatch | None:
        """Reconstruct exact citations; forged, changed or missing identities abstain."""
        checked = ApprovedSupportPassageVersion.model_validate(version.model_dump(warnings=False))
        for source in self.sources:
            for passage, current in zip(source.document.passages, source.passages, strict=True):
                if current == checked:
                    return SupportMatch(
                        source_id=source.document.source_id,
                        title=source.document.title,
                        passage_id=passage.passage_id,
                        text=passage.text,
                        approval=source.document.approval,
                    )
        return None


def version_source(
    document: SupportDocument,
    *,
    revision: str,
    reviewed_by: str,
    reviewed_at: AwareDatetime,
    valid_until: AwareDatetime,
) -> ApprovedSupportSourceVersion:
    """Wrap already eligible copy; this helper does not establish owner approval."""
    document_digest = support_document_digest(document)
    passages = []
    for ordinal, passage in enumerate(document.passages):
        identity = {
            "source_id": document.source_id,
            "revision": revision,
            "document_sha256": document_digest,
            "passage_id": passage.passage_id,
            "passage_sha256": hashlib.sha256(passage.text.encode("utf-8")).hexdigest(),
            "chunker_version": "authored-passages-v1",
            "chunk_ordinal": ordinal,
            "overlap_characters": 0,
            "audience": "public_customer",
        }
        passages.append(
            ApprovedSupportPassageVersion.model_validate(
                {**identity, "chunk_id": canonical_digest(identity)}
            )
        )
    return ApprovedSupportSourceVersion(
        revision=revision,
        document_sha256=document_digest,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        valid_until=valid_until,
        document=document,
        passages=tuple(passages),
    )
