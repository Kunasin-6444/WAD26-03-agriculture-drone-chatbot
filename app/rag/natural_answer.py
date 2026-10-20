"""Plain-language answers with inline source markers, checked line by line (ANSWER_MODE=natural).

The JSON-claims answer (one claim + verbatim quote each, repair round on any mismatch) was slow and
dropped correct facts; the 2026-10-20 screening put most failures there. Here the model writes the
answer the way an ordinary assistant does and ends each factual line with markers such as [D1].
The server keeps a line only when its numbers, table rows and labels agree with the sources it
cites, renumbers the markers into [1], [2] … and builds the reference list from index metadata, so
page numbers never come from the model. A failing line is dropped; the model is not called again.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.rag.claim_consistency import claim_inconsistency
from app.rag.evidence import (CHEMICAL_NOTE, MAX_ANSWER_CHARS, Claim, Evidence, _is_aviation_regulation, _numbers,
                              needs_chemical_note)
from app.rag.source_policy import is_caat_url, without_document_ids
from app.rag.table_grounding import table_inconsistency

PROMPT = (Path(__file__).parent / "prompts" / "natural_answer.txt").read_text(encoding="utf-8")
NOT_FOUND = "NOT_FOUND"
GAP_LABEL = "ยังยืนยันไม่ได้: "
DROPPED_GAP = "บางส่วนของคำตอบตรวจกับแหล่งอ้างอิงไม่ผ่าน จึงไม่แสดง"
CAAT_PAGE_REQUIRED = "drone-law line without a CAAT page"
# CAAT web results include dated announcements (a 2025 temporary night-flight ban read as a standing
# rule, 2026-10-20); the system says so instead of trusting every model to name the announcement.
CAAT_NOTE = "หมายเหตุ: ข้อกำหนดของ กพท. เปลี่ยนตามประกาศได้ ก่อนบินจริงควรตรวจประกาศล่าสุดที่ https://uasportal.caat.or.th"
CAAT_NEWS_NOTE = ("หมายเหตุ: ข้อมูลบางส่วนมาจากข่าวของ กพท. ({title}) ซึ่งอาจเป็นเงื่อนไขเฉพาะช่วงเวลา "
                  "ก่อนบินจริงควรตรวจประกาศล่าสุดที่ https://uasportal.caat.or.th")
# A news or announcement page: the CAAT media section, or a title that names one ("CAAT NEWS 15/2568").
_NEWS_URL = re.compile(r"/(?:caat-media|news)/", re.IGNORECASE)
_NEWS_TITLE = re.compile(r"\bNEWS\b|ข่าว|ประกาศ\s*ฉบับ", re.IGNORECASE)
_MARKER = re.compile(r"\[\s*([DW]\d+(?:\s*[,，]\s*[DW]\d+)*)\s*\]")
_LIST_PREFIX = re.compile(r"^\s*(?:[-•*·]|\d{1,2}[.)])\s*")
_MISSING = re.compile(r"^\s*(?:ยังไม่พบข้อมูล|ยังยืนยันไม่ได้)\s*[:：]\s*(.*)$")
_BARE_ID = re.compile(r"(?<![\w\[])[DW]\d{1,2}(?![\w\]])")
_MODEL_FOOTER = re.compile(r"^\s*(?:แหล่งอ้างอิง|อ้างอิง|References?)\s*[:：]?\s*$", re.IGNORECASE)


@dataclass
class NaturalAnswer:
    text: str = ""                               # what the user sees; "" when no line survived
    used_ids: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)   # "<reason>: <line>" for diagnostics
    lines: list[tuple[str, list[str]]] = field(default_factory=list)
    not_found: bool = False
    gap: str = ""


def build_messages(query: str, evidence: list[Evidence]) -> list[dict]:
    payload = {"question": query, "today": datetime.now(timezone(timedelta(hours=7))).date().isoformat(),
               "sources": [{k: v for k, v in e.__dict__.items() if v} for e in evidence]}
    return [{"role": "system", "content": PROMPT}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


def _ids(line: str) -> list[str]:
    return list(dict.fromkeys(i.strip() for m in _MARKER.finditer(line) for i in re.split(r"[,，]", m.group(1))))


def _named_sources(text: str, by_id: dict, replacement) -> str:
    """Replace source ids the model wrote into the prose ("D1 ระบุว่า…"); other codes stay.
    `replacement` is a string or a function of the id."""
    name = replacement if callable(replacement) else (lambda _: replacement)
    return _BARE_ID.sub(lambda m: name(m.group(0)) if m.group(0) in by_id else m.group(0), text)


def line_problem(line: str, ids: list[str], by_id: dict[str, Evidence]) -> str:
    """'' when the line may be shown. The same checks as the JSON path, applied per line."""
    plain = _named_sources(_LIST_PREFIX.sub("", _MARKER.sub("", line)).strip(), by_id, "")
    numbers = _numbers(without_document_ids(plain))
    if not ids:
        return "number without a source" if numbers else ""
    if any(i not in by_id for i in ids):
        return "unknown source id"
    # The source type first: a drone rule cited to a document needs the CAAT page whatever its
    # numbers, and the pipeline fetches that page when it sees this reason.
    if _is_aviation_regulation(plain) and any(not is_caat_url(by_id[i].url) for i in ids):
        return CAAT_PAGE_REQUIRED
    cited = " ".join(f"{by_id[i].content} {by_id[i].title}" for i in ids)
    if not numbers <= _numbers(cited):
        return "number not in the cited sources"
    problem = claim_inconsistency(plain, [], cited)
    if problem:
        return problem
    for i in ids:
        problem = table_inconsistency(without_document_ids(plain), [], by_id[i].content)
        if problem:
            return problem
    return ""


def caat_note(sources: list[Evidence]) -> str:
    """'' unless an answer line cites CAAT; names the news item when one is cited, so a dated
    announcement is never read as a standing rule whatever the model wrote."""
    caat = [item for item in sources if is_caat_url(item.url)]
    if not caat:
        return ""
    news = [item for item in caat if _NEWS_URL.search(item.url) or _NEWS_TITLE.search(item.title or "")]
    if not news:
        return CAAT_NOTE
    title = re.sub(r"\s+", " ", news[0].title or "ข่าว").strip()
    return CAAT_NEWS_NOTE.format(title=title if len(title) <= 60 else title[:57].rstrip() + "...")


def _plain_chat_text(text: str) -> str:
    """LINE shows markdown literally: drop **bold**/__bold__, heading hashes and code fences."""
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    return re.sub(r"^\s*```\w*\s*$", "", text, flags=re.MULTILINE)


def render(raw: str, evidence: list[Evidence], service_note: str = "") -> NaturalAnswer:
    text = _plain_chat_text((raw or "").strip())
    if not text or text.strip("` \n").upper() == NOT_FOUND:
        return NaturalAnswer(not_found=True)
    by_id = {e.id: e for e in evidence}
    result = NaturalAnswer()
    # Lines grouped into blocks (split by blank lines). A list item without its own marker belongs to
    # the marked line of its block, usually the heading above it ("…ดังนี้ [D1]" then "• สาร 320-640"):
    # it is checked against that source rather than dropped (2026-10-20 smoke: a complete, correct
    # 12-row list was removed because only the heading carried [D1]).
    blocks: list[list[str]] = [[]]
    for line in text.replace(NOT_FOUND, "").splitlines():
        if not line.strip():
            blocks.append([])
        elif not _MODEL_FOOTER.match(line):
            blocks[-1].append(line)
    for block in blocks:
        own = [_ids(line) for line in block]
        for index, line in enumerate(block):
            missing = _MISSING.match(line)
            if missing:
                result.gap = missing.group(1).strip()
                continue
            ids = own[index]
            if not ids:
                before = [found for found in own[:index] if found]
                after = [found for found in own[index + 1:] if found]
                ids = (before[-1] if before else after[0] if after else [])
            problem = line_problem(line, ids, by_id)
            if problem:
                result.dropped.append(f"{problem}: {line.strip()[:100]}")
            else:
                result.lines.append((line.strip() if own[index] else _MARKER.sub("", line).strip(), ids))
    if not any(ids for _, ids in result.lines):
        result.lines = []
        return result

    labels, references = {}, {}
    for _, ids in result.lines:
        for source_id in ids:
            item = by_id[source_id]
            key = (item.url,) if item.url else (item.source_file, item.page_number)
            if key not in references:
                references[key] = (len(references) + 1, item.citation)
            labels[source_id] = references[key][0]
    result.used_ids = list(labels)

    def document(source_id: str) -> str:
        return f"เอกสาร [{labels[source_id]}]" if source_id in labels else "เอกสาร"

    def numbered(line: str, ids: list[str]) -> str:
        # Only lines the model marked show a reference number; list items under a marked heading
        # were checked against the heading's source but stay uncluttered.
        if not _MARKER.search(line):
            return _named_sources(line.rstrip(), by_id, document)
        # Source ids belong only in markers; "ส่วน D1 ระบุ…" in the prose means nothing to a pilot.
        body = _named_sources(_MARKER.sub("", line).rstrip(), by_id, document)
        return f"{body} [{','.join(dict.fromkeys(str(labels[i]) for i in ids))}]"

    body = "\n".join(numbered(line, ids) for line, ids in result.lines)
    gaps = [g for g in (result.gap, DROPPED_GAP if result.dropped else "") if g]
    if gaps:
        body += "\n\n" + GAP_LABEL + "; ".join(gaps)
    if service_note:
        body += f"\n({service_note} ส่วนที่แสดงด้านบนตรวจกับแหล่งอ้างอิงแล้ว)"
    claims = [Claim(_MARKER.sub("", line), tuple(ids)) for line, ids in result.lines if ids]
    if needs_chemical_note(claims, [by_id[i] for i in result.used_ids]):
        body += f"\n\n{CHEMICAL_NOTE}"
    note = caat_note([by_id[i] for i in result.used_ids])
    if note:
        body += f"\n\n{note}"
    reference_list = "\n".join(f"[{number}] {citation}" for number, citation in references.values())
    result.text = f"{body}\n\nแหล่งอ้างอิง:\n{reference_list}"
    if len(result.text) > MAX_ANSWER_CHARS:
        # A chat message has a hard size limit; keep whole lines and say what was cut.
        while result.lines and len(result.text) > MAX_ANSWER_CHARS:
            result.lines.pop()
            return render("\n".join(line for line, _ in result.lines) + "\nยังไม่พบข้อมูล: คำตอบยาวเกินข้อความแชท",
                          evidence, service_note)
    return result
