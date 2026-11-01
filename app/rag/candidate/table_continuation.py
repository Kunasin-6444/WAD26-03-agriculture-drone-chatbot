"""Multi-page table continuation resolution and comparison scope assembly for candidate RAG.

Ensures comparison and superlative queries (cheapest, most expensive, full lists, etc.)
retrieve all contiguous pages of a structured table rather than losing continuation
pages or picking UI/template comparison mockups.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from app.rag.evidence import Evidence

logger = logging.getLogger(__name__)

# Superlative, comparative, and exhaustive table query indicators
_COMPARATIVE_PATTERNS = re.compile(
    r"(?:ถูก|แพง|มาก|น้อย|ต่ำ|สูง|ดี|คุ้ม|เร็ว|ช้า|หนัก|เบา|กว้าง|แคบ|ประหยัด)ที่สุด|"
    r"เปรียบเทียบ|เทียบ(?:ราคา|สเปก|ข้อมูล|รุ่น)?|"
    r"ในตาราง|ตามตาราง|ตารางราคา|ตารางที่|"
    r"ทั้งหมด|มี.*กี่|มี.*บ้าง|ทุกรุ่น|รายชื่อ|รายการ.*ทั้งหมด",
    re.IGNORECASE,
)

# Marker for UI mockups, screenshots, and code templates that should not be merged as data tables
_UI_TEMPLATE_INDICATORS = re.compile(
    r"\${(?:formatNumber|data\.drone_)|"
    r"ภาพที่\s*\d+\s*(?:แสดง|ผลลัพธ์)|"
    r"ภาพหน้าจอ(?:แสดง|ระบบ|แอปพลิเคชัน)|"
    r"การคลิกเลือกโดรนเพื่อเปรียบเทียบ|"
    r"ส่วนติดต่อผู้ใช้งาน",
    re.IGNORECASE,
)


@dataclass
class TableMetadata:
    source_file: str
    page_number: str
    table_id: str = ""
    row_start: int | None = None
    row_end: int | None = None
    headers: list[str] = field(default_factory=list)
    caption: str = ""
    is_ui_template: bool = False
    is_structured_table: bool = False
    content: str = ""


def is_comparative_or_table_query(query: str) -> bool:
    """Detect if query asks for comparison, superlatives, or table data."""
    return bool(_COMPARATIVE_PATTERNS.search(query or ""))


def is_ui_template_content(content: str) -> bool:
    """Detect if content is a UI mockup, screenshot description, or code template."""
    return bool(_UI_TEMPLATE_INDICATORS.search(content or ""))


def extract_table_headers(content: str) -> list[str]:
    """Extract clean column headers from a markdown table string."""
    for line in (content or "").splitlines():
        line = line.strip()
        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
            if parts and parts[0] == "":
                parts = parts[1:]
            if parts and parts[-1] == "":
                parts = parts[:-1]
            if parts and not all(re.match(r"^:?-+:?$", p) for p in parts):
                return parts
    return []


def extract_table_caption(content: str) -> str:
    """Extract table caption or title, e.g. 'ตารางที่ 4 ...' or preamble line before table."""
    match = re.search(r"(ตารางที่\s*\d+[^\n]*)", content or "")
    if match:
        return match.group(1).strip()
    for line in (content or "").splitlines():
        line = line.strip()
        if not line or line.startswith("---") or line.startswith("#"):
            continue
        if "|" in line:
            break
        return line
    return ""


def parse_table_metadata(evidence: Evidence, meta_dict: dict[str, Any] | None = None) -> TableMetadata:
    """Extract table metadata from Evidence object and optional raw index metadata."""
    meta = meta_dict or {}
    content = evidence.content or ""
    headers = extract_table_headers(content)
    caption = extract_table_caption(content)
    is_ui = is_ui_template_content(content)

    table_id = str(meta.get("table_id") or "")
    # Fallback table_id extraction from caption if not in metadata
    if not table_id and caption:
        cap_num = re.search(r"ตารางที่\s*(\d+)", caption)
        if cap_num:
            table_id = f"table-{cap_num.group(1)}"

    row_s = meta.get("row_start")
    row_e = meta.get("row_end")
    try:
        r_start = int(row_s) if row_s is not None and str(row_s).isdigit() else None
    except (ValueError, TypeError):
        r_start = None
    try:
        r_end = int(row_e) if row_e is not None and str(row_e).isdigit() else None
    except (ValueError, TypeError):
        r_end = None

    has_table_rows = bool(headers) or (r_start is not None and r_end is not None)

    return TableMetadata(
        source_file=evidence.source_file,
        page_number=evidence.page_number,
        table_id=table_id,
        row_start=r_start,
        row_end=r_end,
        headers=headers,
        caption=caption,
        is_ui_template=is_ui,
        is_structured_table=has_table_rows and not is_ui,
        content=content,
    )


def check_units_conflict(table_a: TableMetadata, table_b: TableMetadata) -> bool:
    """Return True if tables have conflicting units across columns or captions."""
    # Compare column-by-column units when headers match in count
    if table_a.headers and table_b.headers and len(table_a.headers) == len(table_b.headers):
        for h_a, h_b in zip(table_a.headers, table_b.headers):
            units_a = re.findall(r"\(([^)]+)\)", h_a)
            units_b = re.findall(r"\(([^)]+)\)", h_b)
            if units_a and units_b:
                norm_u_a = [u.strip().lower() for u in units_a]
                norm_u_b = [u.strip().lower() for u in units_b]
                if norm_u_a != norm_u_b:
                    return True

    # Check overall currency/unit conflicts in headers, captions, or content
    text_a = f"{table_a.caption} {' '.join(table_a.headers)} {table_a.content}".lower()
    text_b = f"{table_b.caption} {' '.join(table_b.headers)} {table_b.content}".lower()

    thb_kw = ["บาท", "thb", "฿"]
    usd_kw = ["usd", "dollar", "$", "ดอลลาร์"]
    a_thb = any(k in text_a for k in thb_kw)
    b_thb = any(k in text_b for k in thb_kw)
    a_usd = any(k in text_a for k in usd_kw)
    b_usd = any(k in text_b for k in usd_kw)
    if (a_thb and b_usd) or (a_usd and b_thb):
        return True

    return False


def check_conditions_conflict(text_a: str, text_b: str) -> bool:
    """Return True if texts have explicitly conflicting conditions, scopes, or statuses."""
    if not text_a or not text_b:
        return False
    a_low = text_a.lower()
    b_low = text_b.lower()

    # 1. New vs Used status conflict
    new_kw = ["เครื่องใหม่", "ของใหม่", "สภาพใหม่"]
    used_kw = ["มือสอง", "มือ 2", "ใช้แล้ว"]
    a_has_new = any(k in a_low for k in new_kw)
    b_has_new = any(k in b_low for k in new_kw)
    a_has_used = any(k in used_kw for k in used_kw if k in a_low)
    b_has_used = any(k in used_kw for k in used_kw if k in b_low)
    if (a_has_new and b_has_used) or (a_has_used and b_has_new):
        return True

    # 2. Inclusion vs Exclusion conflict (e.g. รวมแบตเตอรี่ vs ไม่รวมแบตเตอรี่)
    exclusions_a = set(re.findall(r"ไม่รวม\s*(\w+)", a_low))
    inclusions_a = set(re.findall(r"(?<!ไม่)รวม\s*(\w+)", a_low))
    exclusions_b = set(re.findall(r"ไม่รวม\s*(\w+)", b_low))
    inclusions_b = set(re.findall(r"(?<!ไม่)รวม\s*(\w+)", b_low))

    if (inclusions_a & exclusions_b) or (exclusions_a & inclusions_b):
        return True

    # 3. Explicit operational scope conflict (e.g. โดรนสำรวจ vs โดรนฉีดพ่น)
    a_is_survey = "โดรนสำรวจ" in a_low
    b_is_survey = "โดรนสำรวจ" in b_low
    a_is_spray = "โดรนฉีดพ่น" in a_low or "โดรนเกษตร" in a_low
    b_is_spray = "โดรนฉีดพ่น" in b_low or "โดรนเกษตร" in b_low
    if (a_is_survey and b_is_spray) or (a_is_spray and b_is_survey):
        return True

    # 4. Incompatible numbered packages (e.g. แพ็กเกจ 1 vs แพ็กเกจ 2)
    pkg_a = set(re.findall(r"แพ็กเกจ\s*([a-zA-Z0-9]+)", a_low))
    pkg_b = set(re.findall(r"แพ็กเกจ\s*([a-zA-Z0-9]+)", b_low))
    if pkg_a and pkg_b and pkg_a != pkg_b:
        return True

    return False


def are_tables_compatible(table_a: TableMetadata, table_b: TableMetadata) -> bool:
    """Check if table_b is a compatible continuation or segment of table_a."""
    if table_a.source_file != table_b.source_file:
        return False

    if table_a.is_ui_template or table_b.is_ui_template:
        return False

    # 1. HARD NEGATIVE: Unit conflicts (USD vs THB, ml vs L, etc.)
    if check_units_conflict(table_a, table_b):
        return False

    # 2. HARD NEGATIVE: Condition / Scope / Status conflicts (new vs used, with vs without battery, etc.)
    text_a = f"{table_a.caption} {' '.join(table_a.headers)} {table_a.content}"
    text_b = f"{table_b.caption} {' '.join(table_b.headers)} {table_b.content}"
    if check_conditions_conflict(text_a, text_b):
        return False

    # 3. Explicit table_id matching
    if table_a.table_id and table_b.table_id:
        norm_id_a = table_a.table_id.strip().lower()
        norm_id_b = table_b.table_id.strip().lower()

        if norm_id_a == norm_id_b:
            return True

        # Normalized pure table numbers (e.g. "t1" vs "table-1" vs "ตารางที่ 1")
        # ONLY if the whole id is a table number, not when having different content prefixes
        pure_num_a = re.fullmatch(r"(?:table|t|ตารางที่)?[-_\s]*(\d+)", norm_id_a)
        pure_num_b = re.fullmatch(r"(?:table|t|ตารางที่)?[-_\s]*(\d+)", norm_id_b)
        if pure_num_a and pure_num_b and pure_num_a.group(1) == pure_num_b.group(1):
            return True

        # When both have explicit IDs and they do not match, they are explicitly DIFFERENT tables!
        # Must NOT fall through to caption, row numbers, or headers!
        return False

    # 4. Matching table caption (e.g. "ตารางที่ 4" and "ตารางที่ 4 (ต่อ)")
    if table_a.caption and table_b.caption:
        base_a = re.sub(r"\(ต่อ\)", "", table_a.caption).strip()
        base_b = re.sub(r"\(ต่อ\)", "", table_b.caption).strip()
        if base_a and base_a == base_b:
            return True

    # 5. Contiguous row ranges (only if headers do not conflict in column count)
    if (
        table_a.row_end is not None
        and table_b.row_start is not None
        and (table_b.row_start == table_a.row_end + 1 or table_a.row_start == table_b.row_end + 1)
    ):
        if table_a.headers and table_b.headers and len(table_a.headers) != len(table_b.headers):
            return False
        return True

    # 6. Identical headers with non-conflicting captions
    if table_a.headers and table_b.headers and len(table_a.headers) == len(table_b.headers):
        norm_a = [re.sub(r"\s+", "", re.sub(r"\([^)]*\)", "", h)).lower() for h in table_a.headers]
        norm_b = [re.sub(r"\s+", "", re.sub(r"\([^)]*\)", "", h)).lower() for h in table_b.headers]
        if norm_a == norm_b:
            return True

    return False


def _chroma_table_lookup(source_file: str, table_id: str | None = None) -> list[tuple[Evidence, dict[str, Any]]]:
    """Query Chroma collection for chunks of the same document (zero network/API call)."""
    try:
        from app.rag.vector_store import collection

        res = collection.get(where={"source_file": source_file}, include=["metadatas", "documents"])
        items: list[tuple[Evidence, dict[str, Any]]] = []
        for meta, doc in zip(res.get("metadatas") or [], res.get("documents") or []):
            meta = meta or {}
            page_num = str(meta.get("page_number", ""))
            if not page_num.isdigit():
                continue
            ev = Evidence(
                id=f"D_cont_{page_num}",
                content=(doc or "").strip(),
                source_file=source_file,
                page_number=page_num,
                page_from=str(meta.get("page_from") or page_num),
                page_end=str(meta.get("page_end") or page_num),
            )
            items.append((ev, meta))
        return items
    except Exception as exc:
        logger.warning("Chroma table lookup failed: %s", exc)
        raise RuntimeError(f"Chroma table lookup failed for {source_file}: {exc}") from exc


def assemble_candidate_table_evidence(
    evidence_list: Sequence[Evidence],
    query: str,
    max_table_chunks: int = 12,
    lookup_fn: Callable[[str, str | None], list[tuple[Evidence, dict[str, Any]]]] | None = None,
    enabled: bool = True,
) -> tuple[list[Evidence], dict[str, Any]]:
    """Assemble table continuations for comparative or table queries.

    Args:
        evidence_list: Initial retrieved evidence
        query: User query string
        max_table_chunks: Maximum table continuation chunks to include
        lookup_fn: Optional callable for offline/synthetic testing
        enabled: Allows disabling table continuation for regression mutation check

    Returns:
        assembled_evidence: list of Evidence with table continuations attached.
        diagnostics: tracking metadata (stage, table_id, coverage, total_pages, included_pages).
    """
    if not enabled:
        return list(evidence_list), {"table_continuation_applied": False, "reason": "feature_disabled"}

    is_comp = is_comparative_or_table_query(query)
    if not is_comp:
        return list(evidence_list), {"table_continuation_applied": False, "reason": "non_comparative_query"}

    # Identify anchors among retrieved evidence
    anchors: list[tuple[Evidence, TableMetadata]] = []
    for ev in evidence_list:
        t_meta = parse_table_metadata(ev)
        if t_meta.is_structured_table:
            anchors.append((ev, t_meta))

    if not anchors:
        return list(evidence_list), {"table_continuation_applied": False, "reason": "no_structured_table_anchors"}

    lookup = lookup_fn or _chroma_table_lookup

    # Use chunk-specific key (source_file, page_number, content) to avoid dropping row chunks on the same page
    expanded_pool: dict[tuple[str, str, str], tuple[Evidence, TableMetadata]] = {}
    table_diagnostics: list[dict[str, Any]] = []

    for anchor_ev, anchor_meta in anchors:
        anchor_key = (anchor_ev.source_file, anchor_ev.page_number, anchor_ev.content.strip())
        expanded_pool[anchor_key] = (anchor_ev, anchor_meta)

        lookup_error: str | None = None
        try:
            candidates = lookup(anchor_meta.source_file, anchor_meta.table_id if anchor_meta.table_id else None)
        except TimeoutError:
            raise  # do not turn an exhausted request into apparently usable scope
        except Exception as exc:
            lookup_error = str(exc)
            candidates = []

        if lookup_error:
            table_diagnostics.append({
                "stage": "table_continuation",
                "source_file": anchor_meta.source_file,
                "table_id": anchor_meta.table_id or anchor_meta.caption,
                "coverage": "unknown",
                "status": "lookup_error",
                "error": lookup_error,
                "total_pages": 1,
                "total_chunks": 1,
                "included_pages": [anchor_meta.page_number],
                "missing_pages": [],
                "included_chunks": [(anchor_meta.source_file, str(anchor_meta.page_number), anchor_ev.content.strip())],
                "missing_chunks": [],
            })
            continue

        if not candidates:
            # Empty lookup must NOT certify complete scope
            table_diagnostics.append({
                "stage": "table_continuation",
                "source_file": anchor_meta.source_file,
                "table_id": anchor_meta.table_id or anchor_meta.caption,
                "coverage": "unknown",
                "status": "lookup_empty",
                "total_pages": 1,
                "total_chunks": 1,
                "included_pages": [anchor_meta.page_number],
                "missing_pages": [],
                "included_chunks": [(anchor_meta.source_file, str(anchor_meta.page_number), anchor_ev.content.strip())],
                "missing_chunks": [],
            })
            continue

        # Enrich anchor metadata from matching candidate record if anchor lacked explicit table_id or row info
        for cand_ev, cand_meta_dict in candidates:
            if (cand_ev.source_file == anchor_ev.source_file and str(cand_ev.page_number) == str(anchor_ev.page_number)
                    and cand_ev.content.strip() == anchor_ev.content.strip()):
                if cand_meta_dict:
                    is_exact_chunk = cand_ev.content.strip() == anchor_ev.content.strip()
                    cand_meta = parse_table_metadata(cand_ev, cand_meta_dict)
                    explicit_id = str(cand_meta_dict.get("table_id") or "")
                    if explicit_id and (is_exact_chunk or not anchor_meta.table_id or anchor_meta.table_id.startswith("table-")):
                        anchor_meta.table_id = explicit_id
                    if anchor_meta.row_start is None and cand_meta.row_start is not None:
                        anchor_meta.row_start = cand_meta.row_start
                    if anchor_meta.row_end is None and cand_meta.row_end is not None:
                        anchor_meta.row_end = cand_meta.row_end
                    if not anchor_meta.caption and cand_meta.caption:
                        anchor_meta.caption = cand_meta.caption

        matching_pages: list[tuple[Evidence, TableMetadata]] = []
        for cand_ev, cand_meta_dict in candidates:
            cand_meta = parse_table_metadata(cand_ev, cand_meta_dict)
            if are_tables_compatible(anchor_meta, cand_meta):
                matching_pages.append((cand_ev, cand_meta))

        # For tables without explicit table_id or shared caption (matching on headers alone),
        # enforce contiguous page chaining from the anchor to prevent jumping over gaps to distant tables
        if not anchor_meta.table_id and not anchor_meta.caption:
            anchor_p = int(anchor_meta.page_number) if anchor_meta.page_number.isdigit() else 1
            matching_pages.sort(key=lambda item: int(item[0].page_number) if item[0].page_number.isdigit() else 9999)

            forward_pages: set[int] = {anchor_p}
            curr = anchor_p
            while True:
                next_p = curr + 1
                if any(int(item[0].page_number) == next_p for item in matching_pages if item[0].page_number.isdigit()):
                    forward_pages.add(next_p)
                    curr = next_p
                else:
                    break

            backward_pages: set[int] = {anchor_p}
            curr = anchor_p
            while True:
                prev_p = curr - 1
                if any(int(item[0].page_number) == prev_p for item in matching_pages if item[0].page_number.isdigit()):
                    backward_pages.add(prev_p)
                    curr = prev_p
                else:
                    break

            allowed_pages = forward_pages | backward_pages
            matching_pages = [
                item for item in matching_pages
                if item[0].page_number.isdigit() and int(item[0].page_number) in allowed_pages
            ]

        # Ensure anchor itself is included in matching_pages if compatible
        anchor_in_matching = any(
            (cand_ev.source_file == anchor_ev.source_file and str(cand_ev.page_number) == str(anchor_ev.page_number) and cand_ev.content.strip() == anchor_ev.content.strip())
            for cand_ev, _ in matching_pages
        )
        if not anchor_in_matching:
            matching_pages.append((anchor_ev, anchor_meta))

        # Sort matching pages by page number and row start
        def sort_key(item: tuple[Evidence, TableMetadata]) -> tuple[int, int, str]:
            p_int = int(item[0].page_number) if item[0].page_number.isdigit() else 9999
            r_int = item[1].row_start if item[1].row_start is not None else 0
            return (p_int, r_int, item[0].id)

        matching_pages.sort(key=sort_key)

        distinct_pages = sorted(
            list({item[0].page_number for item in matching_pages}),
            key=lambda p: int(p) if p.isdigit() else 9999,
        )
        total_pages = len(distinct_pages)
        total_chunks = len(matching_pages)

        if total_chunks > max_table_chunks:
            coverage = "incomplete"
            included = matching_pages[:max_table_chunks]
            included_pages_set = {item[0].page_number for item in included}
            missing = sorted(
                list({item[0].page_number for item in matching_pages[max_table_chunks:]} - included_pages_set),
                key=lambda p: int(p) if p.isdigit() else 9999,
            )
        else:
            coverage = "complete"
            included = matching_pages
            missing = []

        # Retrieval coverage cannot erase a known extraction failure. Retain the
        # usable source rows but forbid a global comparison over degraded data.
        incomplete_keys = {(ev.source_file, str(ev.page_number), ev.content.strip()) for ev, meta in candidates
            if str((meta or {}).get('extraction_complete', '')).casefold() in {'false','0','no'}
            or str((meta or {}).get('vision_status', '')).casefold() in {'failed','unavailable','incomplete','degraded'}}
        extraction_incomplete = [(ev.source_file, str(ev.page_number), ev.content.strip()) for ev, _ in included
            if (ev.source_file, str(ev.page_number), ev.content.strip()) in incomplete_keys]
        if extraction_incomplete:
            coverage = 'incomplete'

        for ev, meta in included:
            c_key = (ev.source_file, ev.page_number, ev.content.strip())
            if c_key not in expanded_pool:
                expanded_pool[c_key] = (ev, meta)

        table_diagnostics.append({
            "stage": "table_continuation",
            "source_file": anchor_meta.source_file,
            "table_id": anchor_meta.table_id or anchor_meta.caption,
            "coverage": coverage,
            "total_pages": total_pages,
            "total_chunks": total_chunks,
            "included_pages": sorted(list({item[0].page_number for item in included}), key=lambda p: int(p) if p.isdigit() else 9999),
            "missing_pages": missing,
            "included_chunks": [(item[0].source_file, str(item[0].page_number), item[0].content.strip()) for item in included],
            "missing_chunks": [(item[0].source_file, str(item[0].page_number), item[0].content.strip()) for item in matching_pages[max_table_chunks:]] if total_chunks > max_table_chunks else [],
            "extraction_incomplete_chunks": extraction_incomplete,
        })

    # Assemble result: table pages first (in document order), then remaining non-table evidence
    table_items = [item[0] for item in expanded_pool.values()]
    table_items.sort(key=lambda e: (e.source_file, int(e.page_number) if e.page_number.isdigit() else 9999, e.id))

    seen_keys = {(e.source_file, e.page_number, e.content.strip()) for e in table_items}
    non_table_items = [e for e in evidence_list if (e.source_file, e.page_number, e.content.strip()) not in seen_keys]

    assembled = table_items + non_table_items

    return assembled, {
        "stage": "table_continuation",
        "table_continuation_applied": True,
        "tables": table_diagnostics,
        "assembled_count": len(assembled),
    }
