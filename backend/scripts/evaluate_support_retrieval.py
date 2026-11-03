"""Run the explicit offline public-source evaluation; JSON output contains no learner data."""

import argparse
import json
from pathlib import Path

from app.evaluation.lexical_candidates import compare_lexical_candidates
from app.evaluation.support_retrieval import evaluate, load_dataset
from app.support.knowledge import load_corpus_package


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path, help="Explicit offline fixture JSON")
    parser.add_argument("--output", type=Path, help="Optional new report JSON path")
    parser.add_argument(
        "--compare-candidate", action="store_true", help="Offline fixed BM25 experiment"
    )
    arguments = parser.parse_args()
    dataset = load_dataset(arguments.dataset)
    result = (
        compare_lexical_candidates(dataset, load_corpus_package())
        if arguments.compare_candidate
        else evaluate(dataset)
    )
    report = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if arguments.output:
        # Preserve prior reports instead of silently overwriting existing work.
        with arguments.output.open("x", encoding="utf-8", newline="\n") as target:
            target.write(report)
    print(report, end="")


if __name__ == "__main__":
    main()
