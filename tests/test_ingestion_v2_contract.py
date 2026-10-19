"""Contract tests for the v2 ingestion pipeline. Offline: synthetic PDFs, fake vision and
embedding clients, an isolated Chroma collection."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import chromadb
import pymupdf

from app.ingestion import pipeline
from app.ingestion.layout import build_paragraphs, join_lines, needs_vision, read_page
from app.ingestion.structured_chunker import split_long
from app.ingestion.tables import GROUP_COLUMN, LogicalTable, TablePart, TableRow, is_group_row, stitch, table_chunks
from app.ingestion.vision_extractor import TableRow as VisionRow
from app.ingestion.vision_extractor import VisionPageResult, VisualElement, get_cache_path
from app.rag import embedding
from app.rag.embedding_cache import cached_document_embeddings
from app.rag.slide_retriever import _order_by_seq
from scripts.verify_ingestion import table_header_problems

HEADER = ["Brand", "Model", "Tank_L", "Speed_ms", "Width_m", "Price_THB"]
ROWS = [[f"B{i}", f"M{i}", str(10 + i), "10", str(4 + i % 4), str(200000 + i * 1000)] for i in range(60)]
THAI_FONT = Path("C:/Windows/Fonts/tahoma.ttf")


def vector(text: str) -> list[float]:
    return [float(len(text) % 7 + 1)] + [0.0] * 3071


def draw_table(page, top, rows, widths=(60, 60, 60, 60, 60, 80), height=22):
    y = top
    for row in rows:
        x = 40
        for width, cell in zip(widths, row):
            page.draw_rect(pymupdf.Rect(x, y, x + width, y + height), color=(0, 0, 0), width=0.7)
            page.insert_text((x + 3, y + 15), cell, fontsize=8)
            x += width
        y += height
    return y


def save(doc, path: Path) -> Path:
    doc.save(path)
    doc.close()
    return path


class Fixture(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)  # Chroma keeps its sqlite file open on Windows
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.collection = chromadb.PersistentClient(path=str(self.root / "db")).get_or_create_collection("drone_test")
        self.embed_calls: list[list[str]] = []
        self.vision_calls: list[int] = []
        self.vision_result = VisionPageResult(has_meaningful_visual_content=True, summary="figure summary",
                                              elements=[VisualElement(type="photo", description="a figure",
                                                                      extracted_text="label 12")])

    def deps(self, vision=None):
        def embed(texts):
            self.embed_calls.append(list(texts))
            return [vector(t) for t in texts]

        def vision_fn(pdf, page, sha):
            self.vision_calls.append(page)
            if vision:
                return vision(pdf, page, sha)
            return self.vision_result

        return pipeline.Deps(vision_fn, embed, self.collection, self.root / "emb", "test-model")

    def options(self, **kwargs):
        return pipeline.Options(report_dir=self.root / "reports", workers=2, **kwargs)

    def table_pdf(self, name="UAV98 table.pdf") -> Path:
        doc = pymupdf.open()
        first = doc.new_page()
        first.insert_text((40, 40), "Table 4 Drone price list", fontsize=9)
        draw_table(first, 60, [HEADER] + ROWS[:30])
        draw_table(doc.new_page(), 40, ROWS[30:])
        return save(doc, self.root / name)

    def stored(self, **where):
        found = self.collection.get(where=where or None, include=["documents", "metadatas"])
        return list(zip(found["ids"], found["documents"], found["metadatas"]))


class TextRules(unittest.TestCase):
    def test_thai_wraps_join_without_a_space_and_other_wraps_with_one(self):
        self.assertEqual(join_lines("ผลตอบแท", "น"), "ผลตอบแทน")
        self.assertEqual(join_lines("ข้อมูลที่รอบด้านและ", "การวิเคราะห์"), "ข้อมูลที่รอบด้านและการวิเคราะห์")
        self.assertEqual(join_lines("price 10", "baht"), "price 10 baht")
        self.assertEqual(join_lines("ข้าว", "10 ไร่"), "ข้าว 10 ไร่")

    def test_split_long_keeps_every_word_and_respects_the_limit(self):
        text = "First sentence is here. Second sentence follows it. Third one ends the paragraph."
        pieces = split_long(text, 40)
        self.assertTrue(all(len(p) <= 40 for p in pieces))
        self.assertEqual(" ".join(pieces).split(), text.split())

    def test_a_lone_page_number_is_not_ingested(self):
        from app.ingestion.layout import Paragraph
        from app.ingestion.structured_chunker import text_pieces
        pieces = text_pieces([Paragraph(1, "7", (), 700.0, 710.0), Paragraph(1, "Real sentence about nozzles.", (), 100.0, 110.0)])
        self.assertEqual(["Real sentence about nozzles."], [p.content for p in pieces])

    def test_unbroken_run_longer_than_the_limit_is_hard_cut(self):
        pieces = split_long("x" * 25, 10)
        self.assertEqual(["x" * 10, "x" * 10, "x" * 5], pieces)


class NativeTablesWinOverVision(Fixture):
    def build(self, vision_table_rows):
        pdf = self.root / "UAV98 one table.pdf"
        doc = pymupdf.open()
        draw_table(doc.new_page(), 60, [HEADER] + ROWS[:12])
        save(doc, pdf)
        with pymupdf.open(pdf) as opened:
            layouts = [read_page(page) for page in opened]
        table = VisualElement(type="table", description="price table",
                              extracted_text="; ".join(", ".join(row) for row in vision_table_rows))
        photo = VisualElement(type="photo", description="drone photo", extracted_text="label 12")
        result = VisionPageResult(has_meaningful_visual_content=True, elements=[table, photo])
        chunks, _, _ = pipeline._build(pdf, "UAV98", "sha", layouts, {1}, {1: result})
        return "\n".join(chunk.content for chunk in chunks)

    def test_a_table_the_text_layer_holds_comes_from_the_text_layer_not_vision(self):
        misread = [[cell.replace("Brand", "Brnad") for cell in row] for row in [HEADER] + ROWS[:12]]
        text = self.build(misread)
        self.assertNotIn("Brnad", text)
        self.assertIn("B11 | M11", text)       # the native row, row-aligned
        self.assertIn("label 12", text)        # the photo still comes from vision

    def test_a_table_from_a_damaged_thai_text_layer_does_not_replace_vision(self):
        vision = VisionPageResult(elements=[VisualElement(
            type="table", extracted_text="รายการ, บูมสเปรย์, โดรน; ใช้น้ำมาก, 160, 100; ต้นทุนต่ำลง, 120, 100")])
        damaged = "รายการ | บูมสเปรย์ | โดรน\nใช้น้ ามาก | 160 | 100\nต้นทุนต่ าลง | 120 | 100"
        clean = damaged.replace("น้ า", "น้ำ").replace("ต่ า", "ต่ำ")
        self.assertEqual(len(pipeline.drop_vision_tables_native_covers(vision, 15, damaged).elements), 1)
        self.assertEqual(len(pipeline.drop_vision_tables_native_covers(vision, 15, clean).elements), 0)

    def test_a_vision_table_with_numbers_the_text_layer_lacks_is_kept(self):
        text = self.build([HEADER] + [[f"X{i}", "M", "99", "10", "4", str(777000 + i)] for i in range(12)])
        self.assertIn("777000", text)


class TableStitching(unittest.TestCase):
    def part(self, page, rows, **kwargs):
        return TablePart(page, rows, "pdf_native_table", **kwargs)

    def test_continuation_inherits_header_and_is_one_table(self):
        head = tuple(HEADER)
        a = self.part(1, [head] + [tuple(r) for r in ROWS[:3]], y0=100, y1=780, page_height=842, text_above=True)
        b = self.part(2, [tuple(r) for r in ROWS[3:6]], y0=40, y1=200, page_height=842, text_above=False)
        (table,) = stitch([a, b], "D-t")
        self.assertEqual(head, table.header)
        self.assertEqual([1, 2], table.pages)
        self.assertEqual({2}, table.inherited_pages)
        self.assertEqual(6, len(table.rows))

    def test_repeated_header_is_not_stored_as_data(self):
        head = tuple(HEADER)
        a = self.part(1, [head, tuple(ROWS[0])], y0=100, y1=780, page_height=842, text_above=True)
        b = self.part(2, [head, tuple(ROWS[1])], y0=40, y1=200, page_height=842, text_above=False)
        (table,) = stitch([a, b], "D-t")
        self.assertEqual([tuple(ROWS[0]), tuple(ROWS[1])], [r.cells for r in table.rows])
        self.assertEqual(set(), table.inherited_pages)

    def test_text_above_the_table_or_a_gap_in_pages_starts_a_new_table(self):
        head = tuple(HEADER)
        a = self.part(1, [head, tuple(ROWS[0])], y0=100, y1=780, page_height=842, text_above=True)
        titled = self.part(2, [head, tuple(ROWS[1])], y0=40, y1=200, page_height=842, text_above=True)
        self.assertEqual(2, len(stitch([a, titled], "D-t")))
        later = self.part(4, [tuple(ROWS[2])], y0=40, y1=200, page_height=842, text_above=False)
        self.assertEqual(2, len(stitch([a, later], "D-t")))

    def test_table_not_at_the_page_edges_is_not_a_continuation(self):
        head = tuple(HEADER)
        short = self.part(1, [head, tuple(ROWS[0])], y0=100, y1=300, page_height=842, text_above=True)
        nxt = self.part(2, [tuple(ROWS[1])], y0=40, y1=200, page_height=842, text_above=False)
        self.assertEqual(2, len(stitch([short, nxt], "D-t")))

    def test_group_rows_become_a_context_column_and_leave_values_untouched(self):
        rows = [("Name", "Rate", "Note"), ("Group 1: Systemic", "", ""), ("a", "5-10 g", "x"),
                ("Group 2: Contact", "", ""), ("b", "20 cc", "y")]
        (table,) = stitch([self.part(1, rows)], "D-t")
        self.assertEqual(("Name", "Rate", "Note", GROUP_COLUMN), table.header)
        self.assertEqual([("a", "5-10 g", "x", "Group 1: Systemic"), ("b", "20 cc", "y", "Group 2: Contact")],
                         [r.cells for r in table.rows])

    def test_a_displaced_value_row_merges_into_the_row_above_instead_of_becoming_a_group(self):
        rows = [("Brand", "Model", "Tank", "Price"), ("DJI", "T10", "8", "220"), ("NAc", "E70", "", "369"),
                ("", "", "50", ""), ("XAG", "P100", "50", "568")]
        (table,) = stitch([self.part(1, rows)], "D-t")
        self.assertFalse(table.group_column)
        self.assertEqual(("NAc", "E70", "50", "369"), table.rows[1].cells)
        self.assertEqual(3, len(table.rows))

    def test_text_spilling_onto_the_next_page_rejoins_its_row(self):
        head = ("Brand", "Model", "Kit", "Price")
        a = self.part(1, [head, ("DJI", "T40", "remote, battery", "422")], y0=100, y1=780, page_height=842, text_above=True)
        b = self.part(2, [("", "", "charger x1", ""), ("DJI", "T50", "remote", "427")], y0=40, y1=200,
                      page_height=842, text_above=False)
        (table,) = stitch([a, b], "D-t")
        self.assertEqual(("DJI", "T40", "remote, battery charger x1", "422"), table.rows[0].cells)
        self.assertEqual(2, len(table.rows))

    def test_chunks_record_the_pages_their_rows_and_header_really_span(self):
        a = self.part(1, [("Brand", "Model", "Kit", "Price")], y0=300, y1=780, page_height=842, text_above=True)
        b = self.part(2, [("", "", "spilled text", ""), ("DJI", "T50", "remote", "427")], y0=40, y1=780,
                      page_height=842, text_above=False)
        c = self.part(3, [("XAG", "P100", "kit", "568")], y0=40, y1=200, page_height=842, text_above=False)
        (table,) = stitch([a, b, c], "D-t")
        chunks = table_chunks(table)
        self.assertEqual([(2, 1, 2), (3, 3, 3)], [(ch.page, ch.page_from, ch.page_end) for ch in chunks])

    def test_a_long_merged_label_gives_a_short_context_column_and_keeps_its_description_once(self):
        label = ("4: Trace elements (EDTA Chelated) Chelated trace elements are wrapped in organic matter, "
                 "so plants take them up faster and they do not precipitate when mixed")
        rows = [("Type", "Name", "Rate"), (label, "", ""), ("", "Mg-EDTA", "5 g"), ("", "Zn-EDTA", "5 g")]
        (table,) = stitch([self.part(1, rows)], "D-t")
        self.assertEqual(["4: Trace elements (EDTA Chelated)"] * 2, [row.cells[-1] for row in table.rows])
        self.assertEqual([(1, label)], table.notes)

    def test_a_label_at_the_foot_of_a_page_is_kept_even_though_its_rows_start_on_the_next(self):
        head = ("Name", "Rate", "Note")
        a = self.part(1, [head, ("Group 1", "", ""), ("a", "1", "x"), ("Group 2", "", "")],
                      y0=100, y1=780, page_height=842, text_above=True)
        b = self.part(2, [("b", "2", "y")], y0=40, y1=200, page_height=842, text_above=False)
        (table,) = stitch([a, b], "D-t")
        self.assertEqual([(1, "Group 2")], table.notes)
        self.assertEqual("Group 2", table.rows[-1].cells[-1])

    def test_a_bare_number_in_the_first_column_is_not_a_group_label(self):
        self.assertFalse(is_group_row(("50", "", "")))
        self.assertTrue(is_group_row(("Group 1", "", "")))

    def test_a_merged_title_row_on_top_is_a_caption_not_data(self):
        rows = [("Table 9 Prices", "", ""), ("Name", "Rate", "Note"), ("a", "5", "x")]
        (table,) = stitch([self.part(1, rows)], "D-t")
        self.assertEqual("Table 9 Prices", table.caption)
        self.assertEqual(("Name", "Rate", "Note"), table.header)
        self.assertEqual(1, len(table.rows))

    def test_chunks_split_on_row_boundaries_and_repeat_the_header(self):
        rows = [TableRow(1, (f"row{i}", "value " * 8, str(i))) for i in range(80)]
        table = LogicalTable("D-t1", "pdf_native_table", ("Name", "Text", "N"), rows, pages=[1])
        chunks = table_chunks(table, max_chars=400)
        self.assertGreater(len(chunks), 3)
        seen = []
        for chunk in chunks:
            lines = chunk.content.splitlines()
            self.assertEqual("Name | Text | N", lines[0])
            self.assertTrue(all(line.count(" | ") == 2 for line in lines))
            self.assertLessEqual(len(chunk.content), 400 + 80)
            seen += lines[1:]
        self.assertEqual([f"row{i} | {'value ' * 8} | {i}" for i in range(80)], seen)

    def test_chunks_never_span_pages(self):
        rows = [TableRow(1 + i // 5, (f"r{i}", "v")) for i in range(10)]
        table = LogicalTable("D-t1", "pdf_native_table", ("A", "B"), rows, pages=[1, 2],
                             inherited_pages={2})
        chunks = table_chunks(table)
        self.assertEqual([1, 2], [c.page for c in chunks])
        self.assertEqual([False, True], [c.header_inherited for c in chunks])
        self.assertEqual([(1, 5), (6, 10)], [(c.row_start, c.row_end) for c in chunks])


class LayoutReading(Fixture):
    def test_headings_define_sections_and_wrapped_lines_form_one_paragraph(self):
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((40, 60), "1. Spraying basics", fontsize=18, fontname="hebo")
        page.insert_text((40, 90), "Body text that wraps onto", fontsize=10)
        page.insert_text((40, 103), "a second printed line.", fontsize=10)
        page.insert_text((40, 160), "A separate later paragraph.", fontsize=10)
        page.insert_text((40, 200), "- bullet one", fontsize=10)
        path = save(doc, self.root / "a.pdf")
        with pymupdf.open(path) as opened:
            layouts = [read_page(opened[0])]
        paragraphs = build_paragraphs(layouts)
        self.assertEqual(["heading", "paragraph", "paragraph", "paragraph"], [p.kind for p in paragraphs])
        self.assertEqual("Body text that wraps onto a second printed line.", paragraphs[1].text)
        self.assertEqual(("1. Spraying basics",), paragraphs[1].section)
        self.assertEqual(("1. Spraying basics",), paragraphs[3].section)

    @unittest.skipUnless(THAI_FONT.exists(), "needs a Thai font")
    def test_thai_text_wrapped_inside_a_word_is_rejoined(self):
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((40, 60), "ผลตอบแท", fontsize=12, fontfile=str(THAI_FONT), fontname="th")
        page.insert_text((40, 74), "นของการลงทุน", fontsize=12, fontfile=str(THAI_FONT), fontname="th")
        path = save(doc, self.root / "thai.pdf")
        with pymupdf.open(path) as opened:
            paragraphs = build_paragraphs([read_page(opened[0])])
        self.assertEqual("ผลตอบแทนของการลงทุน", paragraphs[0].text)

    def test_unnumbered_bold_headings_nest_under_a_numbered_one_and_are_siblings_of_each_other(self):
        doc = pymupdf.open()
        page = doc.new_page()
        for y, text, size, font in [(60, "3.1.3. Usage", 16, "hebo"), (90, "Before flight", 10, "hebo"),
                                    (110, "Check the propellers carefully before every flight.", 10, "helv"),
                                    (150, "After use", 10, "hebo"), (170, "Wash the tank and the pump after use.", 10, "helv")]:
            page.insert_text((40, y), text, fontsize=size, fontname=font)
        path = save(doc, self.root / "n.pdf")
        with pymupdf.open(path) as opened:
            paragraphs = build_paragraphs([read_page(opened[0])])
        body = [p for p in paragraphs if p.kind == "paragraph"]
        self.assertEqual(("3.1.3. Usage", "Before flight"), body[0].section)
        self.assertEqual(("3.1.3. Usage", "After use"), body[1].section)

    def test_a_section_number_and_its_title_on_two_lines_form_one_heading(self):
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((40, 60), "3.1.2.", fontsize=16, fontname="hebo")
        page.insert_text((40, 80), "System specifications", fontsize=16, fontname="hebo")
        page.insert_text((40, 120), "Body text under the heading.", fontsize=10)
        path = save(doc, self.root / "h.pdf")
        with pymupdf.open(path) as opened:
            paragraphs = build_paragraphs([read_page(opened[0])])
        self.assertEqual(["3.1.2. System specifications"], [p.text for p in paragraphs if p.kind == "heading"])
        self.assertEqual(("3.1.2. System specifications",), paragraphs[-1].section)
        from app.ingestion.structured_chunker import text_pieces
        self.assertIn("3.1.2. System specifications", text_pieces(paragraphs)[0].content)

    def test_a_line_that_ends_short_is_a_deliberate_break_and_a_full_line_is_a_wrap(self):
        from app.ingestion.layout import Line, paragraph_text
        full = Line(1, "ข้อมูลที่รอบด้านและ", 10.0, False, 40, 100, 110, 500.0)
        short = Line(1, "ที่แม่นยำ", 10.0, False, 40, 112, 122, 120.0)
        nxt = Line(1, "เพื่อให้ผู้ประกอบการ", 10.0, False, 40, 124, 134, 200.0)
        self.assertEqual("ข้อมูลที่รอบด้านและที่แม่นยำ", paragraph_text([full, short], 500.0))
        self.assertEqual("ที่แม่นยำ เพื่อให้ผู้ประกอบการ", paragraph_text([short, nxt], 500.0))

    def test_cell_text_keeps_pdf_character_order_and_separates_deliberate_line_breaks(self):
        doc = pymupdf.open()
        page = doc.new_page()
        draw_table(page, 60, [["Name", "Note"], ["x", "y"]], widths=(120, 150), height=60)
        page.insert_text((46, 150), "Rate 5 g", fontsize=8)      # a short line: ended on purpose
        page.insert_text((46, 161), "Advice: rinse", fontsize=8)
        path = save(doc, self.root / "cell.pdf")
        with pymupdf.open(path) as opened:
            layout = read_page(opened[0])
        self.assertEqual("x Rate 5 g Advice: rinse", layout.tables[0].rows[1][0])

    def test_blank_page_is_recognised_and_needs_no_vision(self):
        doc = pymupdf.open()
        doc.new_page()
        path = save(doc, self.root / "blank.pdf")
        with pymupdf.open(path) as opened:
            layout = read_page(opened[0])
        self.assertTrue(layout.blank)
        self.assertFalse(layout.vision)

    def _picture(self):
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 200), False)
        pix.clear_with(180)
        return pix

    def test_large_figure_needs_vision_but_a_picture_inside_a_table_cell_does_not(self):
        doc = pymupdf.open()
        figure = doc.new_page()
        figure.insert_text((40, 60), "A page of normal prose " * 8, fontsize=9)
        figure.insert_image(pymupdf.Rect(60, 200, 460, 500), pixmap=self._picture())
        grid = doc.new_page()
        grid.insert_text((40, 40), "A page of normal prose " * 8, fontsize=9)
        draw_table(grid, 60, [["Photo", "Spec"], ["x", "y"]], widths=(250, 250), height=200)
        grid.insert_image(pymupdf.Rect(45, 262, 285, 452), pixmap=self._picture())
        path = save(doc, self.root / "v.pdf")
        with pymupdf.open(path) as opened:
            fig, tab = read_page(opened[0]), read_page(opened[1])
        self.assertTrue(fig.vision)
        self.assertTrue(fig.vision_reason.startswith("figure"))
        self.assertFalse(tab.vision, tab.vision_reason)

    def test_a_mostly_empty_grid_is_not_a_table_and_keeps_its_words_as_text(self):
        doc = pymupdf.open()
        page = doc.new_page()
        draw_table(page, 60, [["y = 0.93x", "", "", ""], ["R2 = 0.82", "", "", ""], ["", "", "Train", "289"]],
                   widths=(70, 70, 70, 70))
        path = save(doc, self.root / "chart.pdf")
        with pymupdf.open(path) as opened:
            layout = read_page(opened[0])
        self.assertEqual([], layout.tables)
        self.assertIn("y = 0.93x", " ".join(line.text for line in layout.lines))

    def test_table_borders_alone_do_not_count_as_a_diagram(self):
        with pymupdf.open(self.table_pdf()) as opened:
            self.assertFalse(read_page(opened[0]).vision)


class PipelineContract(Fixture):
    def run_pdf(self, pdf, **kwargs):
        return pipeline.run([pdf], self.options(**kwargs), self.deps())

    def test_table_across_pages_is_published_with_headers_pages_and_order(self):
        (report,) = self.run_pdf(self.table_pdf())
        self.assertTrue(report["complete"], report)
        tables = sorted((m["row_start"], m["page_number"], m["header_inherited"], d)
                        for _, d, m in self.stored(source_type="table"))
        self.assertEqual({"1", "2"}, {t[1] for t in tables})
        for _, _, _, text in tables:
            self.assertTrue(text.startswith("Brand | Model"))
        rows = [line for *_, text in sorted(tables, key=lambda t: int(t[0])) for line in text.splitlines()[1:]]
        self.assertEqual([" | ".join(r) for r in ROWS], rows)
        self.assertEqual({"false", "true"}, {t[2] for t in tables})

    def test_every_chunk_keeps_the_metadata_retrieval_depends_on(self):
        self.run_pdf(self.table_pdf())
        for _, _, meta in self.stored():
            for key in ("source_file", "page_number", "document_id", "source_type", "source_sha256", "seq",
                        "ingestion_version", "embedding_model"):
                self.assertTrue(meta.get(key), (key, meta))
            self.assertTrue(meta["page_number"].isdigit())
            self.assertEqual("UAV98", meta["document_id"])

    def test_embeddings_are_batched_and_context_is_embedded_not_stored(self):
        self.run_pdf(self.table_pdf())
        self.assertEqual(1, len(self.embed_calls))
        stored = {d for _, d, _ in self.stored()}
        self.assertTrue(any("Table 4 Drone price list" in t for t in self.embed_calls[0]))
        self.assertTrue(all("table › " not in d for d in stored))
        self.assertTrue(any(t.startswith("table › ") or t.startswith("table\u203a") or "›" in t.splitlines()[0]
                            for t in self.embed_calls[0]))

    def test_unchanged_file_is_skipped_without_any_api_call(self):
        pdf = self.table_pdf()
        self.run_pdf(pdf)
        before = len(self.embed_calls)
        (report,) = self.run_pdf(pdf)
        self.assertEqual("up_to_date", report["skipped"])
        self.assertEqual(before, len(self.embed_calls))
        self.assertEqual([], self.vision_calls)

    def test_changed_file_replaces_every_old_chunk(self):
        pdf = self.table_pdf()
        self.run_pdf(pdf)
        old_ids = {i for i, _, _ in self.stored()}
        doc = pymupdf.open()
        doc.new_page().insert_text((40, 60), "Completely different content now.", fontsize=10)
        save(doc, pdf)
        (report,) = self.run_pdf(pdf)
        self.assertTrue(report["complete"], report)
        new_ids = {i for i, _, _ in self.stored()}
        self.assertFalse(old_ids & new_ids)
        self.assertEqual(1, len(new_ids))

    def test_page_range_replaces_only_those_pages(self):
        pdf = self.table_pdf()
        self.run_pdf(pdf)
        page_two = {i for i, _, m in self.stored() if m["page_number"] == "2"}
        (report,) = self.run_pdf(pdf, pages=(1, 1))
        self.assertTrue(report["complete"], report)
        self.assertEqual(page_two, {i for i, _, m in self.stored() if m["page_number"] == "2"})

    def test_a_page_range_trial_never_makes_the_file_look_finished(self):
        pdf = self.table_pdf()
        self.run_pdf(pdf, pages=(1, 1))
        self.assertEqual("partial", pipeline.index_status(self.collection, pdf.name, pipeline.file_sha256(pdf)))
        (report,) = self.run_pdf(pdf)  # the default whole-file run must not skip it
        self.assertTrue(report["complete"], report)
        self.assertEqual("up_to_date", pipeline.index_status(self.collection, pdf.name, pipeline.file_sha256(pdf)))
        self.assertEqual({"1", "2"}, {m["page_number"] for _, _, m in self.stored()})
        self.assertFalse(any(m.get("partial_range") for _, _, m in self.stored()))

    def test_legacy_file_is_never_replaced_without_force(self):
        pdf = self.table_pdf()
        self.collection.upsert(ids=["old"], documents=["old text"], embeddings=[vector("x")],
                               metadatas=[{"source_file": pdf.name, "page_number": "1", "document_id": "UAV98",
                                           "source_type": "text"}])
        (report,) = self.run_pdf(pdf)
        self.assertEqual("legacy_requires_force", report["skipped"])
        self.assertEqual(["old"], [i for i, _, _ in self.stored()])
        (forced,) = pipeline.run([pdf], self.options(force=True), self.deps())
        self.assertTrue(forced["complete"], forced)
        self.assertNotIn("old", [i for i, _, _ in self.stored()])

    def test_excluded_document_is_rejected_before_any_work(self):
        pdf = self.table_pdf("UA03 AIR SPACE.pdf")
        (report,) = self.run_pdf(pdf)
        self.assertEqual("excluded", report["skipped"])
        with self.assertRaises(ValueError):
            pipeline.ingest_document(pdf, self.options(), self.deps())
        self.assertEqual([], self.embed_calls + self.vision_calls)
        self.assertEqual([], self.stored())

    def test_embedding_failure_leaves_the_index_untouched(self):
        pdf = self.table_pdf()
        self.run_pdf(pdf)
        before = self.stored()
        doc = pymupdf.open()
        doc.new_page().insert_text((40, 60), "Changed before a quota failure.", fontsize=10)
        save(doc, pdf)
        deps = self.deps()
        deps.embed_batch = MagicMock(side_effect=RuntimeError("429"))
        (report,) = pipeline.run([pdf], self.options(), deps)
        self.assertFalse(report["complete"])
        self.assertEqual(before, self.stored())

    def test_upsert_failure_never_deletes_the_published_chunks(self):
        pdf = self.table_pdf()
        self.run_pdf(pdf)
        before = self.stored()
        doc = pymupdf.open()
        doc.new_page().insert_text((40, 60), "Changed before storage failed.", fontsize=10)
        save(doc, pdf)
        broken = MagicMock(wraps=self.collection)
        broken.upsert.side_effect = RuntimeError("storage unavailable")
        deps = self.deps()
        deps.collection = broken
        (report,) = pipeline.run([pdf], self.options(), deps)
        self.assertFalse(report["complete"])
        broken.delete.assert_not_called()
        self.assertEqual(before, self.stored())

    def test_source_changing_during_ingestion_is_refused(self):
        pdf = self.table_pdf()
        deps = self.deps()
        original = deps.embed_batch

        def embed_then_modify(texts):
            vectors = original(texts)
            doc = pymupdf.open()
            doc.new_page().insert_text((40, 60), "Swapped mid run.", fontsize=10)
            doc.save(pdf)
            return vectors

        deps.embed_batch = embed_then_modify
        (report,) = pipeline.run([pdf], self.options(), deps)
        self.assertFalse(report["complete"])
        self.assertEqual([], self.stored())

    def test_blank_page_does_not_make_ingestion_incomplete(self):
        doc = pymupdf.open()
        doc.new_page().insert_text((40, 60), "Some prose on the first page.", fontsize=10)
        doc.new_page()
        (report,) = self.run_pdf(save(doc, self.root / "UAV97 blank.pdf"))
        self.assertTrue(report["complete"], report)
        self.assertEqual([2], report["blank_pages"])

    def _figure_pdf(self, name="UAV96 fig.pdf"):
        doc = pymupdf.open()
        first = doc.new_page()
        first.insert_text((40, 60), "Plain text page " * 6, fontsize=10)
        second = doc.new_page()
        second.insert_text((40, 60), "Figure page " * 6, fontsize=10)
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 200), False)
        pix.clear_with(150)
        second.insert_image(pymupdf.Rect(60, 200, 460, 500), pixmap=pix)
        return save(doc, self.root / name)

    def test_vision_runs_only_for_pages_that_need_it_and_adds_its_content(self):
        (report,) = self.run_pdf(self._figure_pdf())
        self.assertEqual([2], self.vision_calls)
        self.assertEqual({"2"}, set(report["vision_pages"]))
        self.assertTrue(report["complete"], report)
        self.assertTrue(any("label 12" in d for _, d, m in self.stored() if m["source"] == "vision"))

    def test_vision_never_makes_no_calls(self):
        (report,) = self.run_pdf(self._figure_pdf(), vision="never")
        self.assertEqual([], self.vision_calls)
        self.assertTrue(report["complete"], report)

    def test_failed_vision_page_is_reported_and_never_replaces_the_old_page(self):
        pdf = self._figure_pdf()
        self.run_pdf(pdf)
        old_page_two = {i: d for i, d, m in self.stored() if m["page_number"] == "2"}
        self.assertTrue(old_page_two)
        pipeline_failed = lambda *_: VisionPageResult(summary="[VISION_EXTRACTION_FAILED] quota")
        (report,) = pipeline.run([pdf], self.options(force=True), self.deps(vision=pipeline_failed))
        self.assertFalse(report["complete"])
        self.assertEqual([2], report["degraded_pages"])
        self.assertEqual(old_page_two, {i: d for i, d, m in self.stored() if m["page_number"] == "2"})

    def test_a_gappy_whole_file_ingest_is_retried_by_the_next_default_run(self):
        pdf = self._figure_pdf()
        failing = lambda *_: VisionPageResult(summary="[VISION_EXTRACTION_FAILED] timeout")
        (report,) = pipeline.run([pdf], self.options(), self.deps(vision=failing))
        self.assertFalse(report["complete"])
        self.assertEqual("partial", pipeline.index_status(self.collection, pdf.name, pipeline.file_sha256(pdf)))
        (again,) = pipeline.run([pdf], self.options(), self.deps())
        self.assertTrue(again["complete"], again)
        self.assertEqual("up_to_date", pipeline.index_status(self.collection, pdf.name, pipeline.file_sha256(pdf)))

    def test_failed_visuals_on_a_new_page_keep_native_evidence_but_stay_incomplete(self):
        pdf = self._figure_pdf()
        failing = lambda *_: VisionPageResult(summary="[VISION_EXTRACTION_FAILED] timeout")
        (report,) = pipeline.run([pdf], self.options(), self.deps(vision=failing))
        self.assertFalse(report["complete"])
        self.assertEqual([2], report["native_only_pages"])
        native = [(d, m) for _, d, m in self.stored() if m["page_number"] == "2"]
        self.assertTrue(native)
        self.assertTrue(any("Figure page" in d for d, _ in native))
        self.assertTrue(all(m["extraction_complete"] == "false" and m["vision_status"] == "unavailable"
                            for _, m in native))
        self.assertEqual("partial", pipeline.index_status(self.collection, pdf.name, pipeline.file_sha256(pdf)))

    def test_empty_extraction_page_does_not_delete_previously_published_evidence(self):
        pdf = self.table_pdf()
        self.run_pdf(pdf)
        previous = {i: d for i, d, m in self.stored() if m["page_number"] == "2"}
        build = pipeline._build

        def lose_page(*args, **kwargs):
            chunks, _, tables = build(*args, **kwargs)
            chunks = [chunk for chunk in chunks if chunk.page_number == 1]
            return chunks, {1}, tables

        with patch.object(pipeline, "_build", side_effect=lose_page):
            (report,) = self.run_pdf(pdf, force=True)
        self.assertFalse(report["complete"])
        self.assertEqual([2], report["empty_pages"])
        self.assertEqual(previous, {i: d for i, d, m in self.stored() if m["page_number"] == "2"})

    def test_a_header_only_page_is_covered_by_its_continuing_table_rows(self):
        doc = pymupdf.open()
        columns = ["Brand", "Model", "Tank", "Speed", "Width", "Price", "Power", "Mass", "Note", "Kit"]
        draw_table(doc.new_page(), 780, [columns], widths=(45,) * 10)
        draw_table(doc.new_page(), 40, [["DJI", "M1", "50", "8", "6", "100", "5", "20", "a", "b"]],
                   widths=(45,) * 10)
        pdf = save(doc, self.root / "UAV94 header.pdf")
        (report,) = self.run_pdf(pdf)
        self.assertTrue(report["complete"], report)
        self.assertEqual([], report["empty_pages"])
        self.assertTrue(any(m.get("page_from") == "1" for _, _, m in self.stored()))

    def _seed_page(self, pdf, page, text, sha):
        meta = {"source_file": pdf.name, "page_number": str(page), "document_id": "UAV96", "source_type": "table",
                "source": "vision", "ingestion_version": "text_v4", "source_sha256": sha}
        self.collection.upsert(ids=[f"seed-{page}-{sha[:6]}"], documents=[text], embeddings=[vector(text)],
                               metadatas=[meta])

    def _failing(self):
        return self.deps(vision=lambda *_: VisionPageResult(summary="[VISION_EXTRACTION_FAILED] timeout"))

    def test_junk_on_a_failed_vision_page_is_replaced_by_its_clean_native_text(self):
        pdf = self._figure_pdf()
        sha = pipeline.file_sha256(pdf)
        self._seed_page(pdf, 2, "ขอบพระคุณครับท่านครับผมสวัสดีครับทุกท่านครับผม" * 40, sha)
        (report,) = pipeline.run([pdf], self.options(force=True), self._failing())
        self.assertFalse(report["complete"])
        page_two = [(d, m) for _, d, m in self.stored() if m["page_number"] == "2"]
        self.assertTrue(page_two)
        self.assertFalse(any("ขอบพระคุณ" in d for d, _ in page_two))
        self.assertTrue(all(m["source"] == "pdf_text" and m["extraction_complete"] == "false" for _, m in page_two))
        self.assertEqual("partial", pipeline.index_status(self.collection, pdf.name, sha))

    def test_a_failed_vision_page_never_keeps_chunks_of_another_pdf_version(self):
        pdf = self._figure_pdf()
        self._seed_page(pdf, 2, "Figure page from an older version of this PDF", "f" * 64)
        (report,) = pipeline.run([pdf], self.options(force=True), self._failing())
        self.assertEqual([2], report["native_only_pages"])
        self.assertFalse(any("older version" in d for _, d, _ in self.stored()))

    def test_junk_on_a_failed_page_without_native_text_is_removed_and_the_page_stays_missing(self):
        doc = pymupdf.open()
        doc.new_page().insert_text((40, 60), "Plain text page " * 6, fontsize=10)
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 200), False)
        pix.clear_with(120)
        doc.new_page().insert_image(pymupdf.Rect(60, 100, 500, 600), pixmap=pix)
        pdf = save(doc, self.root / "UAV94 picture.pdf")
        sha = pipeline.file_sha256(pdf)
        self._seed_page(pdf, 2, "standard layout correctly structured properly " * 40, sha)
        (report,) = pipeline.run([pdf], self.options(force=True), self._failing())
        self.assertEqual([2], report["purged_pages"])
        self.assertEqual([], [i for i, _, m in self.stored() if m["page_number"] == "2"])
        self.assertEqual("partial", pipeline.index_status(self.collection, pdf.name, sha))

    def test_vision_exception_is_a_degraded_page_not_a_crash(self):
        def boom(*_):
            raise RuntimeError("network")
        (report,) = pipeline.run([self._figure_pdf()], self.options(), self.deps(vision=boom))
        self.assertEqual([2], report["degraded_pages"])
        self.assertFalse(report["complete"])

    def test_vision_table_rows_become_header_carrying_chunks_and_stitch_across_pages(self):
        pdf = self._figure_pdf("UAV95 vt.pdf")

        def tables(_pdf, page, _sha):
            element = VisualElement(type="table", status="clear", description="price table",
                                    columns=["Model", "Price"] if page == 1 else [],
                                    rows=[VisionRow(cells=[f"M{page}{i}", f"{page}{i}00"]) for i in range(2)])
            return VisionPageResult(has_meaningful_visual_content=True, summary=None, elements=[element])

        (report,) = pipeline.run([pdf], self.options(vision="always"), self.deps(vision=tables))
        self.assertTrue(report["complete"], report)
        rows = sorted((m["page_number"], d) for _, d, m in self.stored(source="vision") if m["source_type"] == "table")
        self.assertEqual(["Model | Price\nM10 | 1000\nM11 | 1100", "Model | Price\nM20 | 2000\nM21 | 2100"],
                         [d for _, d in rows])

    def test_plan_is_offline_and_reports_cost_before_spending(self):
        pdf = self._figure_pdf()
        plan = pipeline.plan_document(pdf, self.options(), self.collection)
        self.assertEqual("new", plan.status)
        self.assertEqual({2}, set(plan.vision_pages))
        self.assertGreater(plan.estimated_chunks, 0)
        self.assertEqual([], self.embed_calls + self.vision_calls)
        self.assertEqual([], self.stored())

    def test_non_standard_document_id_is_flagged_in_the_plan(self):
        pdf = self.table_pdf("Investment guide.pdf")
        plan = pipeline.plan_document(pdf, self.options(), self.collection)
        self.assertTrue(any("convention" in w for w in plan.warnings))
        self.assertEqual("Investment_guide", plan.document_id)


class VerifierCoverage(unittest.TestCase):
    def test_a_chunk_covers_every_page_between_page_from_and_page_end(self):
        from scripts import verify_ingestion
        self.assertTrue(hasattr(verify_ingestion, "table_header_problems"))
        source = Path(verify_ingestion.__file__).read_text(encoding="utf-8")
        self.assertIn('meta.get("page_from")', source)
        self.assertIn('meta.get("page_end")', source)


class VisionLoopGuard(unittest.TestCase):
    def table(self, rows):
        return VisionPageResult(has_meaningful_visual_content=True, elements=[VisualElement(
            type="table", rows=[VisionRow(cells=list(r)) for r in rows])])

    def test_a_repeated_phrase_spread_over_table_cells_is_rejected(self):
        from app.ingestion.vision_extractor import validate_vision_result
        phrase = "standard layout correctly structured properly"
        with self.assertRaises(ValueError):
            validate_vision_result(self.table([(phrase, phrase) for _ in range(30)]))

    def test_a_looping_thai_paragraph_without_spaces_is_rejected(self):
        from app.ingestion.vision_extractor import validate_vision_result
        looped = VisionPageResult(summary="ตารางแสดงข้อมูลการใช้สารกำจัดวัชพืชในไร่อ้อย" * 40)
        with self.assertRaises(ValueError):
            validate_vision_result(looped)

    def test_a_genuine_table_full_of_repeated_values_is_accepted(self):
        from app.ingestion.vision_extractor import validate_vision_result
        names = ["อาลาคลอร์", "แอตทราซีน", "เมทริบูซีน", "ไดยูรอน", "อ็อกซี่ฟลูออร์เฟน", "ซัลเฟนทราโซน", "เพนดิเมทาลิน"] * 4
        rows = [(f"{name}{i}", f"{300 + i * 10}-{640 + i}", "พ่นก่อนวัชพืชงอก", "ใบแคบและกว้าง", "สามารถใช้ได้")
                for i, name in enumerate(names)]
        validate_vision_result(self.table(rows))  # must not raise

    def fallback_calls(self, first_failure):
        calls = []

        def analyze(pdf, page, structured_tables, **_):
            calls.append(structured_tables)
            if structured_tables:
                return VisionPageResult(summary=f"{pipeline.VISION_FAILED} {first_failure}")
            return VisionPageResult(has_meaningful_visual_content=True, summary="plain read")

        result = pipeline.vision_with_plain_fallback(analyze, Path("x.pdf"), 18, "sha")
        return calls, result

    def test_a_looping_cell_by_cell_read_is_retried_once_as_plain_text(self):
        for failure in ("Vision response contains a repeated-phrase generation loop",
                        "Vision response did not finish normally (MAX_TOKENS; output=16384, thinking=0 tokens)"):
            calls, result = self.fallback_calls(failure)
            self.assertEqual(calls, [True, False], failure)
            self.assertEqual(result.summary, "plain read")

    def test_an_outage_is_not_retried_as_plain_text(self):
        calls, result = self.fallback_calls("Gemini request failed after 3 attempts")
        self.assertEqual(calls, [True])
        self.assertTrue(result.summary.startswith(pipeline.VISION_FAILED))


class SupportingContracts(unittest.TestCase):
    def test_structured_vision_results_use_a_separate_cache_key(self):
        with tempfile.TemporaryDirectory() as folder:
            pdf = Path(folder) / "x.pdf"
            pdf.write_bytes(b"%PDF-1.4 a")
            self.assertNotEqual(get_cache_path(pdf, 1, folder), get_cache_path(pdf, 1, folder, structured_tables=True))

    def test_batch_embedding_falls_back_to_single_calls_on_a_miscounted_response(self):
        def reply(**kwargs):
            contents = kwargs["contents"]
            count = 1 if len(contents) > 1 else len(contents)  # a batch comes back short
            return SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0, 2.0]) for _ in range(count)])
        with patch("app.rag.embedding.client.models.embed_content", side_effect=reply) as api:
            vectors = embedding.embed_texts(["a", "b", "c"], batch_size=3, max_retries=1)
        self.assertEqual(3, len(vectors))
        self.assertEqual(4, api.call_count)  # one rejected batch, then three single calls

    def test_batch_embedding_uses_one_call_per_batch(self):
        def reply(**kwargs):
            return SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0]) for _ in kwargs["contents"]])
        with patch("app.rag.embedding.client.models.embed_content", side_effect=reply) as api:
            self.assertEqual(5, len(embedding.embed_texts(list("abcde"), batch_size=2, max_retries=1)))
        self.assertEqual(3, api.call_count)

    def test_embedding_cache_sends_only_distinct_misses_and_rejects_bad_batches(self):
        calls = []

        def embedder(texts):
            calls.append(list(texts))
            return [vector(t) for t in texts]

        with tempfile.TemporaryDirectory() as folder:
            first = cached_document_embeddings(["a", "b", "a"], "m", Path(folder), embedder)
            self.assertEqual([["a", "b"]], calls)
            self.assertEqual(first[0], first[2])
            cached_document_embeddings(["a", "b", "c"], "m", Path(folder), embedder)
            self.assertEqual(["c"], calls[-1])
            with self.assertRaises(ValueError):
                cached_document_embeddings(["z"], "m", Path(folder), lambda texts: [[0.0]])
            cached_document_embeddings(["z"], "m", Path(folder), embedder)
            self.assertEqual(["z"], calls[-1])  # the rejected batch left nothing in the cache

    def test_retrieval_orders_a_pages_chunks_by_seq_and_leaves_legacy_chunks_alone(self):
        group = {"documents": ["third", "first", "second"], "metadatas": [{"seq": "3"}, {"seq": "1"}, {"seq": "2"}]}
        _order_by_seq(group)
        self.assertEqual(["first", "second", "third"], group["documents"])
        legacy = {"documents": ["x", "y", "z"], "metadatas": [{}, None, {"source_type": "text"}]}
        _order_by_seq(legacy)
        self.assertEqual(["x", "y", "z"], legacy["documents"])

    def test_verifier_flags_a_table_chunk_without_its_header(self):
        meta = {"table_id": "D-t1", "has_header": "true", "source_file": "f.pdf"}
        good = {"ids": ["a", "b"], "metadatas": [meta, meta],
                "documents": ["H1 | H2\nx | 1", "H1 | H2\ny | 2"]}
        self.assertEqual([], table_header_problems(good))
        bad = {"ids": ["a", "b"], "metadatas": [meta, meta], "documents": ["H1 | H2\nx | 1", "y | 2"]}
        self.assertTrue(table_header_problems(bad))


if __name__ == "__main__":
    unittest.main()
