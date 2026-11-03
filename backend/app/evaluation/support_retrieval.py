"""Pinned public-source retrieval benchmark and deterministic selection-contract probes.

The oracle knows engineering reference labels. Its scores are an upper bound on
selection given retrieval, not measured Gemini understanding or wording quality.
No application resources, credentials, provider transport or database are loaded.
"""

from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from app.ai.json_output import strict_json_object
from app.domain.lesson_spec.fields import Digest, Items, LocalId, Value, Version
from app.repositories.support_knowledge import SupportKnowledge
from app.schemas.support import (
    SupportMatch,
    SupportQuestion,
    SupportResponse,
    SupportSelection,
    SupportSelectionResult,
)
from app.services.support import SupportService
from app.support.knowledge import (
    ReviewedSupportKnowledge,
    SupportCorpusPackage,
    load_corpus_package,
    support_corpus_digest,
)
from app.support.versioning import canonical_digest

type Category = Literal[
    "exact_keyword",
    "paraphrase",
    "conceptual",
    "multipart",
    "multi_passage",
    "ambiguous",
    "outside_corpus",
    "outdated",
    "injection",
    "unsupported_policy_action",
]
type SourceState = Literal["approved", "expired", "draft", "missing", "digest_mismatch"]
type Expected = Literal["answer", "abstain", "unavailable"]
type Mode = Literal[
    "oracle",
    "unsupported",
    "first_retrieved",
    "unknown_reference",
    "unretrieved_reference",
    "exception",
    "timeout",
    "none",
    "malformed",
]


class RetrievalCase(Value):
    case_id: LocalId
    intent_family: LocalId
    split: Literal["development", "heldout"]
    categories: Items[Category] = Field(min_length=1, max_length=10)
    question: str = Field(min_length=1, max_length=500)
    source_state: SourceState
    expected: Expected
    relevant_passage_ids: Items[LocalId] = Field(max_length=19)
    sufficient_evidence_sets: Items[Items[LocalId]] = Field(max_length=8)
    required_evidence_groups: Items[Items[LocalId]] = Field(max_length=8)
    forbidden_passage_ids: Items[LocalId] = Field(max_length=19)
    rationale: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def consistent_labels(self) -> Self:
        SupportQuestion(question=self.question)
        for sequence in (self.categories, self.relevant_passage_ids, self.forbidden_passage_ids):
            if len(sequence) != len(set(sequence)):
                raise ValueError("Evaluation labels must be distinct")
        relevant = set(self.relevant_passage_ids)
        if relevant & set(self.forbidden_passage_ids):
            raise ValueError("Relevant passages cannot also be forbidden")
        if self.expected == "answer":
            if self.source_state != "approved" or not relevant or not self.sufficient_evidence_sets:
                raise ValueError("Answer labels require eligible sources and sufficient evidence")
            for group in (*self.sufficient_evidence_sets, *self.required_evidence_groups):
                if not group or len(group) != len(set(group)) or not set(group) <= relevant:
                    raise ValueError("Evidence groups must contain distinct relevant passages")
            for sufficient in self.sufficient_evidence_sets:
                if len(sufficient) > 3 or not all(
                    set(sufficient) & set(group) for group in self.required_evidence_groups
                ):
                    raise ValueError("Sufficient sets must satisfy all required groups within top3")
        elif relevant or self.sufficient_evidence_sets or self.required_evidence_groups:
            raise ValueError("Abstention/unavailable labels cannot claim sufficient evidence")
        if (self.expected == "unavailable") != (self.source_state != "approved"):
            raise ValueError("Unavailable source fixtures must be labelled separately")
        return self


class RetrievalDataset(Value):
    schema_version: Literal["support-retrieval-evaluation-v1"]
    dataset_version: Version
    label_status: Literal["engineering_reference_pending_independent_review"]
    label_author: Literal["trace-engineering"]
    production_approved: Literal[False]
    corpus_schema_version: Literal["support-corpus-v1"]
    corpus_revision: Version
    corpus_canonical_sha256: Digest
    document_digests: dict[LocalId, Digest] = Field(min_length=1, max_length=32)
    evaluation_time: AwareDatetime
    retriever_id: Literal["approved-support-lexical-overlap-top3-v1"]
    cases: Items[RetrievalCase] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def isolated_splits(self) -> Self:
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("Evaluation case IDs must be unique")
        families: dict[str, str] = {}
        for case in self.cases:
            if families.setdefault(case.intent_family, case.split) != case.split:
                raise ValueError("An intent family cannot cross development/heldout splits")
        return self


def corpus_digest(package: SupportCorpusPackage) -> str:
    return support_corpus_digest(package)


def load_dataset(path: Path) -> RetrievalDataset:
    """Load an explicitly chosen offline test dataset, never production support copy."""
    if path.stat().st_size > 524288:
        raise ValueError("Evaluation dataset exceeds its byte limit")
    raw = path.read_text(encoding="utf-8")
    strict_json_object(raw, max_bytes=524288)
    return RetrievalDataset.model_validate_json(raw)


def validate_dataset(dataset: RetrievalDataset, package: SupportCorpusPackage) -> None:
    if (
        dataset.corpus_schema_version != package.schema_version
        or dataset.corpus_revision != package.revision
        or dataset.corpus_canonical_sha256 != corpus_digest(package)
        or dataset.document_digests != package.document_digests
        or package.revoked_source_ids
    ):
        raise ValueError("Dataset corpus identity or digest does not match the reviewed package")
    knowledge = ReviewedSupportKnowledge(
        clock=lambda: dataset.evaluation_time, loader=lambda: package
    )
    if not knowledge.available:
        raise ValueError("The pinned baseline corpus is not eligible at evaluation time")
    ids = {passage.passage_id for doc in package.documents for passage in doc.passages}
    for case in dataset.cases:
        if not (set(case.relevant_passage_ids) | set(case.forbidden_passage_ids)) <= ids:
            raise ValueError("Dataset references a passage outside its pinned corpus")


def _knowledge(
    dataset: RetrievalDataset, package: SupportCorpusPackage, state: SourceState
) -> SupportKnowledge:
    if state == "missing":

        def missing() -> SupportCorpusPackage:
            raise FileNotFoundError("Synthetic missing-source fixture")

        return ReviewedSupportKnowledge(clock=lambda: dataset.evaluation_time, loader=missing)
    snapshot = package
    at = dataset.evaluation_time
    if state == "expired":
        assert package.valid_until is not None
        at = package.valid_until + timedelta(seconds=1)
    elif state == "draft":
        snapshot = package.model_copy(update={"review_status": "draft"})
    elif state == "digest_mismatch":
        snapshot = package.model_copy(
            update={"document_digests": dict.fromkeys(package.document_digests, "0" * 64)}
        )
    return ReviewedSupportKnowledge(clock=lambda: at, loader=lambda: snapshot)


def _sufficient(case: RetrievalCase, ids: set[str]) -> bool:
    return (
        case.expected == "answer"
        and not ids & set(case.forbidden_passage_ids)
        and any(set(group) <= ids for group in case.sufficient_evidence_sets)
        and all(ids & set(group) for group in case.required_evidence_groups)
    )


def _supported_answer(case: RetrievalCase, cited: set[str]) -> bool:
    return _sufficient(case, cited) and cited <= set(case.relevant_passage_ids)


class ReferenceSelector:
    """Deterministic oracle or intentionally bad selector; never a real model."""

    def __init__(
        self, case: RetrievalCase, mode: Mode = "oracle", *, unretrieved_id: str | None = None
    ) -> None:
        self.case, self.mode = case, mode
        self.unretrieved_id = unretrieved_id

    def select(
        self, question: SupportQuestion, passages: tuple[SupportMatch, ...], *, subject: str
    ) -> SupportSelectionResult | None:
        if self.mode == "exception":
            raise RuntimeError("Synthetic provider failure")
        if self.mode == "timeout":
            raise TimeoutError("Synthetic provider timeout")
        if self.mode == "none":
            return None
        if self.mode == "malformed":
            # Exercise strict result revalidation without weakening the production schema.
            return SupportSelectionResult(
                selection=SupportSelection(status="unsupported", passage_ids=()),
                source="test_fixture",
            ).model_copy(update={"selection": {"status": "invalid"}})
        selected: tuple[str, ...] = ()
        if self.mode == "unknown_reference":
            selected = ("benchmark-unknown-reference",)
        elif self.mode == "unretrieved_reference":
            selected = (self.unretrieved_id or "benchmark-unretrieved-reference",)
        elif self.mode == "first_retrieved":
            selected = (passages[0].passage_id,)
        elif self.mode == "oracle" and self.case.expected == "answer":
            available = {passage.passage_id for passage in passages}
            selected = next(
                (group for group in self.case.sufficient_evidence_sets if set(group) <= available),
                (),
            )
        return SupportSelectionResult(
            selection=SupportSelection(
                status="answered" if selected else "unsupported", passage_ids=selected
            ),
            source="test_fixture",
        )


def ratio(numerator: int | float, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _citation_integrity(response: SupportResponse, matches: tuple[SupportMatch, ...]) -> bool:
    allowed = {match.passage_id: match for match in matches}
    return all(
        reference.passage_id in allowed
        and reference.source_id == allowed[reference.passage_id].source_id
        and reference.source_name == allowed[reference.passage_id].title
        and reference.quote == allowed[reference.passage_id].text
        for reference in response.references
    )


def _summary(rows: list[dict[str, object]], ks: tuple[int, ...]) -> dict[str, object]:
    answerable = [row for row in rows if row["expected"] == "answer"]
    abstentions = [row for row in rows if row["expected"] == "abstain"]
    answered = [row for row in rows if row["status"] == "answered"]
    citations = sum(_count(row, "citation_count") for row in answered)
    relevant_citations = sum(_count(row, "relevant_citation_count") for row in answered)
    valid_citations = sum(
        _count(row, "citation_count") for row in answered if row["citation_integrity"]
    )
    supported = sum(row["sufficient_answer"] is True for row in answered)
    correct_abstentions = sum(row["status"] in {"no_sources", "unsupported"} for row in abstentions)
    unavailable = [row for row in rows if row["status"] == "unavailable"]
    retrieval: dict[str, object] = {}
    for k in ks:
        retrieved_counts = [_count(row, f"returned_at_{k}") for row in answerable]
        hits = [_count(row, f"hits_at_{k}") for row in answerable]
        relevant = [_count(row, "relevant_count") for row in answerable]
        reciprocal = [_number(row, f"reciprocal_rank_at_{k}") for row in answerable]
        sufficient_count = sum(row[f"sufficient_at_{k}"] is True for row in answerable)
        groups = sum(_count(row, "required_group_count", default=0) for row in answerable)
        covered_groups = sum(_count(row, f"covered_groups_at_{k}", default=0) for row in answerable)
        retrieval[str(k)] = {
            "answerable_cases": len(answerable),
            "relevant_passage_label_count": sum(relevant),
            "relevant_retrieved_count": sum(hits),
            "returned_passage_count": sum(retrieved_counts),
            "precision_fixed_k_denominator": k * len(answerable),
            "reciprocal_rank_sum": sum(reciprocal),
            "sufficient_evidence_count": sufficient_count,
            "required_evidence_group_count": groups,
            "covered_required_group_count": covered_groups,
            "required_evidence_group_coverage": ratio(covered_groups, groups),
            "macro_recall": ratio(
                sum(hit / gold for hit, gold in zip(hits, relevant, strict=True)), len(answerable)
            ),
            "macro_precision_fixed_k": ratio(sum(hits), k * len(answerable)),
            "micro_precision_returned": ratio(sum(hits), sum(retrieved_counts)),
            "mrr": ratio(sum(reciprocal), len(answerable)),
            "sufficient_evidence_rate": ratio(sufficient_count, len(answerable)),
        }
    return {
        "cases": len(rows),
        "expected_answer_cases": len(answerable),
        "expected_abstention_cases": len(abstentions),
        "expected_unavailable_cases": sum(row["expected"] == "unavailable" for row in rows),
        "retrieval": retrieval,
        "oracle_selection": {
            "answered_count": len(answered),
            "supported_answer_count": supported,
            "answer_support_accuracy": ratio(supported, len(answered)),
            "structural_citation_integrity": ratio(valid_citations, citations),
            "citation_count": citations,
            "valid_citation_count": valid_citations,
            "gold_relevant_citation_count": relevant_citations,
            "gold_relevant_citation_precision": ratio(relevant_citations, citations),
            "correct_semantic_abstention_count": correct_abstentions,
            "abstention_accuracy": ratio(correct_abstentions, len(abstentions)),
            "false_abstention_count": sum(
                row["status"] in {"no_sources", "unsupported"} for row in answerable
            ),
            "false_abstention_rate": ratio(
                sum(row["status"] in {"no_sources", "unsupported"} for row in answerable),
                len(answerable),
            ),
            "unsupported_answer_count": len(answered) - supported,
            "unsupported_answer_rate": ratio(len(answered) - supported, len(answered)),
            "false_answer_on_abstention_rate": ratio(
                sum(row["status"] == "answered" for row in abstentions), len(abstentions)
            ),
            "unavailable_count": len(unavailable),
            "unexpected_unavailable_count": sum(
                row["expected"] != "unavailable" for row in unavailable
            ),
        },
    }


def _count(row: dict[str, object], key: str, *, default: int | None = None) -> int:
    value = row.get(key, default)
    if type(value) is not int:
        raise ValueError("Expected an integer metric observation")
    return value


def _number(row: dict[str, object], key: str) -> float:
    value = row[key]
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("Expected a numeric metric observation")
    return float(value)


def evaluate(
    dataset: RetrievalDataset, package: SupportCorpusPackage | None = None
) -> dict[str, object]:
    package = package if package is not None else load_corpus_package()
    validate_dataset(dataset, package)
    ks = (1, 2, 3)
    rows: list[dict[str, object]] = []
    for case in dataset.cases:
        knowledge = _knowledge(dataset, package, case.source_state)
        question = SupportQuestion(question=case.question)
        matches = knowledge.retrieve(question)
        ranked = [match.passage_id for match in matches]
        response = SupportService(ReferenceSelector(case), knowledge).answer(question)
        cited = {reference.passage_id for reference in response.references}
        row: dict[str, object] = {
            "case_id": case.case_id,
            "split": case.split,
            "categories": list(case.categories),
            "expected": case.expected,
            "status": response.status,
            "ranked_passage_ids": ranked,
            "relevant_count": len(case.relevant_passage_ids),
            "required_group_count": len(case.required_evidence_groups),
            "citation_count": len(cited),
            "relevant_citation_count": len(cited & set(case.relevant_passage_ids)),
            "citation_integrity": _citation_integrity(response, matches),
            "sufficient_answer": _supported_answer(case, cited),
        }
        for k in ks:
            top = ranked[:k]
            relevant = set(case.relevant_passage_ids)
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
    categories = sorted({category for case in dataset.cases for category in case.categories})
    by_category = {
        category: _summary(
            [
                row
                for row, case in zip(rows, dataset.cases, strict=True)
                if category in case.categories
            ],
            ks,
        )
        for category in categories
    }
    return {
        "report_schema_version": "support-retrieval-report-v1",
        "dataset_version": dataset.dataset_version,
        "dataset_canonical_sha256": canonical_digest(dataset.model_dump(mode="json")),
        "label_status": dataset.label_status,
        "label_author": dataset.label_author,
        "production_approved": dataset.production_approved,
        "corpus_revision": dataset.corpus_revision,
        "corpus_canonical_sha256": dataset.corpus_canonical_sha256,
        "corpus_source_count": len(package.documents),
        "corpus_passage_count": sum(len(document.passages) for document in package.documents),
        "evaluation_time": dataset.evaluation_time.isoformat(),
        "retriever_id": dataset.retriever_id,
        "scope": "offline unchanged lexical retrieval plus deterministic oracle; no Gemini calls",
        "model_semantic_performance_measured": False,
        "counts_by_category": dict(
            Counter(category for case in dataset.cases for category in case.categories)
        ),
        "overall": _summary(rows, ks),
        "by_split": {
            split: _summary([row for row in rows if row["split"] == split], ks)
            for split in ("development", "heldout")
        },
        "by_category": by_category,
        "selection_contract_probes": evaluate_controls(dataset, package),
        "cases": rows,
    }


def evaluate_controls(
    dataset: RetrievalDataset, package: SupportCorpusPackage
) -> list[dict[str, object]]:
    """Bad selectors reveal what citation validation can and cannot establish."""
    case = next(
        (
            case
            for case in dataset.cases
            if case.expected == "abstain"
            and case.source_state == "approved"
            and "unsupported_policy_action" in case.categories
        ),
        None,
    )
    if case is None:
        return []
    question = SupportQuestion(question=case.question)
    knowledge = _knowledge(dataset, package, "approved")
    matches = knowledge.retrieve(question)
    if not matches:
        raise ValueError("Adversarial selector control requires lexical matches")
    retrieved_ids = {match.passage_id for match in matches}
    unretrieved_id = next(
        passage.passage_id
        for document in package.documents
        for passage in document.passages
        if passage.passage_id not in retrieved_ids
    )
    rows: list[dict[str, object]] = []
    modes: tuple[Mode, ...] = (
        "unsupported",
        "first_retrieved",
        "unknown_reference",
        "unretrieved_reference",
        "exception",
        "timeout",
        "none",
        "malformed",
    )
    for mode in modes:
        response = SupportService(
            ReferenceSelector(case, mode, unretrieved_id=unretrieved_id), knowledge
        ).answer(question)
        rows.append(
            {
                "mode": mode,
                "status": response.status,
                "citation_count": len(response.references),
                "citation_integrity": (
                    _citation_integrity(response, matches) if response.references else None
                ),
                "sufficient_answer": _supported_answer(
                    case, {ref.passage_id for ref in response.references}
                ),
                "semantic_abstention_credit": mode == "unsupported"
                and response.status == "unsupported",
                "unsupported_answer_detected": response.status == "answered",
            }
        )
    return rows
