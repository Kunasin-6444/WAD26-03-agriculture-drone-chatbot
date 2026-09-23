import unittest
from pathlib import Path

from app.ingestion.knowledge_builder import build_page_knowledge_units


class TestKnowledgeBuilderUnit(unittest.TestCase):
    def test_uav07_p12_text_excludes_table_numbers(self):
        pdf_path = "data/UAV07 หัวฉีดกับคุณภาพการฉีดพ่นของโดรนเกษตร.pdf"
        if not Path(pdf_path).exists():
            self.skipTest(f"{pdf_path} not found")

        units = build_page_knowledge_units(
            pdf_path=pdf_path,
            document_id="uav07",
            page_number=12,
            vision_result=None,
        )

        # There should be 1 text unit and 1 native table unit
        types = [u.source_type for u in units]
        self.assertIn("text", types)
        self.assertIn("table", types)

        text_unit = next(u for u in units if u.source_type == "text")
        table_unit = next(u for u in units if u.source_type == "table")

        # Table unit must contain the table data
        self.assertIn("0.5", table_unit.content)
        self.assertIn("1.4", table_unit.content)
        self.assertIn("3.1", table_unit.content)

        # Text unit must NOT contain table numbers (deduplication verified!)
        self.assertNotIn("0.5", text_unit.content)
        self.assertNotIn("1.4", text_unit.content)
        self.assertNotIn("3.1", text_unit.content)


if __name__ == "__main__":
    unittest.main()
