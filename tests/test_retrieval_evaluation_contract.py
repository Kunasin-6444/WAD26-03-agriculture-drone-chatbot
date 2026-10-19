import unittest

from scripts.retrieval_metrics import evidence_groups, score_ranking, validate_cases


class RetrievalEvaluationTests(unittest.TestCase):
    def test_partial_retrieval_does_not_count_as_complete_multi_aspect_answer(self):
        result = score_ranking([("a.pdf", "1")], [{("a.pdf", "1")}, {("b.pdf", "2")}])
        self.assertEqual(result["hits"][3], 1)
        self.assertEqual(result["coverage"][3], .5)
        self.assertEqual(result["complete"][3], 0)

    def test_alternative_verified_pages_satisfy_one_aspect(self):
        result = score_ranking([("b.pdf", "2"), ("c.pdf", "3")],
                               [{("a.pdf", "1"), ("b.pdf", "2")}, {("c.pdf", "3")}])
        self.assertEqual(result["complete"][3], 1)
        self.assertEqual(result["aspect_ranks"], [1, 2])

    def test_annotation_is_not_rederived_from_extracted_text(self):
        case = {"id": "d1", "evidence_groups": [{"pages": [{"source_file": "a.pdf", "page_number": 2}]}]}
        self.assertEqual(evidence_groups(case, [("fake.pdf", "999", "matching words")]), [{("a.pdf", "2")}])

    def test_empty_missing_and_duplicate_cases_fail_instead_of_green_report(self):
        for cases in [[], [{"id": "a", "split": "test", "query": "x"}],
                      [{"id": "a", "split": "dev", "query": "x"}] * 2]:
            with self.subTest(cases=cases), self.assertRaises(ValueError):
                validate_cases(cases)
        with self.assertRaises(ValueError):
            evidence_groups({"id": "a", "gold": [["not found"]]}, [("a.pdf", "1", "content")])

    def test_invalid_page_annotations_fail(self):
        for pages in [[], [{"source_file": "a.pdf", "page_number": 0}], [{"source_file": "a.pdf", "page_number": "unknown"}]]:
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                evidence_groups({"id": "a", "evidence_groups": [{"pages": pages}]}, [])
