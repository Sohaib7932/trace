"""Public engineering-reference labels and offline metrics; no real model or database."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation.lexical_candidates import BinaryBm25Knowledge, compare_lexical_candidates
from app.evaluation.support_retrieval import (
    ReferenceSelector,
    RetrievalCase,
    RetrievalDataset,
    _citation_integrity,
    _count,
    _knowledge,
    _number,
    _sufficient,
    _summary,
    _supported_answer,
    corpus_digest,
    evaluate,
    evaluate_controls,
    load_dataset,
    ratio,
    validate_dataset,
)
from app.schemas.support import (
    SupportDocument,
    SupportPassage,
    SupportQuestion,
    SupportReference,
    SupportResponse,
)
from app.support.knowledge import load_corpus_package
from scripts import evaluate_support_retrieval as cli

DATASET = Path(__file__).parents[1] / "fixtures" / "support_retrieval_v1.json"


@pytest.fixture(scope="module")
def dataset():
    return load_dataset(DATASET)


@pytest.fixture(scope="module")
def package():
    return load_corpus_package()


@pytest.fixture(scope="module")
def report(dataset, package):
    return evaluate(dataset, package)


def test_dataset_is_explicitly_unreviewed_reference_not_production(dataset, package):
    validate_dataset(dataset, package)
    assert not dataset.production_approved
    assert dataset.label_status == "engineering_reference_pending_independent_review"
    assert len(dataset.cases) == 94
    assert dataset.corpus_canonical_sha256 == corpus_digest(package)
    assert (
        corpus_digest(package) == "1fa44fda7549fcac866926c07c56c9778deaa8e29955309b1f8bab80c24f5063"
    )


def test_all_passages_categories_and_disjoint_families_are_covered(dataset, package):
    assert {pid for case in dataset.cases for pid in case.relevant_passage_ids} == {
        passage.passage_id for document in package.documents for passage in document.passages
    }
    assert len({category for case in dataset.cases for category in case.categories}) == 10
    families = {
        split: {case.intent_family for case in dataset.cases if case.split == split}
        for split in ("development", "heldout")
    }
    assert families["development"] and families["heldout"]
    assert families["development"].isdisjoint(families["heldout"])


@pytest.mark.parametrize("case_index", range(94))
def test_each_reference_case_is_strict_and_serialization_stable(dataset, case_index):
    case = dataset.cases[case_index]
    assert RetrievalCase.model_validate_json(case.model_dump_json()) == case
    assert case.rationale
    if case.expected == "answer":
        assert case.relevant_passage_ids and case.sufficient_evidence_sets
    else:
        assert not case.relevant_passage_ids


@pytest.mark.parametrize(
    "change",
    [
        {"corpus_revision": "9.0.0"},
        {"corpus_canonical_sha256": "0" * 64},
        {"document_digests": {}},
        {"evaluation_time": "2030-01-01T00:00:00Z"},
    ],
)
def test_changed_corpus_pin_or_clock_is_rejected(dataset, package, change):
    with pytest.raises(ValueError):
        modified = RetrievalDataset.model_validate_json(
            json.dumps(dataset.model_dump(mode="json") | change)
        )
        validate_dataset(modified, package)


def test_explicit_revocation_rejects_baseline_even_with_same_authored_digest(dataset, package):
    revoked = package.model_copy(update={"revoked_source_ids": ("trace-overview",)})
    assert corpus_digest(revoked) == corpus_digest(package)
    with pytest.raises(ValueError):
        validate_dataset(dataset, revoked)


def test_unknown_passage_duplicate_case_and_cross_split_family_are_rejected(dataset, package):
    first = dataset.cases[0]
    unknown = first.model_copy(
        update={
            "relevant_passage_ids": ("unknown-passage",),
            "sufficient_evidence_sets": (("unknown-passage",),),
        }
    )
    with pytest.raises(ValueError, match="outside its pinned corpus"):
        validate_dataset(dataset.model_copy(update={"cases": (unknown,)}), package)
    duplicate = dataset.model_dump(mode="json")
    duplicate["cases"] = [first.model_dump(mode="json"), first.model_dump(mode="json")]
    with pytest.raises(ValidationError, match="unique"):
        RetrievalDataset.model_validate_json(json.dumps(duplicate))
    second = first.model_copy(update={"case_id": "different-case", "split": "heldout"})
    with pytest.raises(ValidationError, match="cannot cross"):
        RetrievalDataset.model_validate_json(
            json.dumps(
                dataset.model_dump(mode="json")
                | {"cases": [first.model_dump(mode="json"), second.model_dump(mode="json")]}
            )
        )


@pytest.mark.parametrize(
    "change",
    [
        {"extra": True},
        {"categories": ["exact_keyword", "exact_keyword"]},
        {"relevant_passage_ids": []},
        {"sufficient_evidence_sets": []},
        {"sufficient_evidence_sets": [["unknown-passage"]]},
        {"sufficient_evidence_sets": [["trace-learning-cycle", "trace-learning-cycle"]]},
        {"required_evidence_groups": [["trace-evidence-boundary"]]},
        {"forbidden_passage_ids": ["trace-learning-cycle"]},
        {"expected": "abstain"},
        {"source_state": "expired"},
        {"question": "x" * 501},
        {"question": "password=synthetic-secret-for-rejection"},
    ],
)
def test_invalid_case_labels_are_rejected(dataset, change):
    with pytest.raises(ValidationError):
        RetrievalCase.model_validate_json(
            json.dumps(dataset.cases[0].model_dump(mode="json") | change)
        )


def test_multipart_required_groups_and_alternative_sufficient_sets(dataset):
    multipart = next(case for case in dataset.cases if case.case_id == "multi-1")
    assert not _sufficient(multipart, {multipart.relevant_passage_ids[0]})
    assert _sufficient(multipart, set(multipart.relevant_passage_ids))
    alternative = next(case for case in dataset.cases if case.case_id == "ambiguous-save")
    assert all(_sufficient(alternative, {pid}) for pid in alternative.relevant_passage_ids)
    assert _sufficient(alternative, set(alternative.relevant_passage_ids) | {"unrelated"})
    assert not _supported_answer(alternative, set(alternative.relevant_passage_ids) | {"unrelated"})


def test_zero_denominators_are_null_and_do_not_earn_perfect_scores():
    assert ratio(0, 0) is None
    summary = _summary([], (1, 3))
    assert summary["oracle_selection"]["abstention_accuracy"] is None
    assert summary["oracle_selection"]["answer_support_accuracy"] is None
    assert summary["retrieval"]["3"]["mrr"] is None


def test_retrieval_metric_arithmetic_is_independent_of_oracle_language():
    row = {
        "expected": "answer",
        "status": "unsupported",
        "citation_count": 0,
        "relevant_citation_count": 0,
        "sufficient_answer": False,
        "relevant_count": 2,
        "returned_at_3": 2,
        "hits_at_3": 1,
        "reciprocal_rank_at_3": 0.5,
        "sufficient_at_3": False,
    }
    summary = _summary([row], (3,))
    assert summary["retrieval"]["3"] == {
        "answerable_cases": 1,
        "relevant_passage_label_count": 2,
        "relevant_retrieved_count": 1,
        "returned_passage_count": 2,
        "precision_fixed_k_denominator": 3,
        "reciprocal_rank_sum": 0.5,
        "sufficient_evidence_count": 0,
        "required_evidence_group_count": 0,
        "covered_required_group_count": 0,
        "required_evidence_group_coverage": None,
        "macro_recall": 0.5,
        "macro_precision_fixed_k": 1 / 3,
        "micro_precision_returned": 0.5,
        "mrr": 0.5,
        "sufficient_evidence_rate": 0.0,
    }
    assert summary["oracle_selection"]["false_abstention_count"] == 1
    assert summary["oracle_selection"]["answer_support_accuracy"] is None


@pytest.mark.parametrize("value", [None, "1", True, {}, []])
def test_non_numeric_or_boolean_metric_observations_are_rejected(value):
    with pytest.raises(ValueError):
        _count({"bad": value}, "bad")
    with pytest.raises(ValueError):
        _number({"bad": value}, "bad")


def test_unavailable_is_not_correct_semantic_abstention():
    row = {
        "expected": "abstain",
        "status": "unavailable",
        "citation_count": 0,
        "relevant_citation_count": 0,
        "sufficient_answer": False,
    }
    metrics = _summary([row], (3,))["oracle_selection"]
    assert metrics["abstention_accuracy"] == 0.0
    assert metrics["unexpected_unavailable_count"] == 1
    assert metrics["correct_semantic_abstention_count"] == 0


@pytest.mark.parametrize("state", ["expired", "draft", "missing", "digest_mismatch"])
def test_source_fixture_fails_closed_without_changing_actual_package(dataset, package, state):
    knowledge = _knowledge(dataset, package, state)
    assert not knowledge.available
    assert not knowledge.retrieve(SupportQuestion(question="password recovery"))
    assert package.review_status == "approved"


def test_report_exposes_misses_and_does_not_claim_gemini_quality(report):
    recorded = Path(__file__).parents[3] / "docs" / "support-retrieval-baseline-v1.json"
    assert report == json.loads(recorded.read_text(encoding="utf-8"))
    assert report["model_semantic_performance_measured"] is False
    assert report["label_status"] == "engineering_reference_pending_independent_review"
    assert report["overall"]["cases"] == 94
    assert 0 < report["overall"]["retrieval"]["3"]["macro_recall"] < 1
    assert report["overall"]["oracle_selection"]["false_abstention_count"] > 0
    assert report["overall"]["oracle_selection"]["unexpected_unavailable_count"] == 0
    assert sum(row["status"] == "unavailable" for row in report["cases"]) == 4
    assert all("question" not in row for row in report["cases"])


def test_bad_selector_can_have_valid_citations_but_unsupported_answer(report):
    probes = {probe["mode"]: probe for probe in report["selection_contract_probes"]}
    irrelevant = probes["first_retrieved"]
    assert irrelevant["status"] == "answered"
    assert irrelevant["citation_integrity"] is True
    assert irrelevant["sufficient_answer"] is False
    assert irrelevant["unsupported_answer_detected"] is True
    for mode in (
        "unknown_reference",
        "unretrieved_reference",
        "exception",
        "timeout",
        "none",
        "malformed",
    ):
        assert probes[mode]["status"] == "unavailable"
        assert probes[mode]["semantic_abstention_credit"] is False
        assert probes[mode]["citation_integrity"] is None
    assert probes["unsupported"]["semantic_abstention_credit"] is True


def test_unretrieved_probe_uses_real_but_unselected_passage(dataset, package):
    case = next(case for case in dataset.cases if case.case_id == "unsupported-1")
    question = SupportQuestion(question=case.question)
    matches = _knowledge(dataset, package, "approved").retrieve(question)
    selected_ids = {match.passage_id for match in matches}
    known = next(
        passage.passage_id
        for document in package.documents
        for passage in document.passages
        if passage.passage_id not in selected_ids
    )
    result = ReferenceSelector(case, "unretrieved_reference", unretrieved_id=known).select(
        question, matches, subject="offline"
    )
    assert result.selection.passage_ids == (known,)
    assert known not in selected_ids


def test_exact_quote_source_name_and_identity_are_all_checked(dataset, package):
    matches = _knowledge(dataset, package, "approved").retrieve(
        SupportQuestion(question="password recovery expired recovery link")
    )
    match = matches[0]
    reference = SupportReference(
        source_id=match.source_id,
        source_name=match.title,
        passage_id=match.passage_id,
        quote=match.text,
    )
    response = SupportResponse(
        status="answered",
        message="Relevant approved documentation is quoted below.",
        references=(reference,),
        source="test_fixture",
    )
    assert _citation_integrity(response, matches)
    for change in (
        {"quote": "Invented source quotation"},
        {"source_id": "invented-source"},
        {"source_name": "Invented title"},
        {"passage_id": "invented-passage"},
    ):
        assert not _citation_integrity(
            response.model_copy(update={"references": (reference.model_copy(update=change),)}),
            matches,
        )


def test_dataset_duplicate_json_and_size_limits(tmp_path):
    path = tmp_path / "dataset.json"
    path.write_text('{"schema_version":"one","schema_version":"two"}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_dataset(path)
    path.write_text(" " * 524289, encoding="utf-8")
    with pytest.raises(ValueError, match="byte limit"):
        load_dataset(path)


def test_cli_outputs_json_and_preserves_existing_report(monkeypatch, capsys, tmp_path, dataset):
    monkeypatch.setattr(cli, "load_dataset", lambda path: dataset)
    monkeypatch.setattr(cli, "evaluate", lambda parsed: {"offline": True})
    target = tmp_path / "report.json"
    monkeypatch.setattr(
        "sys.argv", ["benchmark", "--dataset", str(DATASET), "--output", str(target)]
    )
    cli.main()
    assert json.loads(capsys.readouterr().out) == {"offline": True}
    assert json.loads(target.read_text(encoding="utf-8")) == {"offline": True}
    with pytest.raises(FileExistsError):
        cli.main()


def test_controls_require_actual_retrieved_sources(dataset, package):
    case = next(case for case in dataset.cases if case.case_id == "unsupported-1")
    empty_question = case.model_copy(update={"question": "Interplanetary zebrafish astronomy"})
    with pytest.raises(ValueError, match="requires lexical matches"):
        evaluate_controls(dataset.model_copy(update={"cases": (empty_question,)}), package)
    assert (
        evaluate_controls(dataset.model_copy(update={"cases": (dataset.cases[0],)}), package) == []
    )


def test_binary_bm25_is_bounded_deterministic_and_excludes_unapproved_fixtures():
    documents = tuple(
        SupportDocument(
            source_id=f"source-{index}",
            title="Common guide",
            approval="approved_customer_safe",
            passages=(SupportPassage(passage_id=f"passage-{index}", text="common topic"),),
        )
        for index in range(4)
    )
    question = SupportQuestion(question="common topic")
    candidate = BinaryBm25Knowledge(documents)
    assert [match.passage_id for match in candidate.retrieve(question)] == [
        "passage-0",
        "passage-1",
        "passage-2",
    ]
    assert candidate.retrieve(question) == candidate.retrieve(question)
    assert candidate.retrieve(SupportQuestion(question="zebrafish")) == ()
    assert BinaryBm25Knowledge(()).retrieve(question) == ()
    fixture = documents[0].model_copy(update={"approval": "test_fixture"})
    assert BinaryBm25Knowledge((fixture,)).retrieve(question) == ()


def test_binary_bm25_weights_rare_evidence_terms_without_learned_synonyms():
    documents = tuple(
        SupportDocument(
            source_id=f"source-{index}",
            title="Guide",
            approval="approved_customer_safe",
            passages=(
                SupportPassage(
                    passage_id=f"passage-{index}",
                    text="common rare" if index == 3 else "common topic",
                ),
            ),
        )
        for index in range(4)
    )
    assert (
        BinaryBm25Knowledge(documents)
        .retrieve(SupportQuestion(question="common rare"))[0]
        .passage_id
        == "passage-3"
    )


def test_offline_comparison_preserves_baseline_and_separates_provider_quality(
    dataset, package, report
):
    compared = compare_lexical_candidates(dataset, package)
    recorded = Path(__file__).parents[3] / "docs" / "support-lexical-comparison-v1.json"
    assert compared == json.loads(recorded.read_text(encoding="utf-8"))
    assert compared["strategies"]["baseline"]["overall"] == report["overall"]["retrieval"]
    assert compared["production_retriever_changed"] is False
    assert compared["semantic_or_provider_performance_measured"] is False
    assert compared["parameters_predeclared"] == {
        "binary_term_frequency": True,
        "k1": 1.2,
        "b": 0.75,
    }
