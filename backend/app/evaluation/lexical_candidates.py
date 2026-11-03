"""Offline ranking experiment; not registered in production retrieval or AI resources.

Predeclared candidate: binary term frequency, BM25 IDF and length normalization,
k1=1.2, b=0.75. Reuses the exact baseline token sets, positive scores, top3 bound
and source/passage tie order. Parameters are fixed before evaluating either split.
There is no trained model, synonym list, embedding or external dependency.
"""

import math
from collections import Counter

from app.evaluation.support_retrieval import (
    RetrievalDataset,
    _knowledge,
    _sufficient,
    _summary,
    validate_dataset,
)
from app.repositories.support_knowledge import ApprovedSupportKnowledge, _words
from app.schemas.support import SupportDocument, SupportMatch, SupportQuestion
from app.support.knowledge import SupportCorpusPackage
from app.support.versioning import canonical_digest

CANDIDATE_ID = "offline-binary-bm25-k1-1-2-b-0-75-v1"


class BinaryBm25Knowledge(ApprovedSupportKnowledge):
    """Explicit, bounded approved-source injection for offline comparison only."""

    def __init__(self, documents: tuple[SupportDocument, ...]) -> None:
        super().__init__(documents)
        self._entries = tuple(
            (
                document,
                passage,
                _words(document.title + " " + passage.text),
            )
            for document in self._documents
            for passage in document.passages
        )
        self._document_frequency = Counter(
            token for _, _, words in self._entries for token in words
        )
        self._average_length = (
            sum(len(words) for _, _, words in self._entries) / len(self._entries)
            if self._entries
            else 0.0
        )

    def retrieve(self, question: SupportQuestion) -> tuple[SupportMatch, ...]:
        checked = SupportQuestion.model_validate(question.model_dump(warnings=False))
        query = _words(checked.question)
        if not self._entries:
            return ()
        ranked: list[tuple[float, SupportMatch]] = []
        n, k1, b = len(self._entries), 1.2, 0.75
        for document, passage, words in self._entries:
            normalizer = (k1 + 1) / (1 + k1 * (1 - b + b * len(words) / self._average_length))
            score = sum(
                math.log(
                    1
                    + (n - self._document_frequency[token] + 0.5)
                    / (self._document_frequency[token] + 0.5)
                )
                * normalizer
                for token in sorted(query & words)
            )
            if score > 0:
                ranked.append(
                    (
                        score,
                        SupportMatch(
                            source_id=document.source_id,
                            title=document.title,
                            passage_id=passage.passage_id,
                            text=passage.text,
                            approval=document.approval,
                        ),
                    )
                )
        ranked.sort(key=lambda entry: (-entry[0], entry[1].source_id, entry[1].passage_id))
        return tuple(match for _, match in ranked[:3])


def compare_lexical_candidates(
    dataset: RetrievalDataset, package: SupportCorpusPackage
) -> dict[str, object]:
    validate_dataset(dataset, package)
    baseline = _knowledge(dataset, package, "approved")
    candidate = BinaryBm25Knowledge(tuple(document.document() for document in package.documents))
    result: dict[str, object] = {
        "schema_version": "support-lexical-comparison-v1",
        "candidate_id": CANDIDATE_ID,
        "parameters_predeclared": {"binary_term_frequency": True, "k1": 1.2, "b": 0.75},
        "label_status": dataset.label_status,
        "dataset_version": dataset.dataset_version,
        "dataset_canonical_sha256": canonical_digest(dataset.model_dump(mode="json")),
        "corpus_canonical_sha256": dataset.corpus_canonical_sha256,
        "evaluation_time": dataset.evaluation_time.isoformat(),
        "production_retriever_changed": False,
        "semantic_or_provider_performance_measured": False,
    }
    strategies: dict[str, object] = {}
    for name, knowledge in (("baseline", baseline), ("candidate", candidate)):
        rows: list[dict[str, object]] = []
        for case in dataset.cases:
            if case.expected != "answer":
                continue
            ranked = [
                match.passage_id
                for match in knowledge.retrieve(SupportQuestion(question=case.question))
            ]
            relevant = set(case.relevant_passage_ids)
            row: dict[str, object] = {
                "case_id": case.case_id,
                "split": case.split,
                "expected": "answer",
                # Only the retrieval block is returned. No selector is simulated here.
                "status": "unsupported",
                "citation_count": 0,
                "relevant_citation_count": 0,
                "sufficient_answer": False,
                "relevant_count": len(relevant),
                "required_group_count": len(case.required_evidence_groups),
                "ranked_passage_ids": ranked,
            }
            for k in (1, 2, 3):
                top = ranked[:k]
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
        strategies[name] = {
            "overall": _summary(rows, (1, 2, 3))["retrieval"],
            "by_split": {
                split: _summary([row for row in rows if row["split"] == split], (1, 2, 3))[
                    "retrieval"
                ]
                for split in ("development", "heldout")
            },
            "cases": rows,
        }
    result["strategies"] = strategies
    return result
