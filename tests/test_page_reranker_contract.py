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


class TableContinuation(unittest.TestCase):
    def page(self, number, rows, score):
        return {"source_file": "a.pdf", "page_number": str(number), "table_rows": set(rows), "rerank_score": score}

    def test_the_next_rows_of_a_selected_table_are_appended_after_the_top_k(self):
        from app.rag.page_reranker import add_table_continuations
        first, nxt = self.page(30, {("t6", 1, 1)}, 0.9), self.page(31, {("t6", 2, 3)}, 0.2)
        other_table, far_rows = self.page(40, {("t7", 2, 3)}, 0.8), self.page(33, {("t6", 6, 6)}, 0.7)
        self.assertEqual(add_table_continuations([first], [first, other_table, far_rows, nxt], 2), [first, nxt])

    def test_the_limit_keeps_the_best_scored_continuations(self):
        from app.rag.page_reranker import add_table_continuations
        first = self.page(31, {("t6", 2, 3)}, 0.9)
        before, after = self.page(30, {("t6", 1, 1)}, 0.3), self.page(32, {("t6", 4, 5)}, 0.5)
        self.assertEqual(add_table_continuations([first], [first, before, after], 1), [first, after])
        self.assertEqual(add_table_continuations([first], [first, before, after], 0), [first])

    def test_page_metadata_gives_the_row_ranges(self):
        from app.rag.page_reranker import table_rows
        self.assertEqual(table_rows([{"table_id": "t6", "row_start": 2, "row_end": "3"}, {"source_type": "text"}, None]),
                         {("t6", 2, 3)})


class RarePhrase(unittest.TestCase):
    def page(self, content, score):
        return {"content": content, "rrf_score": score, "topic": "general", "source_file": "a.pdf", "page_number": "1"}

    def test_the_only_page_naming_the_subject_outranks_pages_about_the_generic_part(self):
        from app.rag.page_reranker import select_diverse_pages
        generic = [self.page(f"สารกำจัดแมลง สารผสม อัตราการใช้สาร ชุดที่ {n}", 0.020 - n * 0.0001) for n in range(8)]
        named = self.page("แมลงซีลายจุด | สารอัลฟา 5% | 20 มล./น้ำ 20 ลิตร", 0.0165)
        selected = select_diverse_pages("แมลงซีลายจุดใช้สารอะไร", generic + [named], 3, str.split, "general")
        self.assertIn(named, selected)

    def test_a_piece_many_candidates_share_earns_nothing(self):
        from app.rag.page_reranker import rare_phrase_scores
        pages = [self.page("ข้าวนาปรังพ่นสารกำจัดวัชพืช", 0.01) for _ in range(5)] + [self.page("หนอนกอข้าว", 0.01)]
        self.assertEqual(rare_phrase_scores("ข้าวนาปรังพ่นสารอะไร", pages), [0.0] * 6)
        self.assertEqual(rare_phrase_scores("หนอนกอข้าวใช้สารอะไร", pages)[-1], len("หนอนกอข้าว") / 12)
