import json
import unittest

from app.rag.evidence import Evidence, parse_grounded_result

EVIDENCE = [Evidence("D1", "ความสูง | หน้ากว้าง\n1.0 | 2.8 | 4.5", "UAV07.pdf", "12")]


def _response(key: str, value: str) -> str:
    return json.dumps({
        "status": "sufficient", "reason": "", "is_caat_topic": False, "missing_aspects": [],
        "claims": [{"text": "ที่ความสูง 1 เมตร หน้ากว้าง 2.8 เมตร", "evidence": [{"source_id": "D1", key: value}]}],
    }, ensure_ascii=False)


class QuoteKeyAliasContractTests(unittest.TestCase):
    def test_text_and_content_keys_are_accepted_when_verbatim(self):
        for key in ("quote", "text", "content"):
            with self.subTest(key=key):
                result = parse_grounded_result(_response(key, "1.0 | 2.8 | 4.5"), EVIDENCE)
                self.assertEqual(result.status, "sufficient", result.reason)
                self.assertEqual(result.claims[0].quotes, (("D1", "1.0 | 2.8 | 4.5"),))

    def test_aliased_key_does_not_bypass_verbatim_quote_check(self):
        for key in ("text", "content"):
            with self.subTest(key=key):
                result = parse_grounded_result(_response(key, "1.0 | 9.9 | 4.5"), EVIDENCE)
                self.assertEqual(result.status, "insufficient")
                self.assertEqual(result.claims, [])
                self.assertTrue(result.reason.startswith("Evidence validation failed"))

    def test_unknown_key_is_still_rejected(self):
        result = parse_grounded_result(_response("ена", "1.0 | 2.8 | 4.5"), EVIDENCE)
        self.assertEqual(result.claims, [])
        self.assertTrue(result.reason.startswith("Evidence validation failed"))


if __name__ == "__main__":
    unittest.main()
