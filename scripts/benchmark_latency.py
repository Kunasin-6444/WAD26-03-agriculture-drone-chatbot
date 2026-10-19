"""Five representative cases using the canonical evaluator and real exit codes.

Supports the same --warmup, --repeat, --concurrency and --output flags as
scripts.evaluate_acceptance. Answer caching is bypassed during measurement.
"""
from scripts import evaluate_acceptance as harness


def main() -> int:
    original = harness.CASES
    try:
        harness.CASES = [original[index] for index in (4, 0, 17, 20, 23)]
        return harness.main()
    finally:
        harness.CASES = original


if __name__ == "__main__":
    raise SystemExit(main())
