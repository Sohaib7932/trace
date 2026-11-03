"""Artificial vectors test ranking/contracts only; never reported as semantic quality."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.ai.embeddings import BoundedEmbeddingClient
from app.core.embedding_settings import EmbeddingSettings
from app.evaluation.semantic_retrieval import (
    SemanticEvaluationCache,
    create_evaluation_cache,
    evaluate_semantic_cache,
)
from app.evaluation.support_retrieval import load_dataset
from app.schemas.embeddings import EmbeddingIndexMetadata, EmbeddingTransportResult, UnitEmbedding
from app.schemas.support import SupportQuestion
from app.support.embedding_index import (
    EmbeddingIndex,
    FileEmbeddingIndex,
    compose_index,
    document_inputs,
)
from app.support.knowledge import ReviewedSupportKnowledge, load_corpus_package
from app.support.semantic import (
    BoundRetrievalOutcome,
    SemanticRetrievalSettings,
    SemanticSupportKnowledge,
    rank_with_vector,
)
from app.support.vector_json import strict_vector_json
from scripts import evaluate_semantic_retrieval as cli
from tests.unit.test_embeddings import ControlledEmbeddings, basis

NOW = datetime.fromisoformat("2026-11-02T15:34:08+00:00")
DATASET = Path(__file__).parents[1] / "fixtures" / "support_retrieval_v1.json"


@pytest.fixture(scope="module")
def package():
    return load_corpus_package()


@pytest.fixture(scope="module")
def knowledge(package):
    return ReviewedSupportKnowledge(clock=lambda: NOW, loader=lambda: package)


@pytest.fixture(scope="module")
def snapshot(knowledge):
    return knowledge.snapshot()


@pytest.fixture(scope="module")
def index(snapshot):
    bounded = BoundedEmbeddingClient(
        EmbeddingSettings(_env_file=None, mode="mock"), ControlledEmbeddings()
    )
    try:
        return compose_index(
            snapshot, bounded.embed(document_inputs(snapshot), "document"), created_at=NOW
        )
    finally:
        bounded.close()


def experiment(**changes):
    return SemanticRetrievalSettings(
        **dict(mode="semantic", allow_unreviewed_experiment=True, minimum_cosine=0.9) | changes
    )


def test_index_is_exact_complete_source_bound_and_round_trips(snapshot, index, tmp_path):
    assert index.matches_snapshot(snapshot)
    assert len(index.passages) == 19 and index.metadata.source == "test_fixture"
    path = tmp_path / "index.json"
    FileEmbeddingIndex.write_new(path, index)
    assert FileEmbeddingIndex.load(path) == index
    with pytest.raises(FileExistsError):
        FileEmbeddingIndex.write_new(path, index)
    assert index.metadata.scope == "benchmark"


@pytest.mark.parametrize("field", ["index_sha256", "manifest_sha256"])
def test_tampered_index_receipts_are_rejected_or_not_eligible(snapshot, index, field):
    changed = index.model_dump(mode="json") | {field: "0" * 64}
    with pytest.raises(ValidationError):
        EmbeddingIndex.model_validate_json(json.dumps(changed))


def test_changed_vector_or_input_identity_cannot_hydrate_source(index, snapshot):
    changed = index.model_dump(mode="json")
    changed["passages"][0]["vector"]["values"][0] = 0.25
    with pytest.raises(ValidationError):
        EmbeddingIndex.model_validate_json(json.dumps(changed))
    forged = index.model_copy(
        update={
            "passages": (index.passages[0].model_copy(update={"input_sha256": "0" * 64}),)
            + index.passages[1:]
        }
    )
    assert not forged.matches_snapshot(snapshot)


def test_duplicate_chunks_and_wrong_embedding_space_are_rejected(index):
    duplicate = index.model_dump(mode="json")
    duplicate["passages"][1] = duplicate["passages"][0]
    with pytest.raises(ValidationError):
        EmbeddingIndex.model_validate_json(json.dumps(duplicate))
    wrong = index.model_dump(mode="json")
    wrong["passages"][0]["space_sha256"] = "0" * 64
    with pytest.raises(ValidationError):
        EmbeddingIndex.model_validate_json(json.dumps(wrong))


def test_expired_revoked_edited_and_new_manifest_cannot_reuse_index(index, package):
    packages = [
        package.model_copy(update={"revoked_source_ids": ("trace-overview",)}),
        package.model_copy(update={"review_status": "draft"}),
        package.model_copy(
            update={"document_digests": dict.fromkeys(package.document_digests, "0" * 64)}
        ),
    ]
    for current in packages:
        snapshot = ReviewedSupportKnowledge(
            clock=lambda: NOW, loader=lambda current=current: current
        ).snapshot()
        assert not index.matches_snapshot(snapshot)
    expired = ReviewedSupportKnowledge(
        clock=lambda: package.valid_until + timedelta(seconds=1), loader=lambda: package
    ).snapshot()
    assert not index.matches_snapshot(expired)
    with pytest.raises(ValueError):
        document_inputs(expired)


def test_exact_cosine_preserves_authoritative_quotes_and_never_treats_score_as_answer(
    snapshot, index
):
    query = UnitEmbedding.from_raw(basis(5))
    outcome = rank_with_vector(
        snapshot, index, SupportQuestion(question="Public help"), query, experiment()
    )
    assert len(outcome.matches) == 1
    assert outcome.versions[0] == index.passages[5].version
    assert snapshot.reconstruct(outcome.versions[0]) == outcome.matches[0]
    assert outcome.rankings[0].cosine == 1.0
    receipt = json.dumps(outcome.safe_receipt())
    assert "values" not in receipt and "Public help" not in receipt
    assert outcome.matches[0].text not in receipt


def test_query_with_no_above_threshold_evidence_is_empty_not_a_guessed_answer(snapshot, index):
    query = UnitEmbedding.from_raw(basis(700))
    outcome = rank_with_vector(
        snapshot, index, SupportQuestion(question="Unknown subject"), query, experiment()
    )
    assert outcome.matches == () and outcome.mode == "semantic"


def test_hybrid_zero_channel_weights_and_ties_are_deterministic(snapshot, index):
    question = SupportQuestion(question="password recovery expired recovery link")
    query = UnitEmbedding.from_raw(basis(0))
    lexical = snapshot.retrieve(question)
    no_semantic = rank_with_vector(
        snapshot,
        index,
        question,
        query,
        experiment(mode="hybrid", lexical_weight=1.0, semantic_weight=0.0),
    )
    assert no_semantic.matches == lexical
    semantic = rank_with_vector(
        snapshot,
        index,
        question,
        query,
        experiment(mode="hybrid", lexical_weight=0.0, semantic_weight=1.0),
    )
    assert tuple(version for version in semantic.versions) == (index.passages[0].version,)
    assert rank_with_vector(
        snapshot, index, question, query, experiment(mode="hybrid")
    ) == rank_with_vector(snapshot, index, question, query, experiment(mode="hybrid"))
    with pytest.raises(ValidationError):
        experiment(mode="hybrid", lexical_weight=0.0, semantic_weight=0.0)


def test_default_and_unreviewed_paths_stay_lexical_without_provider_calls(knowledge, index):
    provider = ControlledEmbeddings()
    bounded = BoundedEmbeddingClient(EmbeddingSettings(_env_file=None, mode="mock"), provider)
    question = SupportQuestion(question="password recovery")
    for settings in (None, SemanticRetrievalSettings(mode="hybrid")):
        adapter = SemanticSupportKnowledge(knowledge, bounded, index, settings)
        assert adapter.retrieve(question) == knowledge.retrieve(question)
        assert provider.calls == []
    bounded.close()


def test_missing_index_and_embedding_outage_use_only_current_lexical_sources(knowledge, index):
    bounded = BoundedEmbeddingClient(EmbeddingSettings(_env_file=None))
    question = SupportQuestion(question="password recovery")
    for current_index, reason in ((None, "index_unavailable"), (index, "embedding_unavailable")):
        adapter = SemanticSupportKnowledge(knowledge, bounded, current_index, experiment())
        outcome = adapter.retrieve_with_snapshot(question)
        assert outcome.mode == "lexical" and outcome.fallback_reason == reason
        assert outcome.matches == knowledge.retrieve(question)
    bounded.close()


def test_request_bound_release_revalidation_performs_no_second_rpc(knowledge, index):
    provider = ControlledEmbeddings()
    bounded = BoundedEmbeddingClient(EmbeddingSettings(_env_file=None, mode="mock"), provider)
    adapter = SemanticSupportKnowledge(knowledge, bounded, index, experiment())
    outcome = adapter.retrieve_with_snapshot(SupportQuestion(question="Public help"))
    assert outcome.mode == "semantic" and len(provider.calls) == 1
    assert adapter.revalidate(outcome) and adapter.revalidate(outcome)
    assert len(provider.calls) == 1
    adapter.index = None
    assert not adapter.revalidate(outcome)
    bounded.close()


def test_expiry_during_embedding_work_fails_closed_then_release_stays_denied(package, index):
    current = [NOW]
    knowledge = ReviewedSupportKnowledge(clock=lambda: current[0], loader=lambda: package)

    def expire(request):
        current[0] = package.valid_until
        return EmbeddingTransportResult(vectors=(basis(),))

    bounded = BoundedEmbeddingClient(
        EmbeddingSettings(_env_file=None, mode="mock"), ControlledEmbeddings(callback=expire)
    )
    adapter = SemanticSupportKnowledge(knowledge, bounded, index, experiment())
    outcome = adapter.retrieve_with_snapshot(SupportQuestion(question="Public help"))
    assert outcome.mode == "unavailable" and outcome.matches == ()
    assert not adapter.revalidate(outcome)
    assert not adapter.available
    bounded.close()


def test_bound_outcome_rejects_substituted_or_duplicate_citations(snapshot, index):
    version = index.passages[0].version
    match = snapshot.reconstruct(version)
    with pytest.raises(ValidationError):
        BoundRetrievalOutcome(snapshot=snapshot, mode="semantic", matches=(match,), versions=())
    with pytest.raises(ValidationError):
        BoundRetrievalOutcome(
            snapshot=snapshot, mode="semantic", matches=(match, match), versions=(version, version)
        )


def test_forged_sensitive_question_is_revalidated_before_embedding(knowledge, index):
    provider = ControlledEmbeddings()
    bounded = BoundedEmbeddingClient(EmbeddingSettings(_env_file=None, mode="mock"), provider)
    adapter = SemanticSupportKnowledge(knowledge, bounded, index, experiment())
    forged = SupportQuestion.model_construct(question="password=controlled-private-canary")
    with pytest.raises(ValidationError):
        adapter.retrieve_with_snapshot(forged)
    assert provider.calls == []
    bounded.close()


def test_fixture_vectors_cannot_be_promoted_or_used_as_live_semantic_knowledge(knowledge, index):
    with pytest.raises(ValidationError):
        EmbeddingIndexMetadata(created_at=NOW, source="test_fixture", scope="production_candidate")
    provider = ControlledEmbeddings()
    provider.source = "ai"  # Artificial transport only; no SDK, cache or semantic measurement.
    bounded = BoundedEmbeddingClient(
        EmbeddingSettings(
            _env_file=None, mode="gemini_free", free_tier_unbilled_project_confirmed=True
        ),
        provider,
    )
    adapter = SemanticSupportKnowledge(knowledge, bounded, index, experiment())
    outcome = adapter.retrieve_with_snapshot(SupportQuestion(question="password recovery"))
    assert outcome.mode == "lexical" and outcome.fallback_reason == "index_unavailable"
    assert provider.calls == []
    bounded.close()


def test_compose_scope_is_explicit_hashed_and_does_not_approve_production(snapshot):
    provider = ControlledEmbeddings()
    bounded = BoundedEmbeddingClient(EmbeddingSettings(_env_file=None, mode="mock"), provider)
    try:
        receipt = bounded.embed(document_inputs(snapshot), "document")
        with pytest.raises(ValidationError):
            compose_index(snapshot, receipt, created_at=NOW, scope="production_candidate")
        # Artificial trusted adapter receipt only; this test makes no semantic or live claim.
        modeled_ai_receipt = receipt.model_copy(update={"source": "ai"})
        benchmark = compose_index(snapshot, modeled_ai_receipt, created_at=NOW)
        candidate = compose_index(
            snapshot, modeled_ai_receipt, created_at=NOW, scope="production_candidate"
        )
        assert candidate.metadata.scope == "production_candidate"
        assert candidate.index_sha256 != benchmark.index_sha256
        assert candidate.content_digest() == candidate.index_sha256
    finally:
        bounded.close()


@pytest.fixture(scope="module")
def dataset():
    return load_dataset(DATASET)


@pytest.fixture(scope="module")
def cache(dataset, package):
    provider = ControlledEmbeddings()
    bounded = BoundedEmbeddingClient(
        EmbeddingSettings(
            _env_file=None, mode="mock", max_requests_per_process=2, max_items_per_process=113
        ),
        provider,
    )
    try:
        result = create_evaluation_cache(dataset, package, bounded, now=NOW)
        assert [len(request.texts) for request in provider.calls] == [19, 94]
        assert bounded.usage_snapshot().attempts == 2
        return result
    finally:
        bounded.close()


def test_mock_cache_is_labelled_test_fixture_and_not_a_semantic_quality_measurement(
    dataset, package, cache
):
    report = evaluate_semantic_cache(dataset, package, cache)
    assert report["genuine_semantic_vectors"] is False
    assert report["model_selector_semantics_measured"] is False
    assert "disabled" in report["production_activation"]
    assert set(report["strategies"]) == {"lexical", "semantic", "hybrid"}
    baseline = json.loads(
        (Path(__file__).parents[3] / "docs/support-retrieval-baseline-v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert (
        report["strategies"]["lexical"]["overall"]["retrieval"] == baseline["overall"]["retrieval"]
    )


def test_cache_round_trip_digest_and_duplicate_json_guards(cache, tmp_path):
    path = tmp_path / "cache.json"
    cache.write_new(path)
    assert SemanticEvaluationCache.load(path) == cache
    with pytest.raises(FileExistsError):
        cache.write_new(path)
    path.write_text('{"schema_version":"one","schema_version":"two"}', encoding="utf-8")
    with pytest.raises(ValueError):
        SemanticEvaluationCache.load(path)
    changed = cache.model_dump(mode="json") | {"cache_sha256": "0" * 64}
    with pytest.raises(ValidationError):
        SemanticEvaluationCache.model_validate_json(json.dumps(changed))


def test_cache_cannot_be_reused_for_changed_dataset_or_question_identity(dataset, package, cache):
    changed = dataset.model_copy(update={"dataset_version": "1.0.1"})
    with pytest.raises(ValueError, match="do not match"):
        evaluate_semantic_cache(changed, package, cache)


def test_live_indexing_rejects_expired_source_before_any_provider_work(dataset, package):
    provider = ControlledEmbeddings()
    bounded = BoundedEmbeddingClient(EmbeddingSettings(_env_file=None, mode="mock"), provider)
    with pytest.raises(ValueError, match="currently reviewed"):
        create_evaluation_cache(dataset, package, bounded, now=package.valid_until)
    assert provider.calls == []
    bounded.close()


def test_cli_requires_explicit_live_confirmation_without_a_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sys.argv",
        ["semantic-eval", "--dataset", str(DATASET), "--cache", str(tmp_path / "missing.json")],
    )
    monkeypatch.setattr(
        cli.GeminiEmbeddingTransport,
        "from_environment",
        lambda settings: pytest.fail("No credentials or live calls"),
    )
    with pytest.raises(SystemExit) as caught:
        cli.main()
    assert caught.value.code == 2


def test_cli_offline_replay_never_initializes_provider(monkeypatch, tmp_path, cache, capsys):
    path = tmp_path / "cache.json"
    cache.write_new(path)
    monkeypatch.setattr(
        "sys.argv", ["semantic-eval", "--dataset", str(DATASET), "--cache", str(path)]
    )
    monkeypatch.setattr(
        cli.GeminiEmbeddingTransport,
        "from_environment",
        lambda settings: pytest.fail("No credentials or live calls"),
    )
    monkeypatch.setattr(cli, "evaluate_semantic_cache", lambda *args, **kwargs: {"offline": True})
    cli.main()
    assert json.loads(capsys.readouterr().out) == {"offline": True}


@pytest.mark.parametrize(
    "raw",
    [
        '{"x": NaN}',
        '{"x": Infinity}',
        '{"x": 1e999}',
        '{"x":1,"x":2}',
        "[]",
        '{"x":"\\ud800"}',
        '{"x":' + "[" * 17 + "0" + "]" * 17 + "}",
    ],
)
def test_numerical_cache_parser_rejects_nonfinite_duplicate_and_unbounded_content(raw):
    with pytest.raises(ValueError):
        strict_vector_json(raw, max_bytes=8192)
    with pytest.raises(ValueError):
        strict_vector_json('{"value":1}', max_bytes=2)


def test_numerical_cache_parser_allows_finite_floats_without_weakening_conversational_parser():
    from app.ai.json_output import strict_json_object

    assert (
        strict_vector_json('{"value":0.5,"optional":null,"flag":true}', max_bytes=8192)["value"]
        == 0.5
    )
    with pytest.raises(ValueError):
        strict_json_object('{"value":0.5}')


@pytest.mark.parametrize(
    "arguments",
    [
        ["--unknown-private-canary"],
        ["--minimum-cosine", "private-argument-canary"],
        ["--dataset", "private-filename-canary", "--cache", "unused"],
    ],
)
def test_cli_argument_and_file_errors_never_echo_pasted_values(monkeypatch, capsys, arguments):
    monkeypatch.setattr("sys.argv", ["semantic-eval", *arguments])
    with pytest.raises(SystemExit):
        cli.main()
    captured = capsys.readouterr()
    assert "canary" not in captured.out + captured.err


def test_cli_credential_construction_failure_is_constant_without_traceback(
    monkeypatch, capsys, tmp_path
):
    def missing(settings):
        raise RuntimeError("private-credential-canary")

    monkeypatch.setattr(cli.GeminiEmbeddingTransport, "from_environment", missing)
    monkeypatch.setattr(
        "sys.argv",
        [
            "semantic-eval",
            "--dataset",
            str(DATASET),
            "--cache",
            str(tmp_path / "new.json"),
            "--live-free-tier",
            "--confirm-unbilled-project",
        ],
    )
    with pytest.raises(SystemExit) as caught:
        cli.main()
    captured = capsys.readouterr()
    assert caught.value.code == 1 and "canary" not in captured.out + captured.err
    assert json.loads(captured.out) == {
        "status": "unavailable",
        "error_code": "configuration_missing",
    }
