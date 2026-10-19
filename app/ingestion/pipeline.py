"""Ingestion pipeline: plan -> read -> vision -> structure -> chunk -> embed -> publish.

Designed around three costs: API quota (vision only where it adds knowledge, batched
embeddings, content-addressed caches, nothing re-done for an unchanged PDF), wall time
(vision pages run concurrently), and trust (the index is only touched after every vector
exists, and a page whose vision pass failed never replaces a previously good page).
Everything before the vision/embedding calls is offline, so ``plan_document`` can show
exactly what a run would spend before it spends anything.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import pymupdf

from app.ingestion.dedupe import assess_native
from app.ingestion.layout import PageLayout, Paragraph, build_paragraphs, read_page
from app.ingestion.publisher import publish
from app.ingestion.structured_chunker import (
    INGESTION_VERSION, Piece, assemble, table_pieces, text_pieces, vision_pieces)
from app.ingestion.tables import TablePart, render_row, stitch
from app.ingestion.thai_text import thai_layer_damaged
from app.ingestion.vision_extractor import VisionPageResult, is_generation_loop, validate_vision_result
from app.rag.embedding_cache import cached_document_embeddings
from app.rag.source_policy import canonical_document_id, is_excluded_document

ROOT = Path(__file__).resolve().parents[2]
VISION_FAILED = "[VISION_EXTRACTION_FAILED]"


@dataclass
class Options:
    pages: tuple[int, int] | None = None     # inclusive range, 1-based
    vision: str = "auto"                     # auto | always | never
    workers: int = field(default_factory=lambda: int(os.getenv("VISION_WORKERS", "3")))
    force: bool = False
    document_id: str | None = None
    report_dir: Path = ROOT / "cache" / "ingestion"


@dataclass
class Deps:
    """Everything that talks to the outside world; tests replace these."""
    vision: Callable[[Path, int, str], VisionPageResult]
    embed_batch: Callable[[list[str]], list[list[float]]]
    collection: Any
    cache_dir: Path
    embedding_model: str = ""


def default_deps() -> Deps:
    from app.ingestion.vision_extractor import analyze_pdf_page
    from app.rag import vector_store
    from app.rag.embedding import EMBEDDING_MODEL, embed_texts

    def vision(pdf: Path, page: int, sha256: str) -> VisionPageResult:
        return vision_with_plain_fallback(analyze_pdf_page, pdf, page, sha256)

    return Deps(vision, embed_texts, vector_store.collection, vector_store.CHROMA_PATH / "embedding_cache",
                EMBEDDING_MODEL)


# The model degenerates on some dense table pages when asked for every cell, yet the same pages
# read fine as plain text (UAV06 p18 under the old pipeline). Only these content failures earn a
# second call; rate limits and outages would fail the plain read too.
PLAIN_RETRY_FAILURES = ("generation loop", "did not finish normally")


def vision_with_plain_fallback(analyze: Callable[..., VisionPageResult], pdf: Path, page: int,
                               sha256: str) -> VisionPageResult:
    result = analyze(pdf, page, document_sha256=sha256, structured_tables=True, use_heuristic=False)
    summary = result.summary or ""
    if summary.startswith(VISION_FAILED) and any(reason in summary for reason in PLAIN_RETRY_FAILURES):
        print(f"    page {page}: cell-by-cell read failed, retrying as plain text", flush=True)
        result = analyze(pdf, page, document_sha256=sha256, structured_tables=False, use_heuristic=False)
    return result


# --------------------------------------------------
# Plan (offline)
# --------------------------------------------------

@dataclass
class DocumentPlan:
    pdf: Path
    document_id: str
    sha256: str
    pages: int
    status: str                      # new | partial | up_to_date | stale | legacy | excluded
    vision_pages: dict[int, str]
    blank_pages: list[int]
    native_tables: int
    estimated_chunks: int
    warnings: list[str]


def file_sha256(pdf: Path) -> str:
    digest = hashlib.sha256()
    with pdf.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def index_status(collection, source_file: str, sha256: str) -> str:
    found = collection.get(where={"source_file": source_file}, include=["metadatas"])
    metas = [m or {} for m in found["metadatas"]]
    if not metas:
        return "new"
    if any(not m.get("source_sha256") for m in metas):
        return "legacy"   # ingested by an older pipeline; replace only on explicit --force
    if any(m.get("partial_range") for m in metas):
        return "partial"  # a --pages trial run: the rest of the file is still missing
    if all(m["source_sha256"] == sha256 and m.get("ingestion_version") == INGESTION_VERSION for m in metas):
        return "up_to_date"
    return "stale"


def _page_range(options: Options, total: int) -> list[int]:
    start, end = options.pages or (1, total)
    if not 1 <= start <= end <= total:
        raise ValueError(f"Page range must be within 1..{total}")
    return list(range(start, end + 1))


def _read_all(doc: pymupdf.Document, wanted: set[int], failed: dict[str, str]) -> list[PageLayout]:
    layouts = []
    for number in range(1, len(doc) + 1):
        try:
            layouts.append(read_page(doc[number - 1]))
        except Exception as exc:
            if number in wanted:
                failed[str(number)] = type(exc).__name__
            layouts.append(PageLayout(number, [], [], 0, False, False, "unreadable", 0.0))
    return layouts


def _vision_pages(layouts: list[PageLayout], wanted: list[int], mode: str) -> dict[int, str]:
    if mode == "never":
        return {}
    by_page = {layout.page: layout for layout in layouts}
    return {page: ("forced" if mode == "always" else by_page[page].vision_reason) for page in wanted
            if not by_page[page].blank and (mode == "always" or by_page[page].vision)}


def plan_document(pdf: Path, options: Options, collection=None) -> DocumentPlan:
    """What ingesting ``pdf`` would do and spend. Offline: no vision, embedding or index write."""
    document_id = options.document_id or canonical_document_id(pdf.name)
    sha256 = file_sha256(pdf)
    if is_excluded_document(pdf.name):
        return DocumentPlan(pdf, document_id, sha256, 0, "excluded", {}, [], 0, 0,
                            ["excluded by source policy (answered from CAAT instead)"])
    status = index_status(collection, pdf.name, sha256) if collection is not None else "new"
    failed: dict[str, str] = {}
    with pymupdf.open(pdf) as doc:
        wanted = _page_range(options, len(doc))
        layouts = _read_all(doc, set(wanted), failed)
    vision = _vision_pages(layouts, wanted, options.vision)
    chunks, _, tables = _build(pdf, document_id, sha256, layouts, set(wanted), {})
    warnings = [f"page {p}: layout unreadable ({kind})" for p, kind in failed.items()]
    warnings += [f"table {t['id']} (pages {t['pages']}): no header row detected, chunks will carry no column names"
                 for t in tables if not t["has_header"]]
    if not document_id.upper().startswith(("UAV", "UA")):
        warnings.append(f"document id {document_id!r} does not follow the UAVnn convention (use --doc-id to change)")
    return DocumentPlan(
        pdf, document_id, sha256, len(layouts), status, vision, [l.page for l in layouts if l.blank and l.page in wanted],
        sum(len(l.tables) for l in layouts if l.page in wanted), len(chunks), warnings)


# --------------------------------------------------
# Build chunks (offline given the vision results)
# --------------------------------------------------

def _section_at(paragraphs: list[Paragraph], page: int, y: float) -> tuple[str, ...]:
    section: tuple[str, ...] = ()
    for paragraph in paragraphs:
        if (paragraph.page, paragraph.y1) <= (page, y + 2):
            section = paragraph.section
        else:
            break
    return section


def _element_text(element) -> str:
    cells = [cell for row in element.rows or [] for cell in row.cells]
    return " ".join([element.extracted_text or "", *(element.columns or []), *cells])


def drop_vision_tables_native_covers(result: VisionPageResult, page: int, native_tables: str) -> VisionPageResult:
    """A table the PDF text layer already holds comes from the text layer, not from vision.

    The text layer carries the author's exact words; vision re-types them and can slip on the
    words that matter (UAV06 p18: "ก่อนวัชพืชงอก" read as "ก่อนพืชงอก" in all 22 rows, a
    herbicide name misspelled) while every number still matches. Vision keeps the photos,
    figures and any table the text layer lacks or garbles (numbers missing -> not covered)."""
    if not native_tables.strip() or thai_layer_damaged(native_tables):
        return result  # a damaged text layer (UAV06 p15: "น้ า", "ต่ าลง") is no better than vision
    # assess_native(candidate, page, reference) "covered" == the candidate adds nothing over the reference;
    # a table element with no transcribed text ("noise") keeps its description.
    kept = [element for element in result.elements
            if not (element.type == "table"
                    and assess_native(_element_text(element), page, native_tables).reason.startswith("covered"))]
    if len(kept) == len(result.elements):
        return result
    return result.model_copy(update={"elements": kept})


def _build(pdf: Path, document_id: str, sha256: str, layouts: list[PageLayout], wanted: set[int],
           vision: dict[int, VisionPageResult]):
    """-> (chunks, pages that produced content, table summaries)."""
    paragraphs = build_paragraphs(layouts)
    degraded = {page for page, result in vision.items() if (result.summary or "").startswith(VISION_FAILED)}
    usable = {page for page in wanted if page not in degraded}

    native_table_text = {layout.page: "\n".join(render_row(row) for table in layout.tables for row in table.rows)
                         for layout in layouts if layout.tables}
    vision_text: dict[int, str] = {}
    vision_items: dict[int, tuple[list[Piece], list[TablePart]]] = {}
    for page in sorted(usable & set(vision)):
        result = drop_vision_tables_native_covers(vision[page], page, native_table_text.get(page, ""))
        pieces, parts = vision_pieces(page, result, _section_at(paragraphs, page, 1e6))
        vision_items[page] = (pieces, parts)
        vision_text[page] = " ".join([p.content for p in pieces] + [render_row(r) for part in parts for r in part.rows])

    pieces: list[Piece] = []
    page_paragraphs: dict[int, list[Paragraph]] = {}
    for paragraph in paragraphs:
        if paragraph.page in usable:
            page_paragraphs.setdefault(paragraph.page, []).append(paragraph)
    for page, items in page_paragraphs.items():
        if page in vision_text and assess_native(" ".join(p.text for p in items), page, vision_text[page]).drop:
            continue  # the vision pass already transcribed everything this text layer says
        pieces.extend(text_pieces(items))

    native_parts: list[TablePart] = []
    for layout in layouts:
        if layout.page in degraded:
            continue
        for table in layout.tables:
            part = TablePart(layout.page, list(table.rows), "pdf_native_table", table.y0, table.y1,
                             table.page_height, table.text_above, table.caption,
                             _section_at(paragraphs, layout.page, table.y0))
            if layout.page in vision_text and assess_native(
                    "\n".join(render_row(r) for r in part.rows), layout.page, vision_text[layout.page]).drop:
                continue
            native_parts.append(part)
    vision_parts = [part for _, parts in vision_items.values() for part in parts]
    tables = stitch(native_parts, f"{document_id}-t") + stitch(vision_parts, f"{document_id}-v")
    pieces.extend(piece for piece in table_pieces(tables) if piece.page in usable)
    for page_pieces, _ in vision_items.values():
        pieces.extend(page_pieces)
    chunks = assemble(pieces, document_id, pdf.name, sha256)
    chunks = [chunk for chunk in chunks if chunk.page_number in usable]
    summaries = [{"id": t.id, "origin": t.origin, "pages": t.pages, "rows": len(t.rows), "columns": t.columns,
                  "has_header": bool(t.header), "header_inherited_pages": sorted(t.inherited_pages),
                  "group_column": t.group_column, "caption": t.caption} for t in tables]
    return chunks, {chunk.page_number for chunk in chunks}, summaries


# --------------------------------------------------
# Ingest one document
# --------------------------------------------------

def _save_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _run_vision(pdf: Path, sha256: str, pages: list[int], deps: Deps, workers: int) -> dict[int, VisionPageResult]:
    def work(page: int):
        try:
            return page, validate_vision_result(deps.vision(pdf, page, sha256))
        except Exception as exc:
            return page, VisionPageResult(summary=f"{VISION_FAILED} {type(exc).__name__}")

    results: dict[int, VisionPageResult] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for done, (page, result) in enumerate(pool.map(work, pages), start=1):
            results[page] = result
            ok = not (result.summary or "").startswith(VISION_FAILED)
            print(f"    vision {done}/{len(pages)} page {page}: {'ok' if ok else 'FAILED'}", flush=True)
    return results


def ingest_document(pdf: Path, options: Options, deps: Deps) -> dict:
    started = time.monotonic()
    pdf = Path(pdf)
    if is_excluded_document(pdf.name):
        raise ValueError("UAV01/UA03 are excluded; use CAAT UAS Portal")
    if not pdf.exists():
        raise FileNotFoundError(pdf)
    document_id = options.document_id or canonical_document_id(pdf.name)
    if not document_id.strip():
        raise ValueError("document_id cannot be empty")
    sha256 = file_sha256(pdf)
    timings: dict[str, float] = {}

    clock = time.monotonic()
    failed: dict[str, str] = {}
    with pymupdf.open(pdf) as doc:
        total = len(doc)
        requested = _page_range(options, total)
        layouts = _read_all(doc, set(requested), failed)
    timings["read"] = round(time.monotonic() - clock, 2)
    report: dict = {
        "mode": "text", "pipeline": INGESTION_VERSION, "source_file": pdf.name, "document_id": document_id,
        "source_sha256": sha256, "embedding_model": deps.embedding_model, "requested_pages": requested,
        "processed_pages": [], "failed_pages": failed, "degraded_pages": [], "empty_pages": [],
        "blank_pages": [l.page for l in layouts if l.blank and l.page in requested], "vision_pages": {},
        "chunks": 0, "complete": False}
    print(f"[{document_id}] {pdf.name}: {len(requested)} page(s), "
          f"{sum(len(l.tables) for l in layouts if l.page in requested)} native table(s)", flush=True)

    wanted = {page for page in requested if str(page) not in failed}
    plan = _vision_pages(layouts, sorted(wanted), options.vision)
    report["vision_pages"] = {str(page): reason for page, reason in plan.items()}
    clock = time.monotonic()
    results = _run_vision(pdf, sha256, sorted(plan), deps, options.workers) if plan else {}
    timings["vision"] = round(time.monotonic() - clock, 2)
    report["degraded_pages"] = sorted(p for p, r in results.items() if (r.summary or "").startswith(VISION_FAILED))

    clock = time.monotonic()
    chunks, produced, tables = _build(pdf, document_id, sha256, layouts, wanted, results)
    timings["build"] = round(time.monotonic() - clock, 2)
    degraded = set(report["degraded_pages"])
    report["native_only_pages"] = []
    report["purged_pages"] = []
    purge: set[int] = set()
    if degraded:
        # A failed visual pass must preserve an already published *good* page. Existing
        # chunks that are generation loops, or that belong to another version of this PDF,
        # are not good: such a page is rebuilt from its clean native text, or emptied when
        # it has none. Either way the file stays explicitly incomplete so the next run
        # retries its missing visuals.
        covered, unusable = existing_page_quality(deps.collection, pdf.name, sha256)
        covered -= unusable
        recoverable = {layout.page for layout in layouts if layout.page in degraded - covered
                       and layout.text_chars and layout.vision_reason != "corrupted_text_layer"}
        native_pages: set[int] = set()
        if recoverable:
            native, native_pages, _ = _build(pdf, document_id, sha256, layouts, recoverable, {})
            for chunk in native:
                chunk.metadata.update(extraction_complete="false", vision_status="unavailable")
            chunks.extend(native)
            produced |= native_pages
            report["native_only_pages"] = sorted(native_pages)
        purge = (degraded & unusable) - native_pages
        report["purged_pages"] = sorted(purge)
    report["processed_pages"] = sorted(produced)
    covered_pages = set(produced)
    for chunk in chunks:
        first = int(chunk.metadata.get("page_from") or chunk.page_number)
        last = int(chunk.metadata.get("page_end") or chunk.page_number)
        covered_pages.update(range(first, last + 1))
    report["empty_pages"] = sorted(wanted - degraded - covered_pages - set(report["blank_pages"]))
    missing = sorted(degraded | set(report["empty_pages"]) | {int(page) for page in failed})
    marker = f"{requested[0]}-{requested[-1]}" if len(requested) != total else (
        "missing:" + ",".join(map(str, missing)) if missing else "")
    if marker:
        for chunk in chunks:  # a later whole-file run must not mistake a trial or a gappy ingest for a finished one
            chunk.metadata["partial_range"] = marker
    report["chunks"] = len(chunks)
    report["tables"] = tables
    complete = bool(chunks) and not failed and not degraded and not report["empty_pages"]
    try:
        if chunks or purge:
            clock = time.monotonic()
            texts = [chunk.embed_text or chunk.content for chunk in chunks]
            vectors = (cached_document_embeddings(texts, deps.embedding_model, deps.cache_dir, deps.embed_batch)
                       if chunks else [])
            timings["embed"] = round(time.monotonic() - clock, 2)
            if file_sha256(pdf) != sha256:
                raise RuntimeError("Source PDF changed during ingestion; refusing to publish mixed versions")
            clock = time.monotonic()
            whole_file = complete and len(requested) == total
            published = publish(deps.collection, chunks, vectors, pdf.name,
                                None if whole_file else sorted(produced | purge), deps.embedding_model)
            timings["publish"] = round(time.monotonic() - clock, 2)
            report.update(published)
    except Exception as exc:
        report["publish_error"] = type(exc).__name__
        report["timings"] = timings
        report["seconds"] = round(time.monotonic() - started, 3)
        _save_report(report, _report_path(options, document_id, sha256))
        raise
    report["complete"] = complete
    report["timings"] = timings
    report["seconds"] = round(time.monotonic() - started, 3)
    _save_report(report, _report_path(options, document_id, sha256))
    print(f"[{document_id}] {'complete' if complete else 'INCOMPLETE - inspect the report'}: "
          f"{len(chunks)} chunks in {report['seconds']}s", flush=True)
    return report


def existing_page_quality(collection, source_file: str, sha256: str) -> tuple[set[int], set[int]]:
    """Pages the index already covers for this file, and pages holding unusable chunks.

    Unusable: a generation loop, or a chunk stamped with another version (sha256) of the PDF.
    Legacy chunks carry no sha256 and cannot be judged by version, so only the loop check applies."""
    existing = collection.get(where={"source_file": source_file}, include=["metadatas", "documents"])
    covered: set[int] = set()
    unusable: set[int] = set()
    for meta, document in zip(existing.get("metadatas") or [], existing.get("documents") or []):
        meta = meta or {}
        anchor = int(meta["page_number"])
        other_version = bool(meta.get("source_sha256")) and meta["source_sha256"] != sha256
        if other_version or is_generation_loop(document or ""):
            unusable.add(anchor)
        covered.update(range(int(meta.get("page_from") or anchor), int(meta.get("page_end") or anchor) + 1))
    return covered, unusable


def _report_path(options: Options, document_id: str, sha256: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in document_id)
    return Path(options.report_dir) / f"{safe}.{sha256[:8]}.report.json"


# --------------------------------------------------
# Batch
# --------------------------------------------------

def estimated_embedding_calls(chunks: int) -> int:
    return math.ceil(chunks / max(int(os.getenv("EMBED_BATCH_SIZE", "24")), 1))


def run(paths: list[Path], options: Options, deps: Deps) -> list[dict]:
    """Ingest each PDF that needs it. A file that fails never stops the others."""
    reports = []
    for pdf in paths:
        pdf = Path(pdf)
        try:
            status = "new" if options.pages else index_status(deps.collection, pdf.name, file_sha256(pdf))
            if is_excluded_document(pdf.name):
                reports.append({"source_file": pdf.name, "skipped": "excluded", "complete": True})
            elif status == "up_to_date" and not options.force and not options.pages:
                reports.append({"source_file": pdf.name, "skipped": "up_to_date", "complete": True})
            elif status == "legacy" and not options.force and not options.pages:
                reports.append({"source_file": pdf.name, "skipped": "legacy_requires_force", "complete": True})
            else:
                reports.append(ingest_document(pdf, options, deps))
        except Exception as exc:
            print(f"[FAILED] {pdf.name}: {type(exc).__name__}: {exc}", flush=True)
            reports.append({"source_file": pdf.name, "error": type(exc).__name__, "complete": False})
    return reports
