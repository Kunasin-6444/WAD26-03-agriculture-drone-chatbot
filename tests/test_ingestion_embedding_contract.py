import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pymupdf

from app.ingestion.knowledge_builder import build_page_knowledge_units, make_unit_id, rows_to_text
from app.ingestion.vision_extractor import VisionPageResult, VisualElement, analyze_pdf_page, should_use_vision
from app.rag.embedding import embed_text
from scripts.ingest_pdf import ingest_pdf


class IngestionEmbeddingContractTests(unittest.TestCase):
    def test_real_uav07_page12_native_table_preserves_values_and_metadata(self):
        path = next(Path("data").glob("UAV07*.pdf"))
        units = build_page_knowledge_units(str(path), "uav07", 12)
        table = next(unit for unit in units if unit.source_type == "table")
        self.assertIn("2.8", table.content)
        self.assertEqual(table.page_number, 12)
        self.assertEqual(table.source_file, path.name)
        text = next(unit for unit in units if unit.source_type == "text")
        self.assertNotIn("2.8", text.content)

    def test_visual_evidence_and_source_origin_preserved(self):
        path = next(Path("data").glob("UAV07*.pdf"))
        vision = VisionPageResult(has_meaningful_visual_content=True, summary="ตารางหัวฉีด", elements=[VisualElement(type="table", status="clear", description="ตาราง", extracted_text="พัดส้ม 500 ml", visual_description="หน่วยต่อหัวฉีด")])
        units = build_page_knowledge_units(str(path), "uav07", 12, vision)
        self.assertEqual(len({u.id for u in units}), len(units))
        visual = next(u for u in units if u.metadata.get("source") == "vision")
        self.assertIn("500 ml", visual.content)
        self.assertEqual(visual.extracted_text, "พัดส้ม 500 ml")
        self.assertEqual(visual.metadata["vision_status"], "clear")

    def test_unit_ids_distinguish_native_and_vision_tables(self):
        self.assertNotEqual(make_unit_id("uav07", 12, "table", 1, "native_table"), make_unit_id("uav07", 12, "table", 1, "vision"))
        self.assertEqual(rows_to_text([["หัวฉีด", "ml"], ["ส้ม", 500]]), "หัวฉีด | ml\nส้ม | 500")

    def test_native_text_skips_external_vision_and_caches(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "text.pdf"
            doc = pymupdf.open()
            page = doc.new_page()
            page.insert_text((30, 60), "Normal document text " * 15)
            doc.save(path)
            doc.close()
            with patch("app.ingestion.vision_extractor.generate_with_retry") as api:
                first = analyze_pdf_page(str(path), 1, cache_dir=Path(folder) / "cache")
                second = analyze_pdf_page(str(path), 1, cache_dir=Path(folder) / "cache")
            api.assert_not_called()
            self.assertTrue(first.summary.startswith("[VISION_SKIPPED]"))
            self.assertEqual(first, second)

    def test_meaningful_real_visual_page_triggers_vision(self):
        path = next(Path("data").glob("UAV07*.pdf"))
        self.assertTrue(should_use_vision(str(path), 8)[0])

    def test_excluded_pdf_cli_rejected_before_processing(self):
        with patch("scripts.ingest_pdf.analyze_pdf_page") as vision, self.assertRaises(ValueError):
            ingest_pdf("data/UA03 AIR SPACE.pdf", "ua03")
        vision.assert_not_called()

    def test_embedding_returns_vector_with_configured_timeout(self):
        response = SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0, 2.0, 3.0])])
        with patch("app.rag.embedding.client.models.embed_content", return_value=response) as api:
            self.assertEqual(embed_text("หัวฉีด", max_retries=1, timeout_seconds=3), [1, 2, 3])
        config = api.call_args.kwargs["config"]
        self.assertEqual(config.http_options.timeout, 3000)
        self.assertEqual(config.http_options.retry_options.attempts, 1)

    def test_query_embedding_failure_has_no_retry_sleep(self):
        with patch("app.rag.embedding.client.models.embed_content", side_effect=RuntimeError("429")) as api, patch("app.rag.embedding.time.sleep") as sleep:
            with self.assertRaises(RuntimeError):
                embed_text("หัวฉีด", max_retries=1, timeout_seconds=3)
        api.assert_called_once()
        sleep.assert_not_called()

    def test_empty_embedding_rejected_before_api(self):
        with patch("app.rag.embedding.client.models.embed_content") as api, self.assertRaises(ValueError):
            embed_text("  ")
        api.assert_not_called()
