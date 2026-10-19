"""Logical tables: stitch page parts together, then cut them into row-aligned chunks.

A table printed across several pages is one table. Its header row appears once, yet every
chunk must be readable on its own, because retrieval, the answer model and the
table-grounding checks all treat a chunk's first pipe row as the header. So each chunk
repeats the header, never splits a row, and keeps the page its rows were printed on.

Rows that merge across all columns ("Group 1: Neonicotinoids") label the rows below them.
They become a trailing context column instead of a dangling line, so a row quoted on its
own still says which group it belongs to. Cell values are never changed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.ingestion.layout import join_lines

GROUP_COLUMN = "หัวข้อกลุ่ม"
GROUP_TITLE_CHARS = 100
TABLE_CHUNK_CHARS = 1200
TOP_OF_PAGE = 0.35       # a continuation starts in the upper part of its page ...
BOTTOM_OF_PAGE = 0.60    # ... after a table that ran down the lower part of the previous page
_NUMBER = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")


@dataclass
class TableRow:
    page: int
    cells: tuple[str, ...]
    end_page: int = 0                    # last page holding text of this row (0 = same page)


@dataclass
class TablePart:
    """One page's share of a table, as read from the PDF or from a vision result."""
    page: int
    rows: list[tuple[str, ...]]
    origin: str                          # pdf_native_table | vision
    y0: float | None = None
    y1: float | None = None
    page_height: float | None = None
    text_above: bool | None = None
    caption: str | None = None
    section: tuple[str, ...] = ()
    header: tuple[str, ...] | None = None   # explicit (vision); () = "this page prints no header"


@dataclass
class LogicalTable:
    id: str
    origin: str
    header: tuple[str, ...] | None
    rows: list[TableRow] = field(default_factory=list)
    caption: str | None = None
    section: tuple[str, ...] = ()
    pages: list[int] = field(default_factory=list)
    inherited_pages: set[int] = field(default_factory=set)
    y0: float | None = None
    group_column: bool = False
    columns: int = 0
    header_page: int = 0
    notes: list[tuple[int, str]] = field(default_factory=list)   # (page, full text) of group labels


@dataclass
class TableChunk:
    content: str
    page: int
    row_start: int
    row_end: int
    header_inherited: bool
    page_from: int = 0
    page_end: int = 0


def group_title(label: str) -> str:
    """Short context for a group label; a long merged cell is "title (qualifier) description"."""
    if len(label) <= GROUP_TITLE_CHARS:
        return label
    close = label.find(")", 0, GROUP_TITLE_CHARS)
    if close > 0:
        return label[:close + 1]
    return label[:label.rfind(" ", 0, GROUP_TITLE_CHARS)].strip() or label[:GROUP_TITLE_CHARS]


def _key(cells) -> str:
    return re.sub(r"\s+", "", "|".join(cells)).casefold()


def is_group_row(cells: tuple[str, ...]) -> bool:
    """A label merged across the table: the only filled cell is the first, and it is text."""
    return (len(cells) >= 3 and sum(bool(cell.strip()) for cell in cells) == 1 and bool(cells[0].strip())
            and not _NUMBER.fullmatch(cells[0].strip()))


def is_row_fragment(cells: tuple[str, ...]) -> bool:
    """A row that only completes cells of the row above: sparse, and empty in the first column
    (a group label would sit there instead)."""
    filled = sum(bool(cell.strip()) for cell in cells)
    return len(cells) >= 4 and 0 < filled <= max(1, len(cells) // 3) and not cells[0].strip()


def looks_like_header(cells: tuple[str, ...]) -> bool:
    filled = [cell for cell in cells if cell.strip()]
    if len(filled) * 2 < len(cells):
        return False
    return sum(bool(_NUMBER.fullmatch(cell.strip())) for cell in filled) * 2 < len(filled)


def _continues(previous: TablePart, part: TablePart) -> bool:
    if part.page != previous.page + 1 or len(part.rows[0]) != len(previous.rows[0]):
        return False
    if part.header is not None:  # vision states outright whether this page prints a header
        return not part.header
    if None in (previous.y1, previous.page_height, part.y0, part.page_height):
        return False
    return (previous.y1 / previous.page_height >= BOTTOM_OF_PAGE
            and part.y0 / part.page_height <= TOP_OF_PAGE and not part.text_above)


def stitch(parts: list[TablePart], id_prefix: str) -> list[LogicalTable]:
    """Merge consecutive parts of ONE origin into logical tables, in reading order.

    Table ids are ``id_prefix`` + a running number (e.g. ``UAV13-t1``)."""
    tables: list[LogicalTable] = []
    last_part: TablePart | None = None
    group = ""
    for part in sorted(parts, key=lambda p: (p.page, p.y0 if p.y0 is not None else 0.0)):
        rows = [tuple(row) for row in part.rows if any(cell.strip() for cell in row)]
        if not rows:
            continue
        part = TablePart(**{**part.__dict__, "rows": rows})
        current = tables[-1] if tables else None
        if current is not None and last_part is not None and current.origin == part.origin and _continues(last_part, part):
            if current.header and _key(rows[0]) == _key(current.header[:len(rows[0])]):
                rows = rows[1:]  # the header is printed again; do not store it as data
            else:
                current.inherited_pages.add(part.page)
        else:
            caption = part.caption
            while rows and is_group_row(rows[0]) and part.header is None:
                caption = caption or next(cell for cell in rows[0] if cell.strip())
                rows = rows[1:]  # a merged title row on top of the table is a caption, not data
            if part.header is not None:
                header = tuple(part.header) or None
            elif rows and looks_like_header(rows[0]):
                header, rows = rows[0], rows[1:]
            else:
                header = None
            current = LogicalTable(f"{id_prefix}{len(tables) + 1}", part.origin, header, caption=caption,
                                   section=part.section, y0=part.y0, columns=len(part.rows[0]),
                                   header_page=part.page)
            tables.append(current)
            group = ""
        if current.pages[-1:] != [part.page]:
            current.pages.append(part.page)
        pending = None
        for row in rows:
            if (current.rows or current.header) and is_row_fragment(row):
                # A cell's text that the PDF printed as a separate sparse row (across a page break, or
                # a value displaced by a tall picture): it belongs to the row above, or to the header
                # when the header itself was split across the break.
                if current.rows:
                    last = current.rows[-1]
                    current.rows[-1] = TableRow(last.page, tuple(
                        join_lines(old, new) if old and new else (old or new)
                        for old, new in zip(last.cells, row + ("",))), max(last.end_page, part.page))
                else:
                    current.header = tuple(join_lines(old, new) if old and new else (old or new)
                                           for old, new in zip(current.header, row))
                continue
            if is_group_row(row):
                label = next(cell for cell in row if cell.strip())
                group = group_title(label)
                current.group_column = True
                if len(label) > len(group):
                    current.notes.append((part.page, label))  # the description is kept once, as text
                else:
                    pending = (part.page, label)
                continue
            current.rows.append(TableRow(part.page, row + (group,)))  # group column is stripped below if unused
            pending = None
        if pending:  # a label printed at the foot of a page with its rows on the next one
            current.notes.append(pending)
            pending = None
        last_part = part
    for table in tables:
        width = table.columns
        header = ((table.header or ()) + ("",) * width)[:width]
        keep = [i for i in range(width) if header[i].strip() or any(row.cells[i].strip() for row in table.rows)]
        table.rows = [TableRow(row.page, tuple(row.cells[i] for i in keep) + (row.cells[-1],), row.end_page)
                      for row in table.rows]
        table.header = tuple(header[i] for i in keep) if table.header else None
        table.columns = len(keep)
        if table.group_column:
            if table.header:
                table.header = table.header + (GROUP_COLUMN,)
        else:
            table.rows = [TableRow(row.page, row.cells[:-1], row.end_page) for row in table.rows]
    return [table for table in tables if table.rows]


def render_row(cells: tuple[str, ...]) -> str:
    return " | ".join(cell.replace("\n", " ") for cell in cells)


def table_chunks(table: LogicalTable, max_chars: int = TABLE_CHUNK_CHARS) -> list[TableChunk]:
    """Row-aligned chunks. Each starts with the header and holds rows of a single page."""
    header_line = render_row(table.header) if table.header else ""
    by_page: dict[int, list[tuple[int, str, int]]] = {}
    for number, row in enumerate(table.rows, start=1):
        by_page.setdefault(row.page, []).append((number, render_row(row.cells), max(row.end_page, row.page)))
    chunks: list[TableChunk] = []
    for page, rows in by_page.items():
        inherited = page in table.inherited_pages and bool(header_line)
        budget = max(max_chars - len(header_line) - 1, 200)
        whole = sum(len(line) + 1 for _, line, _ in rows)
        batches: list[list[tuple[int, str, int]]] = []
        if whole <= budget * 1.25:
            batches = [rows]
        else:
            batch: list[tuple[int, str, int]] = []
            size = 0
            for item in rows:
                if batch and size + len(item[1]) + 1 > budget:
                    batches.append(batch)
                    batch, size = [], 0
                batch.append(item)
                size += len(item[1]) + 1
            batches.append(batch)
        for batch in batches:
            lines = ([header_line] if header_line else []) + [line for _, line, _ in batch]
            first = not chunks and table.header_page
            chunks.append(TableChunk("\n".join(lines), page, batch[0][0], batch[-1][0], inherited,
                                     min(page, table.header_page) if first else page,
                                     max(end for *_, end in batch)))
    return chunks
