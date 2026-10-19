import unittest

from app.rag.page_reranker import select_diverse_pages, split_query_aspects


class PageRerankerTests(unittest.TestCase):
    def test_unrelated_topics_do_not_override_strong_relevance(self):
        pages = [dict(content="alpha", topic="general", rrf_score=1),
                 dict(content="beta", topic="survey", rrf_score=.5)]
        self.assertEqual(select_diverse_pages("GSD", pages, 1, str.split, "survey"), [pages[0]])

    def test_topic_alignment_breaks_close_relevance_tie(self):
        pages = [dict(content="a", topic="general", rrf_score=1),
                 dict(content="b", topic="survey", rrf_score=.99)]
        self.assertEqual(select_diverse_pages("GSD", pages, 1, str.split, "survey"), [pages[1]])

    def test_duplicate_content_yields_to_relevant_different_evidence(self):
        pages = [dict(content="same information", topic="nozzles", rrf_score=1),
                 dict(content="same information", topic="nozzles", rrf_score=.99),
                 dict(content="different details", topic="nozzles", rrf_score=.98)]
        self.assertEqual(select_diverse_pages("nozzle", pages, 2, str.split, "nozzles"), [pages[0], pages[2]])

    def test_crop_substring_does_not_count_rice_as_corn_match(self):
        pages = [dict(content="ข้าว", topic="general", rrf_score=1),
                 dict(content="ข้าวโพด", topic="general", rrf_score=.99)]
        self.assertEqual(select_diverse_pages("ข้าวโพด", pages, 1, str.split, "general"), [pages[1]])

    def test_empty_and_zero_k_return_no_pages(self):
        self.assertEqual(select_diverse_pages("x", [], 8, str.split, "general"), [])

    def test_independent_clauses_keep_one_page_each(self):
        pages = [dict(content="nozzle", topic="nozzles", rrf_score=.5, aspect_ranks={0: 1}),
                 dict(content="survey", topic="survey", rrf_score=1, aspect_ranks={1: 1}),
                 dict(content="duplicate", topic="survey", rrf_score=.99)]
        self.assertEqual(select_diverse_pages("x", pages, 2, str.split, "survey"), pages[:2])

    def test_splitting_keeps_short_followup_with_its_subject(self):
        self.assertEqual(split_query_aspects("หัวฉีดอุดตันเกิดจากอะไรและแก้อย่างไร"), [])
        self.assertEqual(len(split_query_aspects("พัดส้มมีปริมาณต่อหัวเท่าไร และ GCP ช่วยในการสำรวจแปลงอ้อยอย่างไร")), 2)
