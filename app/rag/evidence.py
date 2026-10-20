"""Evidence packing and strict, server-owned citations."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from app.rag.claim_consistency import claim_inconsistency
from app.rag.source_policy import canonical_document_id, is_caat_url, is_excluded_document, requested_document_ids, valid_web_url, without_document_ids
from app.rag.crag_grader import is_caat_air_law_or_airspace_topic
from app.rag.table_grounding import table_inconsistency

ABSTAIN_MESSAGE = "ยังไม่พบหลักฐานเพียงพอจากเอกสารและเว็บไซต์ จึงไม่สามารถยืนยันคำตอบได้ครับ"
CONTEXT_CHAR_BUDGET = 14000
MAX_BODY_CHARS = 1800
MAX_ANSWER_CHARS = 4200
MAX_CLAIMS = 8
MAX_INTRO_CHARS = 200
# Added to missing_aspects when the verifier dropped claims. It names no topic, so it is not
# something a web search can find (crag_service must not search the web for it).
REJECTED_CLAIMS_ASPECT = "บางประเด็นของคำถามยังตรวจสอบหลักฐานไม่ได้"
# The owner's review (2026-10-19): chemical-rate and diagnosis answers must tell the reader to
# check with an expert. Appended by the server, so it never depends on the model remembering.
CHEMICAL_NOTE = ("หมายเหตุ: ข้อมูลนี้สรุปจากเอกสารอ้างอิงเพื่อประกอบการตัดสินใจเท่านั้น "
                 "ก่อนใช้สารเคมีหรือวินิจฉัยโรคจริง ควรอ่านฉลากผลิตภัณฑ์และปรึกษาผู้เชี่ยวชาญหรือเจ้าหน้าที่เกษตร")
# Two independent signals: a dose/rate stated in the answer (any document), or a cited document
# whose whole subject is chemicals/diagnosis (document_topics.json, owner-editable).
_CHEMICAL_RATE = re.compile(r"(?:กรัม|ซีซี|มล\.?|มิลลิลิตร|cc|ml)\s*(?:สารออกฤทธิ์)?\s*(?:/|ต่อ)\s*(?:ไร่|น้ำ|ลิตร)"
                            r"|สารออกฤทธิ์|วัตถุอันตราย", re.IGNORECASE)
ADVISORY_TOPICS = {"chemical", "diagnosis"}
DOCUMENT_TOPICS_FILE = Path(__file__).with_name("document_topics.json")


@dataclass(frozen=True)
class Evidence:
    id: str
    content: str
    source_file: str = ""
    page_number: str = ""
    url: str = ""
    title: str = ""
    page_from: str = ""
    page_end: str = ""

    @property
    def citation(self) -> str:
        if not self.url:
            first, last = self.page_from or self.page_number, self.page_end or self.page_number
            pages = first if first == last else f"{first}–{last}"
            return f"{self.source_file}, หน้า {pages}"
        # Titles are untrusted display metadata. They must not inject extra links or
        # reference lines; the URL always comes unchanged from the fetched source.
        title = re.sub(r"https?://\S+", "", self.title, flags=re.IGNORECASE)
        title = " ".join(re.sub(r"[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]", " ", title).split())[:120]
        return f"{title}\n{self.url}" if title else self.url


@dataclass(frozen=True)
class Claim:
    text: str
    source_ids: tuple[str, ...]
    quotes: tuple[tuple[str, str], ...] = ()


@dataclass
class GroundedResult:
    status: Literal["sufficient", "partial", "insufficient"] = "insufficient"
    claims: list[Claim] = field(default_factory=list)
    missing_aspects: list[str] = field(default_factory=list)
    reason: str = ""
    is_caat_topic: bool = False
    llm_unavailable: bool = False
    intro: str = ""
    error_code: str = ""


def document_evidence(context: str) -> list[Evidence]:
    """Parse legacy display fixtures only; live retrieval uses document_page_evidence."""
    evidence = []
    for block in re.split(r"\[แหล่งข้อมูล\s+\d+\]\s*", context):
        file = re.search(r"^ไฟล์:\s*([^\n]+)", block, re.MULTILINE)
        page = re.search(r"^หน้า:\s*([^\n]+)", block, re.MULTILINE)
        content = re.search(r"^เนื้อหา:\s*([\s\S]+)", block, re.MULTILINE)
        if not (file and page and content):
            continue
        filename, number = file[1].strip(), page[1].strip()
        if is_excluded_document(filename) or not number.isdigit() or int(number) < 1:
            continue
        evidence.append(Evidence(f"D{len(evidence) + 1}", content[1].strip(), filename, number))
    return evidence


def document_page_evidence(pages: list[dict]) -> list[Evidence]:
    """Keep server-owned page metadata separate from untrusted document text."""
    evidence = []
    for page in pages:
        filename = page.get("source_file", "")
        number = str(page.get("page_number", ""))
        content = page.get("content", "")
        if (not isinstance(filename, str) or not filename.strip() or is_excluded_document(filename)
                or not number.isdigit() or int(number) < 1
                or not isinstance(content, str) or not content.strip()):
            continue
        first, last = str(page.get("page_from") or number), str(page.get("page_end") or number)
        if not (first.isdigit() and last.isdigit() and 1 <= int(first) <= int(number) <= int(last)):
            continue
        evidence.append(Evidence(f"D{len(evidence) + 1}", content.strip(), filename, number,
                                 page_from=first if first != number else "",
                                 page_end=last if last != number else ""))
    return evidence


def pack_evidence(evidence: list[Evidence], budget: int = CONTEXT_CHAR_BUDGET,
                  required_ids: set[str] | None = None) -> list[Evidence]:
    """Keep complete sources; reserve room for both PDF and web when combined."""
    if budget < 1:
        return []
    packed, used_ids = [], set()
    for item in evidence:
        if required_ids and item.id in required_ids and item.id not in used_ids:
            size = len(json.dumps(item.__dict__, ensure_ascii=False))
            if size > budget or not item.content.strip():
                return []  # cannot retain the already validated sources within this budget
            packed.append(item)
            used_ids.add(item.id)
            budget -= size
    candidates = [e for e in evidence if e.id not in used_ids]
    groups = [[e for e in candidates if not e.url], [e for e in candidates if e.url]]
    active = [group for group in groups if group]
    for group in active:
        remaining = budget // len(active)
        for item in group:
            size = len(json.dumps(item.__dict__, ensure_ascii=False))
            if item.id in used_ids or not item.content.strip() or size > remaining:
                continue
            packed.append(item)
            used_ids.add(item.id)
            remaining -= size
    return packed


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


_ELLIPSIS = re.compile(r"\.{3,}|…")
# SARA I..PHINTHU and MAI TAI KHU..YAMAKKAN: a doubled one is an OCR/extraction glitch.
_DOUBLED_MARK = re.compile("([ัิ-ฺ็-๎])\\1+")


def _canonical(text: str) -> str:
    """Whitespace/table-separator/OCR-glitch tolerant form used only to compare a quote."""
    text = text.replace("ํา", "ำ")
    text = re.sub(r"[\s|​‌‍﻿]+", "", text)
    return _DOUBLED_MARK.sub(r"\1", text)


def _quote_supported(quote: str, content: str) -> bool:
    """True when every fragment of the quote appears, in order, in the evidence text.

    Still a literal-substring test; it ignores only layout (spaces, ``|`` between table
    cells), doubled vowel marks and the model eliding text with ``...``. Any different word
    or number still fails.
    """
    haystack = _canonical(content)
    fragments = [_canonical(part) for part in _ELLIPSIS.split(quote)]
    fragments = [part for part in fragments if len(part) >= 3]
    if not fragments:
        return False
    position = 0
    for part in fragments:
        found = haystack.find(part, position)
        if found < 0:
            return False
        position = found + len(part)
    return True


def _numbers(text: str) -> set[Decimal]:
    return {Decimal(value.replace(",", "")) for value in re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", text)}


def _parse_claim(item: dict, by_id: dict[str, Evidence]) -> Claim:
    """Validate one independent fact; a rejected fact never reaches the renderer."""
    text = item.get("text", "")
    citations = item.get("evidence", [])
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Invalid claim text")
    if len(text) > 400:
        raise ValueError("Claim exceeds 400 characters; split independent facts")
    if "http" in text.lower() or ".pdf" in text.lower() or "แหล่งอ้างอิง" in text:
        raise ValueError("Inline citation in claim; use evidence metadata only")
    if not isinstance(citations, list) or not citations or len(citations) > 4:
        raise ValueError("Missing claim evidence")
    ids, quotes = [], []
    for citation in citations:
        source_id, quote = citation.get("source_id"), citation.get("quote")
        if not isinstance(quote, str):
            quote = next((citation[k] for k in ("text", "content") if isinstance(citation.get(k), str)), None)
        if source_id not in by_id or not isinstance(quote, str) or len(quote.strip()) < 3 or len(quote) > 800:
            raise ValueError("Invalid citation")
        if not _quote_supported(quote, by_id[source_id].content):
            raise ValueError("Quote not in supplied evidence")
        ids.append(source_id)
        quotes.append(quote)
    cited_content = " ".join(by_id[source_id].content for source_id in dict.fromkeys(ids))
    cited_documents = {canonical_document_id(by_id[i].source_file) for i in ids if by_id[i].source_file}
    if requested_document_ids(text) - cited_documents:
        raise ValueError("Claim names a different document from its citation")
    if _is_aviation_regulation(text) and any(not is_caat_url(by_id[i].url) for i in ids):
        raise ValueError("Regulatory claims require fetched CAAT sources")
    if not _numbers(without_document_ids(text)).issubset(_numbers(" ".join(quotes) + " " + cited_content)):
        raise ValueError("Unsupported numeric claim")
    cited_text = " ".join(f"{by_id[i].content} {by_id[i].title} {by_id[i].url} {by_id[i].source_file}" for i in dict.fromkeys(ids))
    problem = claim_inconsistency(text, quotes, cited_text)
    if problem:
        raise ValueError(f"Claim inconsistent with cited evidence ({problem})")
    for source_id in dict.fromkeys(ids):
        source_quotes = [quote for current_id, quote in zip(ids, quotes) if current_id == source_id]
        problem = table_inconsistency(without_document_ids(text), source_quotes, by_id[source_id].content)
        if problem:
            raise ValueError(f"Claim inconsistent with cited table ({problem})")
    return Claim(text.strip(), tuple(dict.fromkeys(ids)), tuple(zip(ids, quotes)))


_AVIATION_CONTEXT = re.compile(r"โดรน|อากาศยาน|บิน|น่านฟ้า|uas|uav|caat|กพท", re.IGNORECASE)


def _is_aviation_regulation(text: str) -> bool:
    """CAAT governs flying. Generic legal words ("กฎหมาย", "พ.ร.บ.", "ขึ้นทะเบียน") also describe
    pesticide law, so a claim needs aviation context before only CAAT pages may support it
    (2026-10-20: a glyphosate "ควบคุมการใช้" claim from the KB table was rejected as drone law)."""
    if not _AVIATION_CONTEXT.search(text):
        return False
    if is_caat_air_law_or_airspace_topic(text):
        return True
    # Required third-party cover is a CAAT rule; a premium in a cost table is not (2026-10-20: a
    # news site's "ไม่น้อยกว่า 1 ล้านบาท" without the weight condition passed as an answer).
    return "ประกัน" in text and bool(re.search(r"วงเงิน|คุ้มครอง", text))


def parse_grounded_result(raw: str, evidence: list[Evidence]) -> GroundedResult:
    """Reject invalid IDs/quotes/numbers and incomplete JSON; never repair facts."""
    try:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        data = json.loads(cleaned)
        if not isinstance(data, dict) or data.get("status") not in {"sufficient", "partial", "insufficient"}:
            raise ValueError("Invalid status")
        if type(data.get("is_caat_topic", False)) is not bool:
            raise ValueError("Invalid CAAT flag")
        missing = data.get("missing_aspects", [])
        if not isinstance(missing, list) or any(not isinstance(x, str) or not x.strip() or len(x) > 200 for x in missing) or len(missing) > 8:
            raise ValueError("Invalid missing aspects")
        items = data.get("claims", [])
        if not isinstance(items, list) or len(items) > MAX_CLAIMS:
            raise ValueError("Invalid claims")
        by_id = {e.id: e for e in evidence}
        if len(by_id) != len(evidence) or any(e.url and not valid_web_url(e.url) for e in evidence):
            raise ValueError("Invalid evidence metadata")
        claims, rejected = [], []
        for item in items:
            try:
                claims.append(_parse_claim(item, by_id))
            except (ValueError, TypeError, AttributeError, KeyError) as exc:
                rejected.append(str(exc))
        if rejected and not claims:
            raise ValueError("; ".join(rejected)[:250])
        if sum(len(c.text) + 4 for c in claims) > MAX_BODY_CHARS:
            raise ValueError("Answer exceeds concise body limit")
        status = data["status"]
        if status == "sufficient" and (not claims or missing):
            raise ValueError("Sufficiency contradicts answer")
        if status == "insufficient" and claims:
            raise ValueError("Insufficient response contains claims")
        if status == "partial" and (not claims or not missing):
            raise ValueError("Partial answer must identify missing evidence")
        reason = str(data.get("reason", ""))[:300]
        if rejected:
            status = "partial"
            missing = list(missing) + [REJECTED_CLAIMS_ASPECT]
            reason = "Some claims rejected: " + "; ".join(rejected)[:250]
        return GroundedResult(status, claims, [x.strip() for x in missing], reason, data.get("is_caat_topic", False),
                              intro=_intro(data.get("intro", "")))
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        return GroundedResult(reason=f"Evidence validation failed: {exc}")


def _intro(value) -> str:
    """A lead-in sentence carries no facts of its own: no numbers, no links. A bad one is
    dropped, never a reason to lose the verified claims."""
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    if len(text) > MAX_INTRO_CHARS or re.search(r"[0-9๐-๙]|https?://|www\.", text, re.IGNORECASE):
        return ""
    return text


@lru_cache(maxsize=1)
def document_topics() -> dict[str, frozenset[str]]:
    data = json.loads(DOCUMENT_TOPICS_FILE.read_text(encoding="utf-8"))
    return {doc_id: frozenset(topics) for doc_id, topics in data.items() if not doc_id.startswith("_")}


def needs_chemical_note(claims: list[Claim], evidence: list[Evidence]) -> bool:
    if any(_CHEMICAL_RATE.search(claim.text) for claim in claims):
        return True
    # The cited source counts too: a claim naming only the substance still points at a table whose
    # header carries the dose unit ("อัตราสารที่ใช้ (กรัมสารออกฤทธิ์/ไร่)"). Only documents: a long
    # web page mentions anything (a CAAT guide on insurance names "วัตถุอันตราย" cargo, 2026-10-20).
    if any(_CHEMICAL_RATE.search(item.content) for item in evidence if not item.url):
        return True
    topics = document_topics()
    return any(topics.get(canonical_document_id(item.source_file), frozenset()) & ADVISORY_TOPICS
               for item in evidence if item.source_file)


def merge_verified_partial(initial: GroundedResult, final: GroundedResult) -> GroundedResult:
    """A repair or web generation cannot erase previously verified facts."""
    if initial.status != "partial":
        return final
    if not final.claims:
        return GroundedResult(initial.status, list(initial.claims), list(initial.missing_aspects), initial.reason,
                              initial.is_caat_topic, initial.llm_unavailable or final.llm_unavailable, initial.intro,
                              final.error_code or initial.error_code)
    claims = list(initial.claims)
    for claim in final.claims:
        compact = "".join(claim.text.split())
        if not any(compact in "".join(old.text.split()) for old in claims):
            claims.append(claim)
    if len(claims) > MAX_CLAIMS or sum(len(c.text) + 4 for c in claims) > MAX_BODY_CHARS:
        return initial
    return GroundedResult(final.status, claims, list(final.missing_aspects), final.reason,
                          final.is_caat_topic, final.llm_unavailable, initial.intro or final.intro, final.error_code)


def render_grounded_answer(result: GroundedResult, evidence: list[Evidence], service_note: str = "") -> str:
    """``service_note`` explains a service failure (timeout, quota…) behind the missing part."""
    if not result.claims:
        return ABSTAIN_MESSAGE
    by_id = {e.id: e for e in evidence}
    used = list(dict.fromkeys(source_id for claim in result.claims for source_id in claim.source_ids))
    if any(source_id not in by_id for source_id in used):
        return ABSTAIN_MESSAGE
    # Multiple chunks of one fetched page share a reference. Different paths on
    # the same host stay distinct; do not canonicalize away queries/fragments.
    labels, references_by_key = {}, {}
    for source_id in used:
        item = by_id[source_id]
        key = (item.url,) if item.url else (item.source_file, item.page_number)
        if key not in references_by_key:
            references_by_key[key] = (len(references_by_key) + 1, item.citation)
        labels[source_id] = references_by_key[key][0]
    body = "\n".join(f"• {claim.text} [{','.join(dict.fromkeys(str(labels[s]) for s in claim.source_ids))}]" for claim in result.claims)
    if result.intro:
        body = f"{result.intro}\n{body}"
    if result.status == "partial":
        body += "\n\nยังยืนยันไม่ได้: " + "; ".join(result.missing_aspects)
    if service_note:
        # Directly under the gap it explains, and says the shown part is verified, so the
        # reader does not take the whole answer as unreliable.
        body += f"\n({service_note} ส่วนที่แสดงด้านบนตรวจกับแหล่งอ้างอิงแล้ว)"
    if needs_chemical_note(result.claims, [by_id[source_id] for source_id in used]):
        body += f"\n\n{CHEMICAL_NOTE}"
    references = "\n".join(f"[{number}] {citation}" for number, citation in references_by_key.values())
    answer = f"{body}\n\nแหล่งอ้างอิง:\n{references}"
    return answer if len(answer) <= MAX_ANSWER_CHARS else ABSTAIN_MESSAGE
