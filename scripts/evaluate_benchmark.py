"""Compatibility command for the canonical evidence/latency evaluator.

The old keyword-only evaluator could exit successfully despite failed cases.
Its questions are retained in tests/data/retired_benchmark_questions.json for
source annotation; they are not treated as verified answers.
"""
from scripts.evaluate_acceptance import main


if __name__ == "__main__":
    raise SystemExit(main())
