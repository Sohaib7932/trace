"""Explicit two-RPC public-text experiment or offline replay. Never activates production RAG."""

import argparse
import json
from contextlib import suppress
from pathlib import Path

from app.ai.embeddings import BoundedEmbeddingClient, EmbeddingTransportError
from app.ai.providers.gemini_embeddings import GeminiEmbeddingTransport
from app.core.ai_activation import SafeArgumentParser
from app.core.embedding_settings import EmbeddingSettings
from app.domain.clock import utc_now
from app.evaluation.semantic_retrieval import (
    SemanticEvaluationCache,
    create_evaluation_cache,
    evaluate_semantic_cache,
)
from app.evaluation.support_retrieval import load_dataset
from app.support.knowledge import load_corpus_package
from app.support.semantic import SemanticRetrievalSettings


def main() -> None:
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--live-free-tier", action="store_true")
    parser.add_argument("--confirm-unbilled-project", action="store_true")
    parser.add_argument("--minimum-cosine", type=float, default=0.0)
    parser.add_argument("--summary-only", action="store_true")
    arguments = parser.parse_args()
    try:
        _execute(parser, arguments)
    except EmbeddingTransportError as error:
        print(json.dumps({"status": "unavailable", "error_code": error.code}))
        raise SystemExit(1) from None
    except (ValueError, OSError, UnicodeError):
        print(json.dumps({"status": "unavailable", "error_code": "invalid_request"}))
        raise SystemExit(1) from None


def _execute(parser: SafeArgumentParser, arguments: argparse.Namespace) -> None:
    # Validate all public experiment arguments before reading credentials or making RPCs.
    SemanticRetrievalSettings(minimum_cosine=arguments.minimum_cosine)
    if not arguments.cache.parent.is_dir():
        parser.error("The explicit cache directory must already exist")
    if arguments.output and (arguments.output.exists() or not arguments.output.parent.is_dir()):
        parser.error("Output must be a new file in an existing explicit directory")
    dataset, package = load_dataset(arguments.dataset), load_corpus_package()
    if arguments.cache.exists():
        if arguments.live_free_tier:
            parser.error("Existing cache is preserved; omit --live-free-tier for offline replay")
        cache = SemanticEvaluationCache.load(arguments.cache)
    else:
        if not arguments.live_free_tier or not arguments.confirm_unbilled_project:
            parser.error(
                "A missing cache requires explicit live free-tier and unbilled confirmation"
            )
        settings = EmbeddingSettings(
            _env_file=None,
            mode="gemini_free",
            free_tier_unbilled_project_confirmed=True,
            max_requests_per_process=2,
            max_items_per_process=113,
            max_reserved_input_tokens_per_process=16000,
            max_concurrent_requests=1,
        )
        client: BoundedEmbeddingClient | None = None
        transport: GeminiEmbeddingTransport | None = None
        try:
            try:
                transport = GeminiEmbeddingTransport.from_environment(settings)
                client = BoundedEmbeddingClient(settings, transport)
            except Exception:
                raise EmbeddingTransportError("configuration_missing") from None
            cache = create_evaluation_cache(dataset, package, client, now=utc_now())
            cache.write_new(arguments.cache)
        finally:
            if client is not None:
                client.close()
            elif transport is not None:
                with suppress(Exception):
                    transport.close()
    report = evaluate_semantic_cache(
        dataset, package, cache, minimum_cosine=arguments.minimum_cosine
    )
    if arguments.summary_only:
        strategies = report["strategies"]
        if isinstance(strategies, dict):
            for strategy in strategies.values():
                if isinstance(strategy, dict):
                    strategy.pop("cases", None)
    raw = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if arguments.output:
        with arguments.output.open("x", encoding="utf-8", newline="\n") as target:
            target.write(raw)
    print(raw, end="")


if __name__ == "__main__":
    main()
