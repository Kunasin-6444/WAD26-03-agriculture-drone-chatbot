"""The 2026-10-18 gold set stays honest: well-formed, tied to the exact PDFs, and every
machine-checkable expected string really is printed on the page the case cites."""
import json
import re
import unittest
from pathlib import Path

import pymupdf

from scripts.retrieval_metrics import evidence_groups, validate_cases, verify_source_manifest

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "tests" / "data" / "source_gold_2026-10-18.json"
DECISIONS = {"pending", "ok", "fix", "drop"}


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text)


class SourceGoldContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = json.loads(GOLD.read_text(encoding="utf-8"))
        cls.cases = cls.dataset["cases"]

    def test_cases_are_well_formed_with_real_page_groups(self):
        validate_cases(self.cases)
        for case in self.cases:
            self.assertTrue(evidence_groups(case, []), case["id"])
            self.assertTrue(case["expected_answer"].strip(), case["id"])
            self.assertIn(case["review"]["decision"], DECISIONS, case["id"])
        for case in self.dataset["answer_only_cases"]:
            self.assertIn(case["review"]["decision"], DECISIONS, case["id"])

    def test_holdout_exists_and_ids_do_not_clash_with_the_older_gold(self):
        self.assertTrue(any(c["split"] == "holdout" for c in self.cases))
        older = json.loads((ROOT / "tests" / "data" / "source_gold.json").read_text(encoding="utf-8"))
        self.assertFalse({c["id"] for c in self.cases} & {c["id"] for c in older["cases"]})

    def test_expected_strings_are_printed_on_the_cited_pages(self):
        data = ROOT / "data"
        missing = [name for name in self.dataset["source_sha256"] if not (data / name).exists()]
        if missing:
            self.skipTest(f"source PDFs not present: {missing}")
        verify_source_manifest(self.dataset, data)  # a changed PDF means the gold must be re-reviewed
        for case in self.cases:
            if case["verified_by"] != "pdf_text":
                continue
            pages = case["evidence_groups"][0]["pages"]
            with pymupdf.open(data / pages[0]["source_file"]) as doc:
                text = "".join(_norm(doc[p["page_number"] - 1].get_text()) for p in pages)
            for expected in case["must_contain"]:
                self.assertIn(_norm(expected), text, f"{case['id']}: {expected!r}")


if __name__ == "__main__":
    unittest.main()
