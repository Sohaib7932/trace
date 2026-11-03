"""Independent source revisions in a strict durable-manifest projection (V2)."""

from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from app.domain.knowledge import (
    KnowledgeEvent,
    KnowledgeManifest,
    KnowledgeRevision,
    lexical_index_digest,
    source_chunks,
)
from app.domain.lesson_spec.fields import Digest, Items, Value
from app.repositories.support_knowledge import ApprovedSupportKnowledge
from app.schemas.support import SupportDocument, SupportMatch, SupportQuestion
from app.support.versioning import ApprovedSupportPassageVersion, SupportSnapshotIssue


class ArchivedSupportSourceVersion(Value):
    model_config = ConfigDict(revalidate_instances="always")
    record: KnowledgeRevision = Field(repr=False)
    approval: KnowledgeEvent
    passages: Items[ApprovedSupportPassageVersion] = Field(min_length=1, max_length=8)
    lexical_index_sha256: Digest

    @property
    def document(self) -> SupportDocument:
        return self.record.document()

    @property
    def revision(self) -> str:
        return self.record.revision

    @property
    def valid_until(self) -> AwareDatetime | None:
        return self.approval.valid_until

    @model_validator(mode="after")
    def exact_revision(self) -> "ArchivedSupportSourceVersion":
        if (
            self.approval.revision_id != self.record.id
            or self.approval.action not in {"approve", "adopt_existing_review"}
            or self.approval.reviewed_document_sha256 != self.record.normalized_sha256
            or self.passages != source_chunks(self.record)
            or self.lexical_index_sha256 != lexical_index_digest(self.record)
        ):
            raise ValueError("Archived source versions must match their exact approved revision")
        return self


class ArchivedSupportSnapshot(Value):
    model_config = ConfigDict(revalidate_instances="always")
    schema_version: Literal["support-knowledge-snapshot-v2"] = "support-knowledge-snapshot-v2"
    status: Literal["prepared", "unavailable"]
    evaluated_at: AwareDatetime
    publication_sequence: int = Field(default=-1, ge=-1)
    manifest: KnowledgeManifest | None = None
    sources: Items[ArchivedSupportSourceVersion] = Field(default=(), max_length=32, repr=False)
    issues: Items[SupportSnapshotIssue] = Field(default=(), max_length=65)

    @property
    def manifest_sha256(self) -> str | None:
        return self.manifest.content_sha256 if self.manifest is not None else None

    @property
    def available(self) -> bool:
        return self.status == "prepared"

    @model_validator(mode="after")
    def exact_manifest(self) -> "ArchivedSupportSnapshot":
        if self.status == "unavailable":
            if self.sources or self.manifest is not None or not self.issues:
                raise ValueError("Unavailable archive snapshots cannot expose eligible sources")
            return self
        manifest = self.manifest
        if not self.sources or manifest is None or self.issues or self.publication_sequence < 0:
            raise ValueError("An archive snapshot requires an explicitly published manifest")
        ids = tuple(source.document.source_id for source in self.sources)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("Archived manifest sources must be unique and ordered")
        if (
            manifest.revision_ids != tuple(source.record.id for source in self.sources)
            or manifest.revision_sha256
            != tuple(source.record.content_sha256 for source in self.sources)
            or manifest.approval_sha256
            != tuple(source.approval.content_sha256 for source in self.sources)
            or manifest.chunk_ids
            != tuple(p.chunk_id for source in self.sources for p in source.passages)
            or manifest.lexical_index_sha256
            != tuple(source.lexical_index_sha256 for source in self.sources)
            or any(
                source.valid_until is None
                or source.valid_until <= self.evaluated_at
                or source.approval.created_at > self.evaluated_at
                for source in self.sources
            )
        ):
            raise ValueError("Archive projection must bind exact current approved manifest members")
        ApprovedSupportKnowledge(tuple(source.document for source in self.sources))
        return self

    def retrieve(self, question: SupportQuestion) -> tuple[SupportMatch, ...]:
        return ApprovedSupportKnowledge(tuple(source.document for source in self.sources)).retrieve(
            question
        )

    def resolve(self, match: SupportMatch) -> ApprovedSupportPassageVersion | None:
        checked = SupportMatch.model_validate(match.model_dump(warnings=False))
        for source in self.sources:
            for passage, version in zip(source.document.passages, source.passages, strict=True):
                if checked == SupportMatch(
                    source_id=source.document.source_id,
                    title=source.document.title,
                    passage_id=passage.passage_id,
                    text=passage.text,
                    approval=source.document.approval,
                ):
                    return version
        return None

    def reconstruct(self, version: ApprovedSupportPassageVersion) -> SupportMatch | None:
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
