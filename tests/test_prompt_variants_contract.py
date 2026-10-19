"""Answer-prompt variants can be swapped for measurement without breaking the output contract."""
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from app.rag import rag_service

GOLD = Path(__file__).resolve().parent / "data" / "source_gold_2026-10-18.json"
OUTPUT_KEYS = ('"status"', '"reason"', '"is_caat_topic"', '"missing_aspects"', '"intro"', '"claims"',
               '"source_id"', '"quote"')
PAYLOAD_FIELDS = ("question_parts", "query_aliases", "verified_claims")


class PromptVariantTests(unittest.TestCase):
    def test_every_variant_states_the_json_contract_the_parser_enforces(self):
        for name, text in rag_service._PROMPTS.items():
            for key in OUTPUT_KEYS:
                self.assertIn(key, text, f"{name} lacks {key}")
            for field in PAYLOAD_FIELDS:
                self.assertIn(field, text, f"{name} does not explain {field}")

    def test_variant_is_chosen_per_call_and_defaults_to_full(self):
        with patch.dict(os.environ, {"RAG_PROMPT": ""}):
            self.assertEqual(rag_service.system_prompt(), rag_service._PROMPTS["full"])
        with patch.dict(os.environ, {"RAG_PROMPT": "Concise"}):
            self.assertEqual(rag_service.system_prompt(), rag_service._PROMPTS["concise"])
        with patch.dict(os.environ, {"RAG_PROMPT": "tiny"}), self.assertRaises(ValueError):
            rag_service.system_prompt()

    def test_the_concise_prompt_is_shorter_and_carries_no_gold_set_content(self):
        full, concise = rag_service._PROMPTS["full"], rag_service._PROMPTS["concise"]
        self.assertLess(len(concise.splitlines()), len(full.splitlines()))
        # Copying evaluation content into the prompt would inflate every later measurement.
        gold = json.loads(GOLD.read_text(encoding="utf-8"))
        terms = {term for case in gold["cases"] for term in case.get("must_contain", []) if len(term) >= 4}
        terms |= {"หนองเรือ", "อิมาซาปิก", "เพนดิเมทาลิน", "พัดส้ม", "25.0", "อ้อย"}
        self.assertFalse(sorted(term for term in terms if term in concise))


if __name__ == "__main__":
    unittest.main()
