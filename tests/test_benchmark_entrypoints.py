import unittest
import runpy
from unittest.mock import patch

from scripts import benchmark_latency, evaluate_acceptance


class BenchmarkEntrypointTests(unittest.TestCase):
    def test_old_full_benchmark_uses_canonical_failure_exit_code(self):
        with patch.object(evaluate_acceptance, "main", return_value=1), self.assertRaises(SystemExit) as status:
            runpy.run_module("scripts.evaluate_benchmark", run_name="__main__")
        self.assertEqual(status.exception.code, 1)

    def test_representative_benchmark_keeps_failures_and_restores_default_cases(self):
        original = evaluate_acceptance.CASES
        def evaluate():
            self.assertEqual(len(evaluate_acceptance.CASES), 5)
            routes = {route for case in evaluate_acceptance.CASES for route in case["sources"]}
            self.assertTrue({"knowledge_base", "caat_portal", "web_fallback", "abstain"} <= routes)
            return 1
        with patch.object(evaluate_acceptance, "main", side_effect=evaluate):
            self.assertEqual(benchmark_latency.main(), 1)
        self.assertIs(evaluate_acceptance.CASES, original)
