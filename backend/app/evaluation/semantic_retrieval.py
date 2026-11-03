"""Reproducible cached-vector evaluation, distinct from mock protocol validation."""

import json
from datetime import datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from app.ai.embeddings import BoundedEmbeddingClient, EmbeddingTransportError
from app.domain.lesson_spec.fields import Digest, Value
from app.evaluation.support_retrieval import (
    RetrievalDataset,
    _knowledge,
    _sufficient,
    _summary,
    validate_dataset,
)
from app.schemas.embeddings import EmbeddingBatchResult, text_digest
from app.schemas.support import SupportQuestion
from app.support.embedding_index import EmbeddingIndex, compose_index, document_inputs
from app.support.knowledge import ReviewedSupportKnowledge, SupportCorpusPackage
from app.support.semantic import SemanticRetrievalSettings, rank_with_vector
from app.support.vector_json import strict_vector_json
from app.support.versioning import canonical_digest


class SemanticEvaluationCache(Value):
    schema_version: Literal["semantic-evaluation-cache-v1"] = "semantic-evaluation-cache-v1"
    dataset_sha256: Digest
    corpus_sha256: Digest
    document_index: EmbeddingIndex = Field(repr=False)
    queries: EmbeddingBatchResult = Field(repr=False)
    cache_sha256: Digest

    def content_digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json", exclude={"cache_sha256"}))

    @model_validator(mode="after")
    def cache_integrity(self) -> Self:
        if (
            self.queries.status != "success"
            or self.queries.purpose != "query"
            or self.document_index.metadata.profile != self.queries.profile
            or self.document_index.metadata.source != self.queries.source
            or self.document_index.metadata.scope != "benchmark"
            or self.cache_sha256 != self.content_digest()
        ):
            raise ValueError("Evaluation vectors, source and cache fingerprint must agree")
        return self

    @classmethod
    def load(cls, path: Path) -> "SemanticEvaluationCache":
        if path.stat().st_size > 16777216:
            raise ValueError("Semantic evaluation cache exceeds its byte limit")
        raw = path.read_text(encoding="utf-8")
        strict_vector_json(raw, max_bytes=16777216)
        return cls.model_validate_json(raw)

    def write_new(self, path: Path) -> None:
        checked = SemanticEvaluationCache.model_validate(self.model_dump(warnings=False))
        raw = checked.model_dump_json() + "\n"
        if len(raw.encode("utf-8")) > 16777216:
            raise ValueError("Semantic evaluation cache exceeds its byte limit")
        with path.open("x", encoding="utf-8", newline="\n") as target:
            target.write(raw)


def create_evaluation_cache(
    dataset: RetrievalDataset,
    package: SupportCorpusPackage,
    client: BoundedEmbeddingClient,
    *,
    now: datetime,
) -> SemanticEvaluationCache:
    """Exactly two online standard RPCs; caller must explicitly authorize live mode.

    Mock clients are permitted only to test the cache mechanics; their source is
    preserved as test_fixture and cannot establish a genuine semantic result.
    """
    validate_dataset(dataset, package)
    current = ReviewedSupportKnowledge(clock=lambda: now, loader=lambda: package).snapshot()
    if not current.available:
        raise ValueError("Live indexing requires currently reviewed eligible public sources")
    if len(dataset.cases) > 100:
        raise ValueError("This bounded evaluation accepts at most 100 public questions")
    documents = client.embed(document_inputs(current), "document")
    if documents.status != "success":
        raise EmbeddingTransportError(documents.error_code or "invalid_response")
    index = compose_index(current, documents, created_at=now)
    questions = tuple(case.question for case in dataset.cases)
    queries = client.embed(questions, "query")
    if queries.status != "success":
        raise EmbeddingTransportError(queries.error_code or "invalid_response")
    fields = {
        "schema_version": "semantic-evaluation-cache-v1",
        "dataset_sha256": canonical_digest(dataset.model_dump(mode="json")),
        "corpus_sha256": dataset.corpus_canonical_sha256,
        "document_index": index.model_dump(mode="json"),
        "queries": queries.model_dump(mode="json"),
    }
    return SemanticEvaluationCache.model_validate_json(
        json.dumps(fields | {"cache_sha256": canonical_digest(fields)})
    )


def evaluate_semantic_cache(
    dataset: RetrievalDataset,
    package: SupportCorpusPackage,
    cache: SemanticEvaluationCache,
    *,
    minimum_cosine: float = 0.0,
    lexical_weight: float = 1.0,
    semantic_weight: float = 1.0,
) -> dict[str, object]:
    validate_dataset(dataset, package)
    cache = SemanticEvaluationCache.model_validate(cache.model_dump(warnings=False))
    snapshot = ReviewedSupportKnowledge(
        clock=lambda: dataset.evaluation_time, loader=lambda: package
    ).snapshot()
    if (
        cache.dataset_sha256 != canonical_digest(dataset.model_dump(mode="json"))
        or cache.corpus_sha256 != dataset.corpus_canonical_sha256
        or not cache.document_index.matches_snapshot(snapshot)
        or cache.queries.input_sha256 != tuple(text_digest(case.question) for case in dataset.cases)
    ):
        raise ValueError("Cached vectors do not match this pinned dataset and eligible corpus")
    strategies: dict[str, object] = {}
    for mode in ("lexical", "semantic", "hybrid"):
        config = SemanticRetrievalSettings.model_validate(
            {
                "mode": mode,
                "allow_unreviewed_experiment": True,
                "minimum_cosine": minimum_cosine,
                "lexical_weight": lexical_weight,
                "semantic_weight": semantic_weight,
            }
        )
        rows: list[dict[str, object]] = []
        for case, vector in zip(dataset.cases, cache.queries.vectors, strict=True):
            knowledge = _knowledge(dataset, package, case.source_state)
            if not isinstance(knowledge, ReviewedSupportKnowledge):
                raise ValueError("Benchmark source fixtures require reviewed snapshots")
            current = knowledge.snapshot()
            outcome = rank_with_vector(
                current,
                cache.document_index,
                SupportQuestion(question=case.question),
                vector,
                config,
            )
            ranked = [match.passage_id for match in outcome.matches]
            sufficient = (
                next(
                    (group for group in case.sufficient_evidence_sets if set(group) <= set(ranked)),
                    (),
                )
                if case.expected == "answer"
                else ()
            )
            status = (
                "unavailable"
                if outcome.mode == "unavailable"
                else "answered"
                if sufficient
                else "unsupported"
                if ranked
                else "no_sources"
            )
            row: dict[str, object] = {
                "case_id": case.case_id,
                "split": case.split,
                "expected": case.expected,
                "status": status,
                "relevant_count": len(case.relevant_passage_ids),
                "required_group_count": len(case.required_evidence_groups),
                "citation_count": len(sufficient),
                "relevant_citation_count": len(sufficient),
                "sufficient_answer": _sufficient(case, set(sufficient)),
                "citation_integrity": all(
                    current.resolve(match) is not None for match in outcome.matches
                ),
                "ranked_passage_ids": ranked,
                "retrieval_receipt": outcome.safe_receipt(),
            }
            for k in (1, 2, 3):
                top, relevant = ranked[:k], set(case.relevant_passage_ids)
                row[f"returned_at_{k}"] = len(top)
                row[f"hits_at_{k}"] = len(set(top) & relevant)
                row[f"reciprocal_rank_at_{k}"] = next(
                    (1 / rank for rank, passage in enumerate(top, 1) if passage in relevant), 0.0
                )
                row[f"sufficient_at_{k}"] = _sufficient(case, set(top))
                row[f"covered_groups_at_{k}"] = sum(
                    bool(set(top) & set(group)) for group in case.required_evidence_groups
                )
            rows.append(row)
        summary = _summary(rows, (1, 2, 3))
        abstaining = [row for row in rows if row["status"] in {"unsupported", "no_sources"}]
        correct_abstaining = sum(row["expected"] == "abstain" for row in abstaining)
        strategies[mode] = {
            "configuration": config.model_dump(mode="json"),
            "overall": summary,
            "oracle_abstention_precision": correct_abstaining / len(abstaining)
            if abstaining
            else None,
            "by_split": {
                split: _summary([row for row in rows if row["split"] == split], (1, 2, 3))
                for split in ("development", "heldout")
            },
            "cases": rows,
        }
    return {
        "schema_version": "semantic-retrieval-evaluation-v1",
        "cache_sha256": cache.cache_sha256,
        "dataset_sha256": cache.dataset_sha256,
        "corpus_sha256": cache.corpus_sha256,
        "space_sha256": cache.document_index.metadata.profile.space_sha256,
        "index_sha256": cache.document_index.index_sha256,
        "profile": cache.document_index.metadata.profile.model_dump(mode="json"),
        "genuine_semantic_vectors": cache.queries.source == "ai",
        "label_status": dataset.label_status,
        "model_selector_semantics_measured": False,
        "selection_layer": "deterministic engineering-label oracle; not Gemini selection",
        "production_activation": "disabled pending independent review and quality gates",
        "strategies": strategies,
    }
