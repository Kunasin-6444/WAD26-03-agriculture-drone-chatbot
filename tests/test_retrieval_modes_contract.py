import unittest
from unittest.mock import MagicMock, patch

from app.rag import slide_retriever as sr

DENSE = ("ข้อมูลทั่วไปเกี่ยวกับโดรน", {"source_file": "UAV06.pdf", "page_number": "1", "source_type": "text"})
LEXICAL_ONLY = ("อัตราการใช้ ไกลโฟเซต 500 มล.ต่อไร่", {"source_file": "UAV09.pdf", "page_number": "5", "source_type": "text"})


def _collection(index_available=True):
    docs = [DENSE, LEXICAL_ONLY]
    fake = MagicMock()
    fake.count.return_value = len(docs)
    fake.query.return_value = {"documents": [[DENSE[0]]], "metadatas": [[DENSE[1]]], "distances": [[0.1]]}

    def get(**kwargs):
        if "where" not in kwargs and not index_available:
            raise RuntimeError("index unavailable")
        return {"documents": [d for d, _ in docs], "metadatas": [m for _, m in docs]}

    fake.get.side_effect = get
    return fake


class RetrievalModesContract(unittest.TestCase):
    def setUp(self):
        sr._bm25_cache.clear()
        self.addCleanup(sr._bm25_cache.clear)

    def _pages(self, bm25, fake):
        with patch("app.rag.slide_retriever.RETRIEVER_BM25", bm25), patch("app.rag.slide_retriever.RETRIEVER_RERANK", "none"), \
             patch("app.rag.slide_retriever.collection", fake), patch("app.rag.slide_retriever.embed_text", return_value=[1.0]):
            result = sr.search_slides_pipeline("ไกลโฟเซต", top_k=5)
        return {(p["source_file"], p["page_number"]) for p in result["top_pages"]}

    def test_global_bm25_finds_exact_term_page_dense_search_missed(self):
        self.assertIn(("UAV09.pdf", "5"), self._pages("global", _collection()))

    def test_top50_mode_cannot_find_it(self):
        self.assertNotIn(("UAV09.pdf", "5"), self._pages("top50", _collection()))

    def test_global_bm25_failure_degrades_to_dense_results(self):
        pages = self._pages("global", _collection(index_available=False))
        self.assertEqual(pages, {("UAV06.pdf", "1")})

    def test_rerank_none_does_not_apply_keyword_multipliers(self):
        fake = _collection()
        with patch("app.rag.slide_retriever.RETRIEVER_RERANK", "none"), patch("app.rag.slide_retriever.RETRIEVER_BM25", "top50"), \
             patch("app.rag.slide_retriever.collection", fake), patch("app.rag.slide_retriever.embed_text", return_value=[1.0]):
            page = sr.search_slides_pipeline("ฉีดพ่น วัชพืช 2 เดือน", top_k=3)["top_pages"][0]
        self.assertEqual(page["rerank_score"], page["rrf_score"])


if __name__ == "__main__":
    unittest.main()
