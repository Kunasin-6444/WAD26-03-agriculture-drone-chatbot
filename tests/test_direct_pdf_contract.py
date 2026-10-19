import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pymupdf
import httpx
from google import genai

from app.rag import direct_pdf as pdf
from app.rag import rag_service
from app.rag.crag_service import run_crag_pipeline
from app.rag.embedding import embed_pdf_page
from app.rag.evidence import document_evidence
from scripts.ingest_pdf import ingest_pdf
from tests.helpers import llm_client, result_json

VECTOR = [1.0] + [0.0] * (pdf.DIMENSIONS - 1)


class DirectPdfContract(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        for patcher in [patch.object(pdf, "CACHE_DIR", self.root / "cache"),
                        patch.dict(os.environ, {"PDF_RETRIEVAL_MODE": "text", "PDF_READER_MODEL": "test-reader",
                                                "PDF_READ_MAX_PAGES": "3", "PDF_READ_TIMEOUT_SECONDS": "10"})]:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.collection = pdf.get_collection()
        self.path = self.root / f"UAV07-{self.root.name}.pdf"
        self.addCleanup(self._clear)
        self._make_document(2)

    def _clear(self):
        rows = self.collection.get(where={"source_file": self.path.name})
        if rows["ids"]:
            self.collection.delete(ids=rows["ids"])

    def _make_document(self, count):
        with pymupdf.open() as doc:
            for number in range(count):
                page = doc.new_page()
                page.insert_text((40, 60), f"Nozzle page {number + 1}: 500 ml at 1600 rpm")
            doc.save(self.path)

    def _ingest(self, **kwargs):
        with patch.object(pdf, "embed_pdf_page", return_value=VECTOR):
            return pdf.ingest_pdf_direct(str(self.path), "uav07", **kwargs)

    def _pages(self):
        return self.collection.get(where={"source_file": self.path.name}, include=["metadatas"])["metadatas"]

    def _response(self, entries, finish="STOP"):
        return SimpleNamespace(text=json.dumps({"pages": entries}, ensure_ascii=False),
                               candidates=[SimpleNamespace(finish_reason=finish)])

    def test_embedding_api_receives_pdf_bytes_and_bounded_timeout(self):
        with pymupdf.open(self.path) as doc:
            data = doc.tobytes()
        with patch("app.rag.embedding.client.models.embed_content",
                   return_value=SimpleNamespace(embeddings=[SimpleNamespace(values=VECTOR)])) as api:
            self.assertEqual(embed_pdf_page(data, max_retries=1, timeout_seconds=4), VECTOR)
        args = api.call_args.kwargs
        part = args["contents"][0].parts[0]
        self.assertEqual(part.inline_data.mime_type, "application/pdf")
        self.assertEqual(part.inline_data.data, data)
        self.assertIsNone(part.text)
        self.assertEqual(args["model"], "gemini-embedding-2")
        self.assertEqual(args["config"].http_options.timeout, 4000)

    def test_direct_cli_dispatch_skips_legacy_vision_and_chunk_embedding(self):
        with patch.object(pdf, "ingest_pdf_direct") as direct, \
             patch("scripts.ingest_pdf.analyze_pdf_page") as vision, \
             patch("scripts.ingest_pdf.add_chunks") as chunks:
            ingest_pdf(str(self.path), "uav07", start_page=2, end_page=2, mode="direct")
        direct.assert_called_once_with(str(self.path), "uav07", 2, 2)
        vision.assert_not_called()
        chunks.assert_not_called()

    def test_one_pdf_page_per_vector_metadata_preserved_and_cache_reused(self):
        observed = []
        def embed(data):
            with pymupdf.open(stream=data, filetype="pdf") as page:
                self.assertEqual(len(page), 1)
                observed.append(page[0].get_text())
            return VECTOR
        with patch.object(pdf, "embed_pdf_page", side_effect=embed) as api:
            report = pdf.ingest_pdf_direct(str(self.path), "uav07")
            pdf.ingest_pdf_direct(str(self.path), "uav07")
        self.assertEqual(api.call_count, 2)
        self.assertEqual(report["pages"], 2)
        self.assertIn("page 1", observed[0])
        self.assertIn("page 2", observed[1])
        pages = self._pages()
        self.assertEqual(len(pages), 2)
        for page in pages:
            self.assertEqual(page["source_file"], self.path.name)
            self.assertEqual(page["document_id"], "uav07")
            self.assertEqual(page["source_type"], "pdf_page")
            self.assertEqual(page["embedding_model"], "gemini-embedding-2")
            self.assertTrue(pdf._page_bytes(page).startswith(b"%PDF-"))
        self.assertEqual({p["page_number"] for p in pages}, {"1", "2"})

    def test_real_uav07_page12_keeps_original_table_in_embedded_pdf(self):
        source = next(Path("data").glob("UAV07*.pdf"))
        fake = MagicMock()
        def embed(data):
            with pymupdf.open(stream=data, filetype="pdf") as page:
                self.assertEqual(len(page), 1)
                self.assertIn("2.8", page[0].get_text())
            return VECTOR
        with patch.object(pdf, "get_collection", return_value=fake), \
             patch.object(pdf, "embed_pdf_page", side_effect=embed):
            pdf.ingest_pdf_direct(str(source), "uav07", 12, 12)
        meta = fake.upsert.call_args.kwargs["metadatas"][0]
        self.assertEqual(meta["source_file"], source.name)
        self.assertEqual(meta["page_number"], "12")
        fake.delete.assert_not_called()

    def test_failed_reembedding_preserves_published_pages(self):
        self._ingest()
        old = self._pages()
        with patch.object(pdf, "_embedding", side_effect=[VECTOR, RuntimeError("429")]), \
             self.assertRaises(RuntimeError):
            pdf.ingest_pdf_direct(str(self.path), "uav07")
        self.assertEqual(self._pages(), old)

    def test_full_reingest_removes_shortened_document_pages(self):
        self._ingest()
        self._make_document(1)
        self._ingest()
        self.assertEqual([m["page_number"] for m in self._pages()], ["1"])

    def test_partial_reingest_keeps_other_pages(self):
        self._ingest()
        self._ingest(start_page=2, end_page=2)
        self.assertEqual({m["page_number"] for m in self._pages()}, {"1", "2"})

    def test_invalid_ranges_and_excluded_documents_never_embed(self):
        with patch.object(pdf, "embed_pdf_page") as embed:
            for start, end in [(0, 1), (2, 1), (1, 3), (3, None)]:
                with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                    pdf.ingest_pdf_direct(str(self.path), "uav07", start, end)
            with self.assertRaises(ValueError):
                pdf.ingest_pdf_direct("data/UAV01 Air Law.pdf", "uav01")
        embed.assert_not_called()

    def test_corrupt_vector_cache_is_recomputed(self):
        data = b"%PDF-test"
        digest = pdf._digest(data)
        path = pdf.CACHE_DIR / "embeddings" / pdf.EMBEDDING_MODEL / f"{digest}.json"
        pdf._write(path, b"[0]")
        with patch.object(pdf, "embed_pdf_page", return_value=VECTOR) as embed:
            self.assertEqual(pdf._embedding(data, digest), VECTOR)
        embed.assert_called_once_with(data)

    def test_dense_retrieval_roundtrip_never_uses_page_labels_as_evidence(self):
        self._ingest()
        with patch.object(pdf, "embed_text", return_value=VECTOR) as embed:
            pages = pdf.search_pdf_pages("หัวฉีดพัดส้มไหลเท่าไร", top_k=2)
        self.assertEqual({p["page_number"] for p in pages}, {"1", "2"})
        embed.assert_called_once_with("หัวฉีดพัดส้มไหลเท่าไร", max_retries=1, timeout_seconds=3.0)
        self.assertNotIn("content", pages[0])

    def test_reader_preserves_thai_table_evidence_and_caches_without_another_api_call(self):
        self._ingest(start_page=2, end_page=2)
        pages = self._pages()
        text = "หัวฉีดพัดส้ม | อัตราการไหล 500 ml/หัวฉีด | 1600 rpm"
        response = self._response([{"id": "P1", "text": text}])
        with patch.object(pdf.client.models, "generate_content", return_value=response) as api:
            first = pdf.read_pdf_pages(pages, time.monotonic() + 15)
            second = pdf.read_pdf_pages(pages, time.monotonic() + 15)
        self.assertEqual(first, {"P1": text})
        self.assertEqual(second, first)
        api.assert_called_once()
        kwargs = api.call_args.kwargs
        pdf_parts = [p for p in kwargs["contents"] if isinstance(p, pdf.types.Part) and p.inline_data]
        self.assertEqual(pdf_parts[0].inline_data.data, pdf._page_bytes(pages[0]))
        self.assertEqual(kwargs["config"].http_options.timeout, 10000)
        self.assertEqual(kwargs["config"].http_options.retry_options.attempts, 1)

    def test_reader_rejects_invented_duplicate_or_missing_page_ids_and_truncation(self):
        self._ingest(start_page=1, end_page=1)
        pages = self._pages()
        for entries, finish in [([{"id": "P9", "text": "500 ml"}], "STOP"),
                                ([{"id": "P1", "text": "a"}, {"id": "P1", "text": "b"}], "STOP"),
                                ([], "STOP"), ([{"id": "P1", "text": "500 ml"}], "MAX_TOKENS")]:
            with self.subTest(entries=entries, finish=finish), \
                 patch.object(pdf.client.models, "generate_content", return_value=self._response(entries, finish)):
                self.assertEqual(pdf.read_pdf_pages(pages, time.monotonic() + 15), {})

    def test_real_sdk_serializes_reader_schema_without_unsupported_additional_properties(self):
        self._ingest(start_page=1, end_page=1)
        bodies = []
        def transport(request):
            body = json.loads(request.content)
            bodies.append(body)
            schema = body["generationConfig"]["responseSchema"]
            self.assertNotIn("additional", json.dumps(schema))
            self.assertEqual(schema["required"], ["pages"])
            self.assertEqual(schema["properties"]["pages"]["items"]["required"], ["id", "text"])
            return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {
                "role": "model", "parts": [{"text": json.dumps({"pages": [{"id": "P1", "text": "500 ml"}]})}]}}]})
        with genai.Client(api_key="offline-test-credential", http_options=pdf.types.HttpOptions(
                client_args={"transport": httpx.MockTransport(transport)})) as client, \
             patch.object(pdf, "client", client):
            transcripts = pdf.read_pdf_pages(self._pages(), time.monotonic() + 15)
        self.assertEqual(len(bodies), 1)
        self.assertEqual(transcripts, {"P1": "500 ml"})

    def test_expired_deadline_and_tampered_snapshot_do_not_call_reader(self):
        self._ingest(start_page=1, end_page=1)
        pages = self._pages()
        with patch.object(pdf.client.models, "generate_content") as api:
            self.assertEqual(pdf.read_pdf_pages(pages, time.monotonic() - 1), {})
            self.assertEqual(pdf.read_pdf_pages(pages, time.monotonic() + 9), {})
            (pdf.CACHE_DIR / "pages" / f"{pages[0]['page_sha256']}.pdf").write_bytes(b"tampered")
            self.assertEqual(pdf.read_pdf_pages(pages, time.monotonic() + 15), {})
        api.assert_not_called()

    def test_reader_failure_preserves_other_cached_pages(self):
        self._ingest()
        pages = self._pages()
        first = self._response([{"id": "P1", "text": "หัวฉีด 500 ml"}])
        with patch.object(pdf.client.models, "generate_content", return_value=first):
            pdf.read_pdf_pages(pages[:1], time.monotonic() + 15)
        with patch.object(pdf.client.models, "generate_content", side_effect=RuntimeError("429")):
            result = pdf.read_pdf_pages(pages, time.monotonic() + 15)
        self.assertEqual(result, {"P1": "หัวฉีด 500 ml"})

    def test_invalid_snapshot_path_is_rejected(self):
        with self.assertRaises(ValueError):
            pdf._page_bytes({"page_sha256": "../outside"})

    def test_direct_retrieval_integrates_with_grounded_answer_and_original_page_citation(self):
        self._ingest(start_page=2, end_page=2)
        client = llm_client(result_json())
        transcript = self._response([{"id": "P1", "text": "หัวฉีดพัดส้ม อัตราการไหล 500 ml/หัวฉีด ที่รอบ 1600 rpm"}])
        with patch.dict(os.environ, {"PDF_RETRIEVAL_MODE": "direct"}), \
             patch.object(pdf, "embed_text", return_value=VECTOR), \
             patch.object(pdf.client.models, "generate_content", return_value=transcript), \
             patch("app.rag.crag_service.search_web_fallback") as web:
            answer = run_crag_pipeline("หัวฉีดพัดส้มไหลเท่าไร", client=client)
        self.assertEqual(answer.source_type, "knowledge_base")
        self.assertIn("500", answer.answer)
        self.assertIn(f"{self.path.name}, หน้า 2", answer.answer)
        self.assertTrue(answer.evidence_trace)
        web.assert_not_called()

    def test_reader_failure_does_not_turn_pdf_filename_into_an_answer(self):
        self._ingest(start_page=1, end_page=1)
        client = llm_client()
        with patch.dict(os.environ, {"PDF_RETRIEVAL_MODE": "direct"}), \
             patch.object(pdf, "embed_text", return_value=VECTOR), \
             patch.object(pdf.client.models, "generate_content", side_effect=TimeoutError()), \
             patch("app.rag.crag_service.search_web_fallback", return_value=[]):
            answer = run_crag_pipeline("หัวฉีดพัดส้มไหลเท่าไร", client=client)
        self.assertEqual(answer.source_type, "abstain")
        self.assertEqual(answer.evidence_trace, [])
        client.chat.completions.create.assert_not_called()

    def test_expired_retrieval_budget_returns_no_evidence_or_requests(self):
        with patch.object(pdf, "search_pdf_pages") as search:
            self.assertEqual(pdf.search_pdf_context("หัวฉีด", deadline=time.monotonic() + 1), "")
        search.assert_not_called()

    def test_mode_selection_defaults_to_legacy_and_direct_warmup_avoids_bm25(self):
        with patch("app.rag.slide_retriever.search_slides_pipeline", return_value={"context": "legacy"}) as search:
            self.assertEqual(rag_service.retrieve_context("หัวฉีด"), "legacy")
        search.assert_called_once()
        with patch.dict(os.environ, {"PDF_RETRIEVAL_MODE": "direct"}), \
             patch("app.rag.slide_retriever.warm_up") as legacy:
            rag_service.warm_up_retrieval()
        legacy.assert_not_called()
        with patch.dict(os.environ, {"PDF_RETRIEVAL_MODE": "typo"}), self.assertRaises(ValueError):
            pdf.enabled()
