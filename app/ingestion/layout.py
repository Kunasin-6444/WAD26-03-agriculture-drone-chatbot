"""Layout-aware reading of a PDF's native text layer.

Turns pages into ordered paragraphs with their section path, plus raw table parts, and
decides cheaply (no API call) which pages really need a vision pass. Nothing here
invents content: text is only re-joined, whitespace-normalised and repaired by
``repair_sara_am``; table cells are kept verbatim.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import pymupdf

from app.ingestion.thai_text import repair_sara_am

_THAI = re.compile(r"[฀-๿]")
_INVISIBLE = re.compile(r"[​-‍﻿­]")
_BULLET = re.compile(r"^(?:[●•○◦▪■□▶►✓✔\-–—*]\s|\d{1,3}[.)]\s|\(\d{1,3}\)\s)")
_NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)[.)]?\s+\S")
CAPTION = re.compile(r"^(?:ตารางที่|ตาราง|table)\s*\d+", re.IGNORECASE)

MAX_HEADING_CHARS = 110
BOLD_SHARE = 0.6
SUBSTANTIAL_IMAGE_AREA = 0.06   # share of the page a picture must cover to matter
SUBSTANTIAL_IMAGE_WIDTH = 0.35
DIAGRAM_DRAWINGS = 25           # vector shapes outside tables that make a diagram
SPARSE_TEXT_CHARS = 80
PARAGRAPH_WRAP_SLACK = 4.0      # a line ending within this many font sizes of the right edge was wrapped
CELL_WRAP_SLACK = 1.6
WIDE_TABLE_COLUMNS = 8
MIN_TABLE_FILL = 0.45           # share of non-empty cells; below this it is a chart/diagram, not a table


# --------------------------------------------------
# Text helpers
# --------------------------------------------------

def join_lines(left: str, right: str) -> str:
    """Re-join two wrapped lines. Thai has no spaces between words, so a wrap between
    two Thai characters needs none; anywhere else the wrap stands for a space."""
    if not left:
        return right
    if not right:
        return left
    if _THAI.match(left[-1]) and _THAI.match(right[0]):
        return left + right
    return left + " " + right


def reflow(lines: list[str]) -> str:
    text = ""
    for line in lines:
        text = join_lines(text, line.strip())
    return normalize_text(text)


def paragraph_text(lines: list["Line"], right_edge: float) -> str:
    """Join a paragraph's lines. A line that stops short of the right edge ended on purpose, so the
    next line is separated by a space even between two Thai characters."""
    text = ""
    for previous, line in zip([None, *lines[:-1]], lines):
        if previous is None:
            text = line.text
        elif right_edge - previous.x1 <= PARAGRAPH_WRAP_SLACK * previous.size:
            text = join_lines(text, line.text)
        else:
            text = f"{text} {line.text}"
    return normalize_text(text)


def normalize_text(text: str) -> str:
    text = _INVISIBLE.sub("", text.replace("\xa0", " "))
    return repair_sara_am(re.sub(r"[ \t]+", " ", text).strip())


def clean_cell(value) -> str:
    if value is None:
        return ""
    return reflow([part for part in str(value).splitlines() if part.strip()]).replace("|", "∣")


# --------------------------------------------------
# Data model
# --------------------------------------------------

@dataclass(frozen=True)
class Line:
    page: int
    text: str
    size: float
    bold: bool
    x0: float
    y0: float
    y1: float
    x1: float = 0.0


@dataclass
class Paragraph:
    page: int
    text: str
    section: tuple[str, ...]
    y0: float
    y1: float
    kind: str = "paragraph"          # paragraph | heading | caption


@dataclass
class RawTable:
    page: int
    rows: list[tuple[str, ...]]
    y0: float
    y1: float
    page_height: float
    text_above: bool                 # real text sits above the table on its page
    caption: str | None = None


@dataclass
class PageLayout:
    page: int
    lines: list[Line]
    tables: list[RawTable]
    text_chars: int
    blank: bool
    vision: bool
    vision_reason: str
    page_height: float
    table_rects: list[tuple[float, float, float, float]] = field(default_factory=list)


# --------------------------------------------------
# One page
# --------------------------------------------------

def _inside(point: pymupdf.Point, rects: list[pymupdf.Rect]) -> bool:
    return any(point in rect for rect in rects)


def _cell_text(page: pymupdf.Page, bbox) -> str:
    """One cell's text in the PDF's own character order. A line that runs to the cell's edge was
    wrapped (Thai may continue mid-word); a shorter line was ended on purpose (keep a space)."""
    rect = pymupdf.Rect(bbox)
    data = page.get_text("dict", clip=rect, flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)
    text, edge, size = "", 0.0, 10.0
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            piece = "".join(span["text"] for span in line["spans"]).strip()
            if not piece:
                continue
            if not text:
                text = piece
            elif rect.x1 - edge <= CELL_WRAP_SLACK * size:
                text = join_lines(text, piece)
            else:
                text = f"{text} {piece}"
            edge, size = line["bbox"][2], max(span["size"] for span in line["spans"])
    return clean_cell(text)


def _read_cells(page: pymupdf.Page, table) -> list[tuple[str, ...]]:
    """Cell text from the page's own character order, not ``Table.extract()``, which re-sorts
    characters by position and scrambles Thai vowels and tone marks
    ("อุปกรณ์ในชุด" -> "อปกรณ์ในุชด")."""
    try:
        grid = [[None if bbox is None else _cell_text(page, bbox) for bbox in row.cells] for row in table.rows]
    except Exception:
        try:
            grid = [[clean_cell(cell) for cell in row] for row in table.extract() or []]
        except Exception:
            return []
    width = max((len(row) for row in grid), default=0)
    rows = [tuple(cell or "" for cell in row) + ("",) * (width - len(row)) for row in grid]
    return [row for row in rows if any(row)]


def _table_parts(page: pymupdf.Page) -> tuple[list[RawTable], list[pymupdf.Rect]]:
    parts: list[RawTable] = []
    rects: list[pymupdf.Rect] = []
    try:
        found = page.find_tables().tables
    except Exception:  # find_tables can fail on exotic pages; text extraction still works
        return parts, rects
    height = page.rect.height
    for table in found:
        rows = _read_cells(page, table)
        if not rows:
            continue
        cells = len(rows) * len(rows[0])
        filled = sum(bool(c) for r in rows for c in r)
        # Chart labels and boxed text are small and sparse: keep their words as ordinary text lines.
        # A wide grid is a real table even when a page break leaves it with one or two sparse rows.
        wide = len(rows[0]) >= WIDE_TABLE_COLUMNS
        if not wide and (len(rows) < 2 or len(rows[0]) < 2 or filled < MIN_TABLE_FILL * cells):
            continue
        rect = pymupdf.Rect(table.bbox)
        rects.append(rect)
        parts.append(RawTable(page.number + 1, rows, rect.y0, rect.y1, height, False))
    return parts, rects


def _lines_outside(page: pymupdf.Page, rects: list[pymupdf.Rect]) -> list[Line]:
    data = page.get_text("rawdict", flags=pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES, sort=True)
    lines: list[Line] = []
    for block in data.get("blocks", []):
        for raw in block.get("lines", []):
            chars: list[str] = []
            sizes: Counter = Counter()
            bold = total = 0
            for span in raw.get("spans", []):
                is_bold = bool(span.get("flags", 0) & 16) or "bold" in span.get("font", "").lower()
                for char in span.get("chars", []):
                    x0, y0, x1, y1 = char["bbox"]
                    if _inside(pymupdf.Point((x0 + x1) / 2, (y0 + y1) / 2), rects):
                        chars.append(" ")  # a gap keeps words either side of a table cell apart
                        continue
                    chars.append(char["c"])
                    if char["c"].strip():
                        sizes[round(span.get("size", 0.0) * 2) / 2] += 1
                        total += 1
                        bold += is_bold
            text = normalize_text("".join(chars))
            if not text or not sizes:
                continue
            x0, y0, x1, y1 = raw["bbox"]
            lines.append(Line(page.number + 1, text, max(sizes, key=sizes.get),
                              bold >= BOLD_SHARE * max(total, 1), x0, y0, y1, x1))
    return lines


def needs_vision(page: pymupdf.Page, rects: list[pymupdf.Rect], text_chars: int) -> tuple[bool, str]:
    """Vision only when the picture can hold knowledge the text layer lacks.

    Thumbnails inside table cells and table borders (hundreds of vector shapes) do not
    count; a large figure, a diagram, a scan or a damaged text layer does."""
    area = page.rect.width * page.rect.height
    figures = 0
    for info in page.get_image_info():
        rect = pymupdf.Rect(info["bbox"]) & page.rect
        if rect.is_empty or _inside(pymupdf.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2), rects):
            continue
        if rect.get_area() / area >= SUBSTANTIAL_IMAGE_AREA or rect.width / page.rect.width >= SUBSTANTIAL_IMAGE_WIDTH:
            figures += 1
    if figures:
        return True, f"figure_x{figures}"
    try:
        # Word/Docs exports paint table borders just outside the cell box, often
        # twice. Those paint operations must not turn native tables into diagrams.
        borders = [rect + (-2, -2, 2, 2) for rect in rects]
        outside = [d for d in page.get_drawings() if not _inside(
            pymupdf.Point((d["rect"].x0 + d["rect"].x1) / 2, (d["rect"].y0 + d["rect"].y1) / 2), borders)]
        shapes = len({(d.get("type"), repr(d.get("items"))) for d in outside})
    except Exception:
        shapes = 0
    if shapes > DIAGRAM_DRAWINGS:
        return True, f"diagram_shapes_{shapes}"
    raw = page.get_text()
    if "�" in raw:
        return True, "corrupted_text_layer"
    if text_chars < SPARSE_TEXT_CHARS and (page.get_images() or shapes):
        return True, "sparse_text_with_graphics"
    return False, "text_layer_sufficient"


def read_page(page: pymupdf.Page) -> PageLayout:
    tables, rects = _table_parts(page)
    lines = _lines_outside(page, rects)
    text_chars = sum(len(line.text) for line in lines) + sum(len(c) for t in tables for r in t.rows for c in r)
    for table in tables:
        table.text_above = sum(len(line.text) for line in lines if line.y1 <= table.y0 + 2) >= 6
        above = [line for line in lines if line.y1 <= table.y0 + 2 and table.y0 - line.y1 <= 60 and CAPTION.match(line.text)]
        if above:
            table.caption = max(above, key=lambda line: line.y1).text
    vision, reason = needs_vision(page, rects, text_chars)
    blank = text_chars == 0 and not tables and not page.get_images() and not page.get_drawings()
    if blank:
        vision, reason = False, "blank_page"
    return PageLayout(page.number + 1, lines, tables, text_chars, blank, vision, reason, page.rect.height,
                      [tuple(rect) for rect in rects])


# --------------------------------------------------
# Whole document: headings and paragraphs
# --------------------------------------------------

def body_font_size(layouts: list[PageLayout]) -> float:
    weight: Counter = Counter()
    for layout in layouts:
        for line in layout.lines:
            weight[line.size] += len(line.text)
    return max(weight, key=weight.get) if weight else 10.0


def heading_level(line: Line, body: float) -> int | None:
    """1..4 when the line is a heading, else None."""
    text = line.text
    if len(text) > MAX_HEADING_CHARS or CAPTION.match(text):
        return None
    numbered = _NUMBERED.match(text)
    big = line.size >= body * 1.18
    quiet_bold = line.bold and len(text) <= 90 and not text.endswith((",", ";", "。")) and line.size >= body * 0.98
    if not (big or (quiet_bold and (numbered or not _BULLET.match(text)))):
        return None
    if numbered:
        return min(numbered.group(1).count(".") + 1, 4)
    if line.size >= body * 1.45:
        return 1
    return 2 if line.size >= body * 1.2 else 3


def build_paragraphs(layouts: list[PageLayout]) -> list[Paragraph]:
    """Paragraphs and headings in reading order; each carries its section path."""
    body = body_font_size(layouts)
    stack: list[tuple[int, str, bool]] = []     # (level, title, unnumbered-bold)
    paragraphs: list[Paragraph] = []
    previous_heading_size = 0.0

    def section() -> tuple[str, ...]:
        return tuple(title for _, title, _ in stack)

    for layout in layouts:
        current: list[Line] = []

        right = max((line.x1 for line in layout.lines), default=0.0)

        def flush():
            if current:
                text = paragraph_text(current, right)
                if text:
                    kind = "caption" if CAPTION.match(text) else "paragraph"
                    paragraphs.append(Paragraph(layout.page, text, section(), current[0].y0, current[-1].y1, kind))
                current.clear()

        for line in layout.lines:
            level = heading_level(line, body)
            if level is not None:
                last = paragraphs[-1] if paragraphs else None
                if (not current and last and last.kind == "heading" and last.page == layout.page and stack
                        and line.y0 - last.y1 <= 0.7 * max(last.y1 - last.y0, 1.0) and previous_heading_size == line.size):
                    # "3.1.2." and its title printed on two lines, or a title that wraps: one heading
                    merged = join_lines(last.text, line.text)
                    stack[-1] = (stack[-1][0], merged, stack[-1][2])
                    paragraphs[-1] = Paragraph(layout.page, merged, section(), last.y0, line.y1, "heading")
                    continue
                flush()
                quiet = not _NUMBERED.match(line.text) and line.size < body * 1.18
                if quiet and stack:
                    # an unnumbered bold heading nests under the heading above it, unless that one is
                    # itself such a heading (then they are siblings: "Before flight" / "After use")
                    level = stack[-1][0] if stack[-1][2] else min(stack[-1][0] + 1, 5)
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, line.text, quiet))
                previous_heading_size = line.size
                paragraphs.append(Paragraph(layout.page, line.text, section(), line.y0, line.y1, "heading"))
                continue
            if current:
                previous = current[-1]
                height = max(previous.y1 - previous.y0, 1.0)
                if (line.y0 - previous.y1 > 0.7 * height or _BULLET.match(line.text)
                        or abs(line.size - previous.size) > 1.0):
                    flush()
            current.append(line)
        flush()
    return paragraphs
