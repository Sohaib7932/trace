"""Derived immutable vector caches; approved source snapshots remain citation authority."""

from datetime import datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from app.domain.lesson_spec.fields import Digest, Items, Value
from app.schemas.embeddings import (
    EmbeddingBatchResult,
    EmbeddingIndexMetadata,
    UnitEmbedding,
    text_digest,
)
from app.schemas.support import SupportMatch
from app.support.archive import ArchivedSupportSnapshot
from app.support.vector_json import strict_vector_json
from app.support.versioning import (
    ApprovedSupportPassageVersion,
    SupportKnowledgeSnapshot,
    canonical_digest,
)

type IndexSourceSnapshot = SupportKnowledgeSnapshot | ArchivedSupportSnapshot


def render_document(match: SupportMatch) -> str:
    return match.title + "\n\n" + match.text


class IndexedPassage(Value):
    version: ApprovedSupportPassageVersion
    space_sha256: Digest
    input_sha256: Digest
    vector: UnitEmbedding = Field(repr=False)


class EmbeddingIndex(Value):
    metadata: EmbeddingIndexMetadata
    manifest_sha256: Digest
    passages: Items[IndexedPassage] = Field(min_length=1, max_length=256, repr=False)
    index_sha256: Digest

    def content_digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json", exclude={"index_sha256"}))

    @model_validator(mode="after")
    def index_integrity(self) -> Self:
        identities = [passage.version.chunk_id for passage in self.passages]
        if (
            len(identities) != len(set(identities))
            or any(
                passage.space_sha256 != self.metadata.profile.space_sha256
                for passage in self.passages
            )
            or self.index_sha256 != self.content_digest()
        ):
            raise ValueError("Index identities, vector space and digest must agree")
        return self

    def matches_snapshot(self, snapshot: IndexSourceSnapshot) -> bool:
        if not snapshot.available or snapshot.manifest_sha256 != self.manifest_sha256:
            return False
        expected = tuple(version for source in snapshot.sources for version in source.passages)
        if tuple(passage.version for passage in self.passages) != expected:
            return False
        for passage in self.passages:
            match = snapshot.reconstruct(passage.version)
            if match is None or text_digest(render_document(match)) != passage.input_sha256:
                return False
        return True


def document_inputs(snapshot: IndexSourceSnapshot) -> tuple[str, ...]:
    snapshot = type(snapshot).model_validate(snapshot.model_dump(warnings=False))
    if not snapshot.available:
        raise ValueError("Only a currently eligible snapshot can be indexed")
    return tuple(
        source.document.title + "\n\n" + passage.text
        for source in snapshot.sources
        for passage in source.document.passages
    )


def compose_index(
    snapshot: IndexSourceSnapshot,
    embeddings: EmbeddingBatchResult,
    *,
    created_at: datetime,
    scope: Literal["benchmark", "production_candidate"] = "benchmark",
) -> EmbeddingIndex:
    checked = EmbeddingBatchResult.model_validate(embeddings.model_dump(warnings=False))
    inputs = document_inputs(snapshot)
    if (
        checked.status != "success"
        or checked.purpose != "document"
        or checked.input_sha256 != tuple(text_digest(text) for text in inputs)
        or snapshot.manifest_sha256 is None
        or checked.source == "unavailable"
    ):
        raise ValueError("Indexing requires exact successful document embedding receipts")
    versions = tuple(version for source in snapshot.sources for version in source.passages)
    metadata = EmbeddingIndexMetadata(
        created_at=created_at,
        profile=checked.profile,
        source=checked.source,
        observed_provider_revision=checked.observed_provider_revision,
        scope=scope,
    )
    passages = tuple(
        IndexedPassage(
            version=version,
            space_sha256=checked.profile.space_sha256,
            input_sha256=input_sha,
            vector=vector,
        )
        for version, input_sha, vector in zip(
            versions, checked.input_sha256, checked.vectors, strict=True
        )
    )
    fields = {
        "metadata": metadata.model_dump(mode="json"),
        "manifest_sha256": snapshot.manifest_sha256,
        "passages": [passage.model_dump(mode="json") for passage in passages],
    }
    return EmbeddingIndex(
        metadata=metadata,
        manifest_sha256=snapshot.manifest_sha256,
        passages=passages,
        index_sha256=canonical_digest(fields),
    )


class FileEmbeddingIndex:
    """Explicit operator paths only; no file discovery, client paths or ingestion."""

    @staticmethod
    def load(path: Path) -> EmbeddingIndex:
        if path.stat().st_size > 8388608:
            raise ValueError("Embedding index exceeds its byte limit")
        raw = path.read_text(encoding="utf-8")
        strict_vector_json(raw, max_bytes=8388608)
        return EmbeddingIndex.model_validate_json(raw)

    @staticmethod
    def write_new(path: Path, index: EmbeddingIndex) -> None:
        checked = EmbeddingIndex.model_validate(index.model_dump(warnings=False))
        raw = checked.model_dump_json(indent=2) + "\n"
        if len(raw.encode("utf-8")) > 8388608:
            raise ValueError("Embedding index exceeds its byte limit")
        with path.open("x", encoding="utf-8", newline="\n") as target:
            target.write(raw)
