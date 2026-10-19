import os
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pymupdf

from app.ingestion.models import KnowledgeUnit
from app.ingestion.vision_extractor import VisionPageResult, get_cache_path
from app.rag import slide_retriever, vector_store
from app.rag.chunking import chunk_knowledge_unit
from app.rag.embedding_cache import cached_document_embedding
from scripts.ingest_pdf import ingest_pdf

VECTOR = [1.0] + [0.0] * 3071


class IngestionReliabilityContract(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.pdf = self.root / "UAV99.pdf"
        self._write_pdf("first version")

    def _write_pdf(self, text, pages=1):
        with pymupdf.open() as doc:
            for number in range(pages):
                page = doc.new_page()
                page.insert_text((40, 60), f"{text} page {number + 1}")
            doc.save(self.pdf)

    def _unit(self, number):
        return KnowledgeUnit(id=f"test-{self.root.name}-{number}", document_id="UAV99",
            source_file=self.pdf.name, page_number=number, source_type="text", content=f"evidence {number}")

    def test_vision_cache_changes_when_same_filename_content_changes(self):
        before = get_cache_path(self.pdf, 1, self.root / "cache")
        self._write_pdf("updated version")
        self.assertNotEqual(before, get_cache_path(self.pdf, 1, self.root / "cache"))

    def test_vision_cache_changes_with_model(self):
        with patch.dict(os.environ, {"VISION_MODEL": "model-a"}):
            before = get_cache_path(self.pdf, 1, self.root / "cache")
        with patch.dict(os.environ, {"VISION_MODEL": "model-b"}):
            after = get_cache_path(self.pdf, 1, self.root / "cache")
        self.assertNotEqual(before, after)

    def test_upsert_failure_never_deletes_published_chunks(self):
        fake = MagicMock()
        fake.get.return_value = {"ids": ["old"], "metadatas": [{"page_number": "1"}]}
        fake.upsert.side_effect = RuntimeError("storage unavailable")
        with patch.object(vector_store, "collection", fake), \
             patch.object(vector_store, "CHROMA_PATH", self.root), \
             patch.object(vector_store, "embed_text", return_value=VECTOR), self.assertRaises(RuntimeError):
            vector_store.add_chunks(chunk_knowledge_unit(self._unit(1)), self.pdf.name, range(1, 2))
        fake.delete.assert_not_called()

    def test_same_chunk_count_update_invalidates_bm25(self):
        slide_retriever._bm25_cache.clear()
        self.addCleanup(slide_retriever._bm25_cache.clear)
        fake = MagicMock()
        fake.count.return_value = 1
        fake.get.side_effect = [{"ids": ["same-id"], "documents": ["old content"], "metadatas": [{}]},
                                {"ids": ["same-id"], "documents": ["new content"], "metadatas": [{}]}]
        with patch.object(slide_retriever, "collection", fake):
            self.assertEqual(slide_retriever._bm25_index()["docs"], ["old content"])
            self.assertEqual(slide_retriever._bm25_index()["docs"], ["new content"])

    def test_cached_native_page_has_no_unconditional_sleep_and_returns_report(self):
        with patch("scripts.ingest_pdf.analyze_pdf_page", return_value=VisionPageResult(summary="[VISION_SKIPPED] pure_text_page")), \
             patch("scripts.ingest_pdf.build_page_knowledge_units", return_value=[self._unit(1)]), \
             patch("scripts.ingest_pdf.add_chunks") as add, patch("scripts.ingest_pdf.time.sleep") as sleep:
            report = ingest_pdf(str(self.pdf), "UAV99", report_path=self.root / "report.json")
        sleep.assert_not_called()
        self.assertTrue(report["complete"])
        self.assertEqual(report["processed_pages"], [1])
        self.assertTrue((self.root / "report.json").exists())
        records = json.loads((self.root / "report.records.json").read_text(encoding="utf-8"))
        self.assertEqual(records["schema"], "ingestion_records_v1")
        self.assertEqual(records["chunks"][0]["metadata"]["source_sha256"], report["source_sha256"])
        self.assertEqual(add.call_args.kwargs["chunks"][0].metadata["source_sha256"], report["source_sha256"])

    def test_failed_page_is_reported_and_other_pages_are_still_processed(self):
        self._write_pdf("three pages", pages=3)
        with patch("scripts.ingest_pdf.analyze_pdf_page", return_value=VisionPageResult(summary="[VISION_SKIPPED] pure_text_page")), \
             patch("scripts.ingest_pdf.build_page_knowledge_units", side_effect=[[self._unit(1)], RuntimeError("broken page"), [self._unit(3)]]), \
             patch("scripts.ingest_pdf.add_chunks") as add:
            report = ingest_pdf(str(self.pdf), "UAV99", report_path=self.root / "report.json")
        self.assertFalse(report["complete"])
        self.assertEqual(report["failed_pages"], {"2": "RuntimeError"})
        self.assertEqual(report["processed_pages"], [1, 3])
        self.assertEqual(set(add.call_args.kwargs["replace_pages"]), {1, 3})

    def test_vision_failure_is_not_reported_as_complete_ingestion(self):
        with patch("scripts.ingest_pdf.analyze_pdf_page", return_value=VisionPageResult(summary="[VISION_EXTRACTION_FAILED] quota")), \
             patch("scripts.ingest_pdf.build_page_knowledge_units", return_value=[self._unit(1)]), \
             patch("scripts.ingest_pdf.add_chunks") as add:
            report = ingest_pdf(str(self.pdf), "UAV99", report_path=self.root / "report.json")
        self.assertFalse(report["complete"])
        self.assertEqual(report["degraded_pages"], [1])
        add.assert_not_called()

    def test_vision_failure_cannot_replace_previously_complete_page(self):
        self._write_pdf("three pages", pages=3)
        vision = [VisionPageResult(summary="[VISION_SKIPPED] pure_text_page"),
                  VisionPageResult(summary="[VISION_EXTRACTION_FAILED] quota"),
                  VisionPageResult(summary="[VISION_SKIPPED] pure_text_page")]
        with patch("scripts.ingest_pdf.analyze_pdf_page", side_effect=vision), \
             patch("scripts.ingest_pdf.build_page_knowledge_units", side_effect=[[self._unit(1)], [self._unit(3)]]), \
             patch("scripts.ingest_pdf.add_chunks") as add:
            report = ingest_pdf(str(self.pdf), "UAV99", report_path=self.root / "report.json")
        self.assertEqual(report["degraded_pages"], [2])
        self.assertEqual(set(add.call_args.kwargs["replace_pages"]), {1, 3})
        self.assertTrue(all(c.page_number != 2 for c in add.call_args.kwargs["chunks"]))

    def test_out_of_range_page_fails_before_processing(self):
        with patch("scripts.ingest_pdf.analyze_pdf_page") as vision, self.assertRaises(ValueError):
            ingest_pdf(str(self.pdf), "UAV99", start_page=3, end_page=3)
        vision.assert_not_called()

    def test_document_embedding_cache_keys_include_model_and_content(self):
        embed = MagicMock(return_value=VECTOR)
        directory = self.root / "embeddings"
        cached_document_embedding("first text", "model-a", directory, embed)
        cached_document_embedding("first text", "model-a", directory, embed)
        cached_document_embedding("changed text", "model-a", directory, embed)
        cached_document_embedding("first text", "model-b", directory, embed)
        self.assertEqual(embed.call_count, 3)

    def test_corrupt_document_embedding_cache_is_recomputed(self):
        embed = MagicMock(return_value=VECTOR)
        directory = self.root / "embeddings"
        cached_document_embedding("text", "model-a", directory, embed)
        next(directory.glob("*.json")).write_text("[]", encoding="utf-8")
        self.assertEqual(cached_document_embedding("text", "model-a", directory, embed), VECTOR)
        self.assertEqual(embed.call_count, 2)

    def test_source_provenance_survives_chunking_and_cannot_override_canonical_page(self):
        unit = self._unit(1)
        unit.metadata.update(source_sha256="source-hash", source="vision", page_number="999")
        chunk = chunk_knowledge_unit(unit)[0]
        self.assertEqual(chunk.metadata["source_sha256"], "source-hash")
        self.assertEqual(chunk.metadata["source"], "vision")
        self.assertEqual(chunk.metadata["page_number"], "1")

    def test_cli_exits_nonzero_for_incomplete_ingestion(self):
        from scripts.ingest_pdf import main
        with patch("sys.argv", ["ingest_pdf", str(self.pdf), "UAV99"]), \
             patch("scripts.ingest_pdf.ingest_pdf", return_value={"complete": False}), \
             self.assertRaises(SystemExit) as exit_status:
            main()
        self.assertEqual(exit_status.exception.code, 1)

    def test_batch_continues_after_incomplete_file_but_returns_failure(self):
        from scripts.ingest_all_data import ingest_all
        with patch("scripts.ingest_all_data.Path.glob", return_value=[Path("UAV07.pdf"), Path("UAV08.pdf")]), \
             patch("scripts.ingest_all_data.ingest_pdf", side_effect=[{"complete": False}, {"complete": True}]) as run, \
             patch("scripts.ingest_all_data.time.sleep"), self.assertRaises(SystemExit):
            ingest_all()
        self.assertEqual(run.call_count, 2)

    def test_vision_output_is_capped_so_a_looping_page_fails_fast(self):
        from app.ingestion import vision_extractor as vision
        with patch.object(vision.client.models, "generate_content") as api,              patch.dict("os.environ", {"VISION_MAX_OUTPUT_TOKENS": "4096"}):
            vision.generate_with_retry(b"image", "extract", max_retries=1)
        self.assertEqual(api.call_args.kwargs["config"].max_output_tokens, 4096)
        truncated = type("R", (), {"candidates": [type("C", (), {"finish_reason": "MAX_TOKENS"})()]})()
        with self.assertRaises(RuntimeError):
            vision.parse_vision_response(truncated)

    def test_last_rate_limit_failure_does_not_sleep_without_another_attempt(self):
        from google.genai.errors import ClientError
        from app.ingestion import vision_extractor as vision
        error = ClientError(429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}})
        with patch.object(vision.client.models, "generate_content", side_effect=error) as api, \
             patch.object(vision.time, "sleep") as sleep, self.assertRaises(RuntimeError):
            vision.generate_with_retry(b"image", "extract", max_retries=1)
        api.assert_called_once()
        sleep.assert_not_called()
