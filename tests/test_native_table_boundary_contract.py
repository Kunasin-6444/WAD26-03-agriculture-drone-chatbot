import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pymupdf

from app.ingestion.knowledge_builder import build_page_knowledge_units


class NativeTableBoundaryTests(unittest.TestCase):
    def test_table_overlap_cannot_remove_a_citation_in_the_same_text_block(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "UAV99.pdf"
            doc = pymupdf.open()
            page = doc.new_page(width=400, height=300)
            page.insert_textbox(pymupdf.Rect(30, 30, 350, 180), "Header Value\nA 500\nAdapted from Study (2525)", fontsize=12)
            self.assertEqual(len(page.get_text("blocks")), 1)
            doc.save(path)
            doc.close()
            table = SimpleNamespace(bbox=(20, 25, 360, 65), extract=lambda: [["Header", "Value"], ["A", "500"]])
            with patch.object(pymupdf.Page, "find_tables", return_value=SimpleNamespace(tables=[table])):
                units = build_page_knowledge_units(str(path), "UAV99", 1)
        text = "\n".join(unit.content for unit in units if unit.metadata.get("source") == "pdf_text")
        self.assertIn("Study (2525)", text)
        self.assertNotIn("A 500", text)
