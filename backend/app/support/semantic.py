"""Experimental genuine-vector ranking with current-source hydration and safe fallback.

Nonproduction resources can opt in; production rejects nonlexical ranking pending
quality approval. Mock-vector scores establish neither answers nor correctness.
"""

import math
from typing import Literal, Self

from pydantic import Field, model_validator

from app.ai.embeddings import BoundedEmbeddingClient
from app.domain.lesson_spec.fields import Digest, Items, LocalId, Value
from app.schemas.embeddings import UnitEmbedding
from app.schemas.support import SupportMatch, SupportQuestion
from app.support.archive import ArchivedSupportSnapshot
from app.support.contracts import SupportSnapshot, VersionedSupportKnowledge
from app.support.embedding_index import EmbeddingIndex, IndexSourceSnapshot
from app.support.versioning import (
    ApprovedSupportPassageVersion,
    SupportKnowledgeSnapshot,
    canonical_digest,
)


def _checked_snapshot(snapshot: SupportSnapshot) -> IndexSourceSnapshot:
    if isinstance(snapshot, SupportKnowledgeSnapshot):
        return SupportKnowledgeSnapshot.model_validate(snapshot.model_dump(warnings=False))
    if isinstance(snapshot, ArchivedSupportSnapshot):
        return ArchivedSupportSnapshot.model_validate(snapshot.model_dump(warnings=False))
    raise ValueError("Semantic retrieval requires a strict approved snapshot implementation")


class SemanticRetrievalSettings(Value):
    mode: Literal["lexical", "semantic", "hybrid"] = "lexical"
    allow_unreviewed_experiment: bool = False
    lexical_weight: float = Field(default=1.0, ge=0, le=4)
    semantic_weight: float = Field(default=1.0, ge=0, le=4)
    rrf_constant: int = Field(default=60, ge=1, le=1000)
    minimum_cosine: float = Field(default=0.0, ge=-1, le=1)

    @model_validator(mode="after")
    def positive_weight(self) -> Self:
        if self.mode == "hybrid" and self.lexical_weight + self.semantic_weight == 0:
            raise ValueError("Hybrid ranking requires a positive weight")
        return self


class RankedPassage(Value):
    chunk_id: Digest
    passage_id: LocalId
    lexical_rank: int | None = Field(default=None, ge=1, le=3)
    semantic_rank: int | None = Field(default=None, ge=1, le=3)
    cosine: float | None = Field(default=None, ge=-1, le=1)
    fusion_score: float = Field(ge=0, le=8)


class BoundRetrievalOutcome(Value):
    snapshot: IndexSourceSnapshot = Field(repr=False)
    matches: Items[SupportMatch] = Field(default=(), max_length=3, repr=False)
    versions: Items[ApprovedSupportPassageVersion] = Field(default=(), max_length=3)
    rankings: Items[RankedPassage] = Field(default=(), max_length=3)
    mode: Literal["lexical", "semantic", "hybrid", "unavailable"]
    index_sha256: Digest | None = None
    space_sha256: Digest | None = None
    configuration_sha256: Digest | None = None
    fallback_reason: (
        Literal["not_approved", "index_unavailable", "embedding_unavailable", "source_changed"]
        | None
    ) = None
    query_vector: UnitEmbedding | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def source_bound(self) -> Self:
        if len(self.matches) != len(self.versions) or len(
            {version.chunk_id for version in self.versions}
        ) != len(self.versions):
            raise ValueError("Retrieval matches must carry exact source versions")
        if tuple(self.snapshot.reconstruct(version) for version in self.versions) != self.matches:
            raise ValueError("Only authoritative snapshot copy may be hydrated")
        if tuple((rank.chunk_id, rank.passage_id) for rank in self.rankings) != tuple(
            (version.chunk_id, version.passage_id) for version in self.versions
        ):
            raise ValueError("Ranking receipts must identify the exact returned source versions")
        if self.mode == "unavailable" and self.matches:
            raise ValueError("Unavailable retrieval cannot release sources")
        return self

    def safe_receipt(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "manifest_sha256": self.snapshot.manifest_sha256,
            "index_sha256": self.index_sha256,
            "space_sha256": self.space_sha256,
            "configuration_sha256": self.configuration_sha256,
            "fallback_reason": self.fallback_reason,
            "rankings": [rank.model_dump(mode="json") for rank in self.rankings],
        }


def _lexical(
    snapshot: IndexSourceSnapshot,
    question: SupportQuestion,
    reason: Literal["not_approved", "index_unavailable", "embedding_unavailable"] | None = None,
) -> BoundRetrievalOutcome:
    matches = snapshot.retrieve(question) if snapshot.available else ()
    versions = tuple(snapshot.resolve(match) for match in matches)
    if any(version is None for version in versions):
        raise ValueError("Lexical result failed source hydration")
    checked_versions = tuple(version for version in versions if version is not None)
    return BoundRetrievalOutcome(
        snapshot=snapshot,
        matches=matches,
        versions=checked_versions,
        mode="lexical" if snapshot.available else "unavailable",
        fallback_reason=reason,
        rankings=tuple(
            RankedPassage(
                chunk_id=version.chunk_id,
                passage_id=version.passage_id,
                lexical_rank=rank,
                fusion_score=1 / rank,
            )
            for rank, version in enumerate(checked_versions, 1)
        ),
    )


def rank_with_vector(
    snapshot: IndexSourceSnapshot,
    index: EmbeddingIndex,
    question: SupportQuestion,
    query: UnitEmbedding,
    settings: SemanticRetrievalSettings,
) -> BoundRetrievalOutcome:
    """Pure deterministic exact cosine/fusion; actual vectors must come from receipts."""
    snapshot = _checked_snapshot(snapshot)
    checked = SemanticRetrievalSettings.model_validate(settings.model_dump(warnings=False))
    index = EmbeddingIndex.model_validate(index.model_dump(warnings=False))
    query = UnitEmbedding.model_validate(query.model_dump(warnings=False))
    question = SupportQuestion.model_validate(question.model_dump(warnings=False))
    if not snapshot.available:
        return BoundRetrievalOutcome(snapshot=snapshot, mode="unavailable")
    if checked.mode == "lexical":
        return _lexical(snapshot, question)
    if not checked.allow_unreviewed_experiment:
        return _lexical(snapshot, question, "not_approved")
    if not index.matches_snapshot(snapshot):
        return _lexical(snapshot, question, "index_unavailable")
    lexical = snapshot.retrieve(question)
    lexical_ranks = {match.passage_id: rank for rank, match in enumerate(lexical, 1)}
    semantic = sorted(
        (
            (
                max(
                    -1.0,
                    min(
                        1.0,
                        math.fsum(
                            a * b for a, b in zip(query.values, passage.vector.values, strict=True)
                        ),
                    ),
                ),
                passage,
            )
            for passage in index.passages
        ),
        key=lambda item: (-item[0], item[1].version.source_id, item[1].version.passage_id),
    )
    semantic = [item for item in semantic if item[0] >= checked.minimum_cosine][:3]
    semantic_ranks = {
        passage.version.passage_id: rank for rank, (_, passage) in enumerate(semantic, 1)
    }
    cosines = {passage.version.passage_id: cosine for cosine, passage in semantic}
    selected = set(semantic_ranks)
    if checked.mode == "hybrid":
        selected |= lexical_ranks.keys()
    versions = {passage.version.passage_id: passage.version for passage in index.passages}
    rankings = []
    for passage_id in selected:
        lex_rank, sem_rank = lexical_ranks.get(passage_id), semantic_ranks.get(passage_id)
        score = (
            (checked.lexical_weight / (checked.rrf_constant + lex_rank) if lex_rank else 0)
            + (checked.semantic_weight / (checked.rrf_constant + sem_rank) if sem_rank else 0)
            if checked.mode == "hybrid"
            else 1 / sem_rank
            if sem_rank
            else 0
        )
        if score <= 0:
            continue
        rankings.append(
            RankedPassage(
                chunk_id=versions[passage_id].chunk_id,
                passage_id=passage_id,
                lexical_rank=lex_rank,
                semantic_rank=sem_rank,
                cosine=cosines.get(passage_id),
                fusion_score=score,
            )
        )
    rankings.sort(
        key=lambda rank: (-rank.fusion_score, versions[rank.passage_id].source_id, rank.passage_id)
    )
    chosen = tuple(versions[rank.passage_id] for rank in rankings[:3])
    matches = tuple(snapshot.reconstruct(version) for version in chosen)
    if any(match is None for match in matches):
        raise ValueError("Semantic candidate failed source hydration")
    return BoundRetrievalOutcome(
        snapshot=snapshot,
        mode=checked.mode,
        matches=tuple(match for match in matches if match is not None),
        versions=chosen,
        rankings=tuple(rankings[:3]),
        index_sha256=index.index_sha256,
        space_sha256=index.metadata.profile.space_sha256,
        configuration_sha256=canonical_digest(checked.model_dump(mode="json")),
        query_vector=query,
    )


class SemanticSupportKnowledge:
    """Internal optional adapter. Request-bound outcomes avoid re-embedding at release."""

    def __init__(
        self,
        knowledge: VersionedSupportKnowledge,
        client: BoundedEmbeddingClient,
        index: EmbeddingIndex | None,
        settings: SemanticRetrievalSettings | None = None,
    ) -> None:
        self.knowledge, self.client, self.index = knowledge, client, index
        self.settings = settings or SemanticRetrievalSettings()

    @property
    def available(self) -> bool:
        return _checked_snapshot(self.knowledge.snapshot()).available

    def retrieve_with_snapshot(
        self,
        question: SupportQuestion,
        *,
        timeout_seconds: float | None = None,
        subject: str | None = None,
    ) -> BoundRetrievalOutcome:
        question = SupportQuestion.model_validate(question.model_dump(warnings=False))
        snapshot = _checked_snapshot(self.knowledge.snapshot())
        if not snapshot.available or self.settings.mode == "lexical":
            return _lexical(snapshot, question)
        if not self.settings.allow_unreviewed_experiment:
            return _lexical(snapshot, question, "not_approved")
        if self.index is None or not self.index.matches_snapshot(snapshot):
            return _lexical(snapshot, question, "index_unavailable")
        if self.client.settings.mode in {"mock", "gemini_free"} and self.index.metadata.source != (
            "ai" if self.client.settings.mode == "gemini_free" else "test_fixture"
        ):
            return _lexical(snapshot, question, "index_unavailable")
        result = self.client.embed(
            (question.question,), "query", timeout_seconds=timeout_seconds, subject=subject
        )
        if result.status != "success" or result.profile != self.index.metadata.profile:
            return _lexical(snapshot, question, "embedding_unavailable")
        fresh = _checked_snapshot(self.knowledge.snapshot())
        if not fresh.available or fresh.manifest_sha256 != snapshot.manifest_sha256:
            return BoundRetrievalOutcome(
                snapshot=fresh, mode="unavailable", fallback_reason="source_changed"
            )
        return rank_with_vector(snapshot, self.index, question, result.vectors[0], self.settings)

    def revalidate(self, outcome: BoundRetrievalOutcome) -> bool:
        """Fresh source revalidation only; this method performs zero embedding RPCs."""
        checked = BoundRetrievalOutcome.model_validate(outcome.model_dump(warnings=False))
        fresh = _checked_snapshot(self.knowledge.snapshot())
        return (
            checked.mode != "unavailable"
            and fresh.available
            and fresh.manifest_sha256 == checked.snapshot.manifest_sha256
            and tuple(fresh.reconstruct(version) for version in checked.versions) == checked.matches
            and (
                checked.index_sha256 is None
                or self.index is not None
                and self.index.index_sha256 == checked.index_sha256
            )
            and (
                checked.configuration_sha256 is None
                or checked.configuration_sha256
                == canonical_digest(self.settings.model_dump(mode="json"))
            )
        )

    def retrieve(self, question: SupportQuestion) -> tuple[SupportMatch, ...]:
        # Generic legacy port compatibility; production release should retain
        # retrieve_with_snapshot's outcome and call revalidate instead of re-embedding.
        return self.retrieve_with_snapshot(question).matches
