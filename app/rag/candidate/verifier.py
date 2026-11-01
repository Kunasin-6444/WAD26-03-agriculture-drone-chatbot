from __future__ import annotations

import re
from decimal import Decimal
from typing import Sequence

from app.rag.candidate.models import VerificationResult
from app.rag.claim_consistency import claim_inconsistency
from app.rag.evidence import (
    CHEMICAL_NOTE,
    Evidence,
    _is_aviation_regulation,
    _numbers,
    needs_chemical_note,
)
from app.rag.source_policy import is_caat_url, without_document_ids
from app.rag.table_grounding import table_inconsistency

_MARKER_REGEX = re.compile(r"\[\s*([DW]\d+(?:\s*[,，]\s*[DW]\d+)*)\s*\]")
_MISSING_REGEX = re.compile(r"^\s*(?:ยังไม่พบข้อมูล|ยังยืนยันไม่ได้)\s*[:：]\s*(.*)$")
_LIST_PREFIX = re.compile(r"^\s*(?:[-•*·]|\d{1,2}[.)])\s*")
_BAHT_AMOUNT = re.compile(r"(?<![\d.,])(?P<amount>\d+(?:,\d{3})*(?:\.\d+)?)\s*(?P<scale>ล้าน|แสน|หมื่น|พัน)?\s*บาท")
_MONEY_SCALES = {None: Decimal(1), "พัน": Decimal(1000), "หมื่น": Decimal(10000), "แสน": Decimal(100000), "ล้าน": Decimal(1000000)}
_MODEL_FOOTER = re.compile(r"^\s*(?:แหล่งอ้างอิง|อ้างอิง|References?)\s*[:：]?\s*$", re.IGNORECASE)

CAAT_NOTE = "หมายเหตุ: ข้อกำหนดของ กพท. เปลี่ยนตามประกาศได้ ก่อนบินจริงควรตรวจประกาศล่าสุดที่ https://uasportal.caat.or.th"
CAAT_PAGE_REQUIRED = "drone regulation requires actual CAAT official source"


def _expand_money(text: str) -> str:
    """Normalize Thai currency expressions (e.g. 1 ล้านบาท -> 1000000 บาท)."""
    def _repl(m: re.Match) -> str:
        amt = Decimal(m.group("amount").replace(",", "")) * _MONEY_SCALES[m.group("scale")]
        return f"{amt:f} บาท"
    return _BAHT_AMOUNT.sub(_repl, text)


def clean_chat_formatting(text: str) -> str:
    """Remove markdown bold, headings, and fences for clean mobile chat display."""
    t = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", r"\1", text)
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.MULTILINE)
    t = re.sub(r"(?<=\d)\s*[–—]\s*(?=\d)", "-", t)
    t = re.sub(r"^\s*```\w*\s*$", "", t, flags=re.MULTILINE)
    return t.strip()


def extract_markers(line: str) -> list[str]:
    """Find all source IDs in a line like [D1, D2] -> ['D1', 'D2']."""
    found: list[str] = []
    for match in _MARKER_REGEX.finditer(line):
        parts = re.split(r"[,，]", match.group(1))
        for p in parts:
            clean = p.strip()
            if clean and clean not in found:
                found.append(clean)
    return found


def check_line_integrity(line: str, ids: list[str], by_id: dict[str, Evidence]) -> str:
    """Return empty string if line is valid, or specific problem string."""
    plain = _expand_money(_LIST_PREFIX.sub("", _MARKER_REGEX.sub("", line)).strip())
    numbers = _numbers(without_document_ids(plain))

    if not ids:
        return "factual claim with numbers has no source" if numbers else ""

    unknown = [i for i in ids if i not in by_id]
    if unknown:
        return f"unknown source ids: {unknown}"

    # Aviation regulations must cite a CAAT web source
    if _is_aviation_regulation(plain) and any(not is_caat_url(by_id[i].url) for i in ids):
        return CAAT_PAGE_REQUIRED

    monetary = bool(_BAHT_AMOUNT.search(plain))
    cited = " ".join(f"{by_id[i].content} {by_id[i].title}" for i in ids)
    if monetary:
        cited = _expand_money(cited)

    if not numbers <= _numbers(cited):
        return f"unsupported numbers: {sorted(str(n) for n in (numbers - _numbers(cited)))}"

    # Check units, weed classes, chemicals, nozzle colours, crops
    problem = claim_inconsistency(plain, [], cited)
    if problem:
        return problem

    # Check table row-cell consistency
    for i in ids:
        content = _expand_money(by_id[i].content) if monetary else by_id[i].content
        problem = table_inconsistency(without_document_ids(plain), [], content)
        if problem:
            return problem

    return ""


def verify_and_render_candidate(
    raw_text: str,
    evidence_list: Sequence[Evidence],
    service_note: str = "",
) -> VerificationResult:
    """Non-destructively verify candidate generation against supplied evidence.

    Checks:
    1. NOT_FOUND detection
    2. Missing aspect detection
    3. Block-level citation inheritance for list items under cited headings
    4. Source existence and CAAT regulatory policy
    5. Numeric grounding, unit consistency, and table row-cell bindings
    6. Numbered references [1], [2] and bibliography rendering
    """
    clean_text = clean_chat_formatting(raw_text or "")
    if not clean_text or clean_text.strip("` \n").upper() == "NOT_FOUND":
        return VerificationResult(
            raw_text=raw_text,
            is_not_found=True,
            passed_citations=True,
        )

    by_id: dict[str, Evidence] = {e.id: e for e in evidence_list}
    dropped_reasons: list[str] = []
    warnings: list[str] = []
    unverified_numbers: list[str] = []
    missing_aspect = ""

    # Group lines into blocks separated by blank lines to allow list items under a
    # cited heading to inherit its citation source.
    blocks: list[list[str]] = [[]]
    for line in clean_text.splitlines():
        trimmed = line.strip()
        if not trimmed:
            blocks.append([])
        elif not _MODEL_FOOTER.match(trimmed):
            blocks[-1].append(trimmed)

    verified_lines: list[tuple[str, list[str]]] = []

    for block in blocks:
        own_ids = [extract_markers(line) for line in block]
        for idx, line in enumerate(block):
            missing_match = _MISSING_REGEX.match(line)
            if missing_match:
                missing_aspect = missing_match.group(1).strip()
                continue

            ids = own_ids[idx]
            # Inherit from preceding marked heading in the same block if line is an un-marked item
            if not ids:
                before = [f for f in own_ids[:idx] if f]
                after = [f for f in own_ids[idx + 1 :] if f]
                ids = before[-1] if before else (after[0] if after else [])

            problem = check_line_integrity(line, ids, by_id)
            if problem:
                dropped_reasons.append(f"{problem}: {line[:80]}")
                if "unsupported numbers" in problem:
                    unverified_numbers.append(problem)
            else:
                # If line did not have its own marker, keep plain body without markers
                cleaned_line = line if own_ids[idx] else _MARKER_REGEX.sub("", line).strip()
                verified_lines.append((cleaned_line, ids))

    # Any factual answer must be supported by at least one valid source
    has_any_source = any(bool(ids) for _, ids in verified_lines)
    if not verified_lines or not has_any_source:
        return VerificationResult(
            raw_text=raw_text,
            is_not_found=True,
            passed_citations=False,
            dropped_reasons=dropped_reasons or ["no verified sources support this answer"],
            unverified_numbers=unverified_numbers,
            missing_aspect=missing_aspect,
        )

    # Build reference mapping
    references: dict[tuple, tuple[int, str]] = {}
    id_to_num: dict[str, int] = {}

    for _, ids in verified_lines:
        for source_id in ids:
            item = by_id[source_id]
            key = (item.url,) if item.url else (item.source_file, item.page_number)
            if key not in references:
                ref_num = len(references) + 1
                references[key] = (ref_num, item.citation)
            id_to_num[source_id] = references[key][0]

    used_source_ids = list(id_to_num.keys())

    # Format body with numbered citations
    formatted_body_lines: list[str] = []
    evidence_trace: list[dict] = []

    for line, ids in verified_lines:
        if ids:
            clean_body = _MARKER_REGEX.sub("", line).rstrip()
            ref_nums = sorted(dict.fromkeys(id_to_num[i] for i in ids if i in id_to_num))
            citation_str = f" [{','.join(str(n) for n in ref_nums)}]" if _MARKER_REGEX.search(line) else ""
            rendered_line = clean_body + citation_str
            formatted_body_lines.append(rendered_line)

            evidence_items = []
            for i in ids:
                ev = by_id[i]
                ev_dict = {
                    "source_id": i,
                    "citation": ev.citation,
                    "source_file": ev.source_file,
                    "page_number": ev.page_number,
                    "url": ev.url,
                }
                evidence_items.append(ev_dict)

            evidence_trace.append({
                "text": rendered_line,
                "evidence": evidence_items,
            })
        else:
            formatted_body_lines.append(line)

    body = "\n".join(formatted_body_lines)

    if missing_aspect:
        body += f"\n\nยังไม่พบข้อมูล: {missing_aspect}"

    if service_note:
        body += f"\n\n({service_note})"

    # Advisory notes
    cited_evidence = [by_id[i] for i in used_source_ids if i in by_id]
    from app.rag.evidence import Claim
    claims = [Claim(l, tuple(ids)) for l, ids in verified_lines if ids]
    if needs_chemical_note(claims, cited_evidence):
        body += f"\n\n{CHEMICAL_NOTE}"

    if any(is_caat_url(e.url) for e in cited_evidence):
        body += f"\n\n{CAAT_NOTE}"

    ref_list = "\n".join(f"[{num}] {cit}" for num, cit in sorted(references.values(), key=lambda r: r[0]))
    final_rendered = f"{body}\n\nแหล่งอ้างอิง:\n{ref_list}"

    return VerificationResult(
        rendered_text=final_rendered,
        raw_text=raw_text,
        used_source_ids=used_source_ids,
        passed_citations=len(dropped_reasons) == 0,
        unverified_numbers=unverified_numbers,
        dropped_reasons=dropped_reasons,
        warnings=warnings,
        missing_aspect=missing_aspect,
        is_not_found=False,
        evidence_trace=evidence_trace,
    )
