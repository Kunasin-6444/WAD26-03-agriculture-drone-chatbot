import unittest
from unittest.mock import MagicMock, patch

from app.ingestion.models import KnowledgeUnit
from app.rag.chunking import chunk_knowledge_unit, split_text
from app.rag.query_normalizer import normalize_query
from app.rag.slide_retriever import search_slides_pipeline
from app.rag.vector_store import add_chunks, collection, search


class RetrievalStorageContractTests(unittest.TestCase):
    def test_chunking_overlap_and_metadata(self):
        parts = split_text("abcdefghij", 6, 2)
        self.assertEqual(parts, ["abcdef", "efghij"])
        unit = KnowledgeUnit(id="u1", document_id="uav07", source_file="UAV07.pdf", page_number=12, source_type="table", content="หัวฉีด 500 ml")
        chunk = chunk_knowledge_unit(unit)[0]
        self.assertEqual(chunk.content, unit.content)
        self.assertEqual(chunk.metadata["page_number"], "12")

    def test_invalid_chunk_parameters_rejected(self):
        for size, overlap in [(0, 0), (100, -1), (100, 100)]:
            with self.subTest(size=size, overlap=overlap), self.assertRaises(ValueError):
                split_text("data", size, overlap)

    def test_thai_normalization_idempotent_and_does_not_inject_answer(self):
        for query in ["พัดฟ้า", "คุมดิน", "ฉีดดพ่น", "  หัวฉีด   พัดฟ้า "]:
            normalized = normalize_query(query)
            self.assertEqual(normalize_query(normalized), normalized)
            self.assertNotIn("พัดแดง", normalized)
            self.assertNotIn("Ultra-Coarse", normalized)

    def test_real_isolated_chroma_upsert_retrieval_and_metadata(self):
        unit = KnowledgeUnit(id="storage-regression", document_id="uav07", source_file="UAV07.pdf", page_number=12, source_type="table", content="หัวฉีด 500 ml")
        chunks = chunk_knowledge_unit(unit)
        self.addCleanup(collection.delete, ids=[chunk.id for chunk in chunks])
        with patch("app.rag.vector_store.embed_text", return_value=[1.0] + [0.0] * 3071) as embed:
            add_chunks(chunks)
            add_chunks(chunks)
            result = search("หัวฉีด", n_results=1)
        self.assertEqual(embed.call_count, 2)  # one ingestion embedding + one query; reingest is cached
        self.assertEqual(result["documents"][0][0], unit.content)
        self.assertEqual(result["metadatas"][0][0]["page_number"], "12")
        self.assertEqual(len(collection.get(ids=[chunks[0].id])["ids"]), 1)

    def test_excluded_ingestion_rejected_before_embedding(self):
        unit = KnowledgeUnit(id="excluded", document_id="uav01", source_file="UAV01 Air Law.pdf", page_number=1, source_type="text", content="old law")
        with patch("app.rag.vector_store.embed_text") as embed, self.assertRaises(ValueError):
            add_chunks(chunk_knowledge_unit(unit))
        embed.assert_not_called()

    def test_text_table_chart_kept_and_expansion_batched_once(self):
        metadata = {"source_file": "UAV07.pdf", "page_number": "12", "source_type": "text"}
        fake = MagicMock()
        fake.query.return_value = {"documents": [["TEXT_EVIDENCE", "OTHER_PAGE"]],
            "metadatas": [[metadata, {**metadata, "page_number": "13"}]], "distances": [[0.1, 0.2]]}
        fake.get.return_value = {"documents": ["TEXT_EVIDENCE", "TABLE_EVIDENCE", "CHART_EVIDENCE", "OTHER_PAGE"],
            "metadatas": [metadata, {**metadata, "source_type": "table"}, {**metadata, "source_type": "chart"}, {**metadata, "page_number": "13"}]}
        with patch("app.rag.slide_retriever.RETRIEVER_BM25", "top50"), patch("app.rag.slide_retriever.RETRIEVER_RERANK", "legacy"), patch("app.rag.slide_retriever.collection", fake), patch("app.rag.slide_retriever.embed_text", return_value=[1.0]) as embed:
            result = search_slides_pipeline("หัวฉีด", top_k=2)
        for content in ["TEXT_EVIDENCE", "TABLE_EVIDENCE", "CHART_EVIDENCE", "OTHER_PAGE"]:
            self.assertIn(content, result["context"])
        fake.get.assert_called_once()
        self.assertEqual(len(result["top_pages"]), 2)
        self.assertEqual(embed.call_args.kwargs["max_retries"], 1)
        self.assertLessEqual(embed.call_args.kwargs["timeout_seconds"], 3)

    def test_retrieval_filters_excluded_documents_even_if_already_indexed(self):
        fake = MagicMock()
        fake.query.return_value = {"documents": [["old law"]], "metadatas": [[{"source_file": "UAV01 Air Law.pdf", "page_number": "1"}]], "distances": [[0.1]]}
        with patch("app.rag.slide_retriever.RETRIEVER_BM25", "top50"), patch("app.rag.slide_retriever.RETRIEVER_RERANK", "legacy"), patch("app.rag.slide_retriever.collection", fake), patch("app.rag.slide_retriever.embed_text", return_value=[1.0]):
            self.assertEqual(search_slides_pipeline("โดรน")["context"], "")
        fake.get.assert_not_called()

    def test_page_expansion_failure_preserves_initial_chunk(self):
        fake = MagicMock()
        fake.query.return_value = {"documents": [["หัวฉีด 500 ml"]], "metadatas": [[{"source_file": "UAV07.pdf", "page_number": "12", "source_type": "text"}]], "distances": [[0.1]]}
        fake.get.side_effect = RuntimeError("failed")
        with patch("app.rag.slide_retriever.RETRIEVER_BM25", "top50"), patch("app.rag.slide_retriever.RETRIEVER_RERANK", "legacy"), patch("app.rag.slide_retriever.collection", fake), patch("app.rag.slide_retriever.embed_text", return_value=[1.0]):
            self.assertIn("500 ml", search_slides_pipeline("หัวฉีด")["context"])
