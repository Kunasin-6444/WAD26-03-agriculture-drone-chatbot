"""Turn extracted structure into retrieval chunks.

Rules (each one fixes a measured weakness of fixed 800-character windows):
  * a chunk never starts or ends in the middle of a table row, word-wrapped Thai line or
    sentence, and table chunks always begin with the table header;
  * every chunk keeps the single page its text was printed on, so citations stay exact;
  * the section path and document title are added to the text that is *embedded* but not
    to the text that is *stored*, so ranking gets context while evidence and the
    verbatim-quote check still see only what the PDF says.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from app.ingestion.dedupe import skeleton
from app.ingestion.layout import Paragraph
from app.ingestion.tables import LogicalTable, TablePart, table_chunks
from app.ingestion.vision_extractor import VisionPageResult
from app.rag.chunking import Chunk

INGESTION_VERSION = "text_v4"
TEXT_CHUNK_CHARS = 800
SMALL_CHUNK_CHARS = 250
NOISE_CHARS = 3             # a lone slide/page number is not knowledge
CONTEXT_CHARS = 240
_LEADING_ID = re.compile(r"^(?:uav|ua)\s*\d+[\s_.-]*", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass
class Piece:
    page: int
    y0: float
    content: str
    source_type: str
    source: str
    section: tuple[str, ...] = ()
    caption: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


def document_title(source_file: str) -> str:
    stem = source_file.rsplit(".", 1)[0]
    return _LEADING_ID.sub("", stem).strip() or stem


def split_long(text: str, limit: int) -> list[str]:
    """Split on sentence ends, then on spaces (Thai phrases), never inside a word if avoidable."""
    if len(text) <= limit:
        return [text]
    units = [u for s in _SENTENCE_END.split(text) for u in ([s] if len(s) <= limit else s.split(" ")) if u.strip()]
    pieces, current = [], ""
    for unit in units:
        while len(unit) > limit:  # a single unbroken run longer than the limit
            if current:
                pieces.append(current)
                current = ""
            pieces.append(unit[:limit])
            unit = unit[limit:]
        if current and len(current) + 1 + len(unit) > limit:
            pieces.append(current)
            current = ""
        current = f"{current} {unit}" if current else unit
    if current:
        pieces.append(current)
    return pieces


# --------------------------------------------------
# Pieces from each source
# --------------------------------------------------

def text_pieces(paragraphs: list[Paragraph], limit: int = TEXT_CHUNK_CHARS) -> list[Piece]:
    """Pack paragraphs of one section and page together; merge tiny neighbours on a page."""
    groups: list[tuple[int, tuple[str, ...], float, list[str]]] = []
    for paragraph in paragraphs:
        if paragraph.kind != "heading" and len(skeleton(paragraph.text)) <= NOISE_CHARS:
            continue
        key = (paragraph.page, paragraph.section)
        if not groups or (groups[-1][0], groups[-1][1]) != key:
            groups.append((paragraph.page, paragraph.section, paragraph.y0, []))
        groups[-1][3].extend(split_long(paragraph.text, limit))
    packed: list[Piece] = []
    for page, section, y0, parts in groups:
        current = ""
        for part in parts:
            if current and len(current) + 1 + len(part) > limit:
                packed.append(Piece(page, y0, current, "text", "pdf_text", section))
                current = ""
            current = f"{current}\n{part}" if current else part
        if current:
            packed.append(Piece(page, y0, current, "text", "pdf_text", section))
    merged: list[Piece] = []
    for piece in packed:
        last = merged[-1] if merged else None
        if (last and last.page == piece.page and len(last.content) + 1 + len(piece.content) <= limit
                and min(len(last.content), len(piece.content)) < SMALL_CHUNK_CHARS):
            last.content = f"{last.content}\n{piece.content}"
        else:
            merged.append(piece)
    return merged


def table_pieces(tables: list[LogicalTable]) -> list[Piece]:
    pieces: list[Piece] = []
    for table in tables:
        for page, note in table.notes:
            pieces.append(Piece(page, table.y0 if table.y0 is not None else 0.0, note, "text", "pdf_text",
                                table.section, table.caption, {"table_note": table.id}))
        for chunk in table_chunks(table):
            extra = {"table_id": table.id, "row_start": str(chunk.row_start), "row_end": str(chunk.row_end),
                     "header_inherited": "true" if chunk.header_inherited else "false",
                     "has_header": "true" if table.header else "false"}
            if chunk.page_end > chunk.page:
                extra["page_end"] = str(chunk.page_end)  # a row's text ran onto the next page(s)
            if chunk.page_from < chunk.page:
                extra["page_from"] = str(chunk.page_from)  # the header was printed on an earlier page
            if table.group_column:
                extra["group_column"] = "true"
            source = "vision" if table.origin == "vision" else "pdf_native_table"
            pieces.append(Piece(chunk.page, table.y0 if table.y0 is not None else 0.0, chunk.content, "table",
                                source, table.section, table.caption, extra))
    return pieces


_VISION_TYPES = {"table": "table", "diagram": "diagram", "chart": "chart"}


def vision_pieces(page: int, result: VisionPageResult, section: tuple[str, ...]) -> tuple[list[Piece], list[TablePart]]:
    """Pieces for the page's visual elements, plus the structured tables they contain.

    Tables the model returned cell by cell are handed back as ``TablePart``-ready rows so they
    are chunked like native tables; every other element keeps its described text."""
    pieces: list[Piece] = []
    parts: list[TablePart] = []
    for element in result.elements:
        source_type = _VISION_TYPES.get(element.type or "", "image")
        status = {"vision_status": element.status or "unknown"}
        rows = [tuple((cell or "").replace("|", "∣").strip() for cell in row.cells) for row in element.rows or []]
        rows = [row for row in rows if any(row)]
        if element.type == "table" and rows:
            width = max(max(len(row) for row in rows), len(element.columns or []))
            parts.append(TablePart(page, [row + ("",) * (width - len(row)) for row in rows], "vision",
                                   section=section, caption=element.description,
                                   header=tuple((c or "").strip() for c in element.columns or [])))
            prose = [p for p in (f"ประเภท: {element.description}" if element.description else "",
                                 f"คำอธิบายภาพ:\n{element.visual_description}" if element.visual_description else "") if p]
            source_type = "image"
        else:
            prose = []
            if element.description:
                prose.append(f"ประเภท: {element.description}")
            if element.extracted_text:
                prose.append("ข้อมูลจากภาพ:\n" + element.extracted_text)
            if element.visual_description:
                prose.append("คำอธิบายภาพ:\n" + element.visual_description)
        text = "\n\n".join(p for p in prose if p.strip())
        for part in split_long(text, TEXT_CHUNK_CHARS * 2) if text.strip() else []:
            pieces.append(Piece(page, 1e6, part, source_type, "vision", section, element.description, status))
    if result.summary and result.has_meaningful_visual_content:
        pieces.append(Piece(page, 1e6 + 1, result.summary, "mixed", "vision_summary", section, "Visual summary"))
    return pieces, parts


# --------------------------------------------------
# Pieces -> chunks
# --------------------------------------------------

def embedding_context(title: str, piece: Piece) -> str:
    trail = [title, *piece.section[-2:]]
    if piece.caption and piece.caption not in trail:
        trail.append(piece.caption)
    return " › ".join(part for part in trail if part)[:CONTEXT_CHARS]


def assemble(pieces: list[Piece], document_id: str, source_file: str, source_sha256: str) -> list[Chunk]:
    title = document_title(source_file)
    chunks: list[Chunk] = []
    counters: dict[tuple[int, str], int] = {}
    for seq, piece in enumerate(sorted(pieces, key=lambda p: (p.page, p.y0)), start=1):
        content = piece.content.strip()
        if not content:
            continue
        key = (piece.page, piece.source_type)
        counters[key] = counters.get(key, 0) + 1
        digest = hashlib.sha1(content.encode("utf-8")).hexdigest()[:6]
        metadata = {
            "document_id": document_id, "source_file": source_file, "page_number": str(piece.page),
            "source_type": piece.source_type, "source": piece.source, "seq": str(seq),
            "ingestion_version": INGESTION_VERSION, "source_sha256": source_sha256,
            "extraction_complete": "true", **piece.extra,
        }
        if piece.section:
            metadata["section"] = " › ".join(piece.section)[:300]
        chunks.append(Chunk(
            id=f"{document_id}-p{piece.page}-{piece.source_type}-{counters[key]}-{digest}",
            content=content, document_id=document_id, source_file=source_file, page_number=piece.page,
            source_type=piece.source_type, metadata=metadata,
            embed_text=f"{embedding_context(title, piece)}\n{content}"))
    return chunks
