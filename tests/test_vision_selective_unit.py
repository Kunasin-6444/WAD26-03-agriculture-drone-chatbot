import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import pymupdf

from app.ingestion.vision_extractor import (
    should_use_vision,
    get_cache_path,
    load_vision_cache,
    save_vision_cache,
    analyze_pdf_page,
    VisionPageResult,
    VisualElement,
)
from app.ingestion.knowledge_builder import build_page_knowledge_units


class TestSelectiveVisionUnit(unittest.TestCase):
    """
    Unit tests for selective vision heuristic, edge cases, and caching.
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.pdf_dir = Path("data")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_synthetic_pdf(self, pages_spec: list[dict]) -> str:
        """
        Helper to create synthetic PDF documents with precise visual elements.
        pages_spec: list of dicts with keys:
            - text: str
            - add_image: tuple (width, height) or None
            - add_drawings: int (number of rectangles)
        """
        pdf_path = os.path.join(self.test_dir, "synthetic_test.pdf")
        doc = pymupdf.open()

        for spec in pages_spec:
            page = doc.new_page(width=595, height=842)
            text = spec.get("text", "")
            if text:
                page.insert_text((50, 72), text, fontsize=12)

            img_size = spec.get("add_image")
            if img_size:
                w, h = img_size
                pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, w, h), False)
                pix.clear_with(0x88)
                img_bytes = pix.tobytes("png")
                page.insert_image(pymupdf.Rect(50, 150, 50 + w, 150 + h), stream=img_bytes)

            drawing_count = spec.get("add_drawings", 0)
            for i in range(drawing_count):
                rect = pymupdf.Rect(50, 200 + i * 20, 200, 215 + i * 20)
                page.draw_rect(rect, color=(0, 0, 1), fill=(0.9, 0.9, 1))

        doc.save(pdf_path)
        doc.close()
        return pdf_path

    # --------------------------------------------------
    # Edge Case 1: Pure text page should skip Vision
    # --------------------------------------------------
    def test_pure_text_page_skips_vision(self):
        pdf_path = self._create_synthetic_pdf([
            {
                "text": "นี่คือหน้าเอกสารที่มีแต่ข้อความภาษาไทยธรรมดา ไม่มีรูปภาพและไม่มีไดอะแกรมซับซ้อนใดๆ ทั้งสิ้น",
                "add_image": None,
                "add_drawings": 0,
            }
        ])

        use_vision, reason = should_use_vision(pdf_path, 1)
        self.assertFalse(use_vision)
        self.assertEqual(reason, "pure_text_page")

    # --------------------------------------------------
    # Edge Case 2: Page with tiny icon/logo (< 150x150) should skip Vision
    # --------------------------------------------------
    def test_tiny_logo_ignored_skips_vision(self):
        pdf_path = self._create_synthetic_pdf([
            {
                "text": "เอกสารรายงานหัวเรื่อง มีโลโก้มหาวิทยาลัยขนาดเล็กมากอยู่ที่มุมบนของหน้ากระดาษ",
                "add_image": (60, 40),
                "add_drawings": 2,
            }
        ])

        use_vision, reason = should_use_vision(pdf_path, 1)
        self.assertFalse(use_vision)
        self.assertEqual(reason, "pure_text_page")

    # --------------------------------------------------
    # Edge Case 3: Page with large content image (> 150x150) triggers Vision
    # --------------------------------------------------
    def test_content_image_triggers_vision(self):
        pdf_path = self._create_synthetic_pdf([
            {
                "text": "ภาพถ่ายอุปกรณ์หัวฉีดโดรนการเกษตร",
                "add_image": (400, 300),
                "add_drawings": 0,
            }
        ])

        use_vision, reason = should_use_vision(pdf_path, 1)
        self.assertTrue(use_vision)
        self.assertIn("content_images", reason)

    # --------------------------------------------------
    # Edge Case 4: Page with complex vector drawings triggers Vision
    # --------------------------------------------------
    def test_complex_drawings_triggers_vision(self):
        pdf_path = self._create_synthetic_pdf([
            {
                "text": "แผนผังระบบ Flowchart กระบวนการพ่นยา",
                "add_image": None,
                "add_drawings": 15,
            }
        ])

        use_vision, reason = should_use_vision(pdf_path, 1)
        self.assertTrue(use_vision)
        self.assertIn("complex_vector_drawings", reason)

    # --------------------------------------------------
    # Edge Case 5: Sparse text with banner/graphics triggers Vision
    # --------------------------------------------------
    def test_sparse_text_with_graphics_triggers_vision(self):
        pdf_path = self._create_synthetic_pdf([
            {
                "text": "หน้าปก",
                "add_image": (100, 100),
                "add_drawings": 3,
            }
        ])

        use_vision, reason = should_use_vision(pdf_path, 1)
        self.assertTrue(use_vision)
        self.assertEqual(reason, "sparse_text_with_graphics")

    # --------------------------------------------------
    # Edge Case 6: Real PDF Pages Verification
    # --------------------------------------------------
    def test_real_pdf_uav07_and_uav09(self):
        # UAV09 Page 5 is pure text
        uav09_files = [f for f in os.listdir("data") if "UAV09" in f]
        if uav09_files:
            uav09_path = os.path.join("data", uav09_files[0])
            use_v, reason = should_use_vision(uav09_path, 5)
            self.assertFalse(use_v, f"UAV09 Page 5 should skip vision, got {reason}")
            self.assertEqual(reason, "pure_text_page")

        # UAV07 Page 8 has the color table photo (content image)
        uav07_files = [f for f in os.listdir("data") if "UAV07" in f]
        if uav07_files:
            uav07_path = os.path.join("data", uav07_files[0])
            use_v8, reason8 = should_use_vision(uav07_path, 8)
            self.assertTrue(use_v8, f"UAV07 Page 8 must trigger vision, got {reason8}")

            # UAV07 Page 20 has droplet comparison image (content image)
            use_v20, reason20 = should_use_vision(uav07_path, 20)
            self.assertTrue(use_v20, f"UAV07 Page 20 must trigger vision, got {reason20}")

    # --------------------------------------------------
    # Edge Case 7: Caching behavior (hit vs miss)
    # --------------------------------------------------
    def test_caching_behavior(self):
        cache_dir = os.path.join(self.test_dir, "cache")
        pdf_path = self._create_synthetic_pdf([
            {"text": "หน้าทดสอบแคช", "add_image": None, "add_drawings": 0}
        ])

        # Step 1: analyze_pdf_page on pure text should produce [VISION_SKIPPED] and save to cache
        res1 = analyze_pdf_page(
            pdf_path=pdf_path,
            page_number=1,
            force_vision=False,
            cache_dir=cache_dir,
        )
        self.assertFalse(res1.has_meaningful_visual_content)
        self.assertTrue(res1.summary.startswith("[VISION_SKIPPED]"))

        # Verify cache file was created
        cache_path = get_cache_path(pdf_path, 1, cache_dir)
        self.assertTrue(cache_path.exists())

        # Step 2: Call again - should load directly from cache
        res2 = analyze_pdf_page(
            pdf_path=pdf_path,
            page_number=1,
            force_vision=False,
            cache_dir=cache_dir,
        )
        self.assertEqual(res1.summary, res2.summary)

    # --------------------------------------------------
    # Edge Case 8: Integration with KnowledgeBuilder (no crash on skipped)
    # --------------------------------------------------
    def test_knowledge_builder_integration_with_skipped_vision(self):
        uav09_files = [f for f in os.listdir("data") if "UAV09" in f]
        self.assertTrue(len(uav09_files) > 0)
        uav09_path = os.path.join("data", uav09_files[0])

        skipped_result = VisionPageResult(
            has_meaningful_visual_content=False,
            summary="[VISION_SKIPPED] pure_text_page",
            elements=[],
        )

        units = build_page_knowledge_units(
            pdf_path=uav09_path,
            document_id="uav09",
            page_number=5,
            vision_result=skipped_result,
        )

        # Must extract native text unit
        self.assertTrue(len(units) >= 1)
        text_units = [u for u in units if u.source_type == "text"]
        self.assertTrue(len(text_units) >= 1)
        self.assertTrue(len(text_units[0].content.strip()) > 50)

        # Must NOT extract any image or vision units
        vision_units = [u for u in units if u.source_type in {"image", "diagram", "chart", "mixed"}]
        self.assertEqual(len(vision_units), 0)


if __name__ == "__main__":
    unittest.main()
