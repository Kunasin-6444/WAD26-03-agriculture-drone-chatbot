"""Evidence packing and strict, server-owned citations."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from app.rag.source_policy import is_excluded_document

ABSTAIN_MESSAGE = "ยังไม่พบหลักฐานเพียงพอจากเอกสารและเว็บไซต์ จึงไม่สามารถยืนยันคำตอบได้ครับ"
CONTEXT_CHAR_BUDGET = 14000
MAX_BODY_CHARS = 1800
MAX_ANSWER_CHARS = 4200
MAX_CLAIMS = 8


@dataclass(frozen=True)
class Evidence:
    id: str
    content: str
    source_file: str = ""
    page_number: str = ""
    url: str = ""
    title: str = ""

    @property
    def citation(self) -> str:
        return self.url if self.url else f"{self.source_file}, หน้า {self.page_number}"


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


def document_evidence(context: str) -> list[Evidence]:
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


def pack_evidence(evidence: list[Evidence], budget: int = CONTEXT_CHAR_BUDGET) -> list[Evidence]:
    """Keep complete sources; reserve room for both PDF and web when combined."""
    if budget < 1:
        return []
    groups = [[e for e in evidence if not e.url], [e for e in evidence if e.url]]
    active = [group for group in groups if group]
    packed, used_ids = [], set()
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


def _numbers(text: str) -> set[Decimal]:
    return {Decimal(value.replace(",", "")) for value in re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", text)}


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
        claims = []
        for item in items:
            text = item.get("text", "")
            citations = item.get("evidence", [])
            if not isinstance(text, str) or not text.strip() or len(text) > 400 or "http" in text.lower() or ".pdf" in text.lower() or "แหล่งอ้างอิง" in text:
                raise ValueError("Invalid claim text")
            if not isinstance(citations, list) or not citations or len(citations) > 4:
                raise ValueError("Missing claim evidence")
            ids, quotes = [], []
            for citation in citations:
                source_id, quote = citation.get("source_id"), citation.get("quote")
                if source_id not in by_id or not isinstance(quote, str) or len(quote.strip()) < 3 or len(quote) > 800:
                    raise ValueError("Invalid citation")
                if _normalized(quote) not in _normalized(by_id[source_id].content):
                    raise ValueError("Quote not in supplied evidence")
                ids.append(source_id)
                quotes.append(quote)
            numbers = _numbers(text)
            # A number must appear somewhere in the cited evidence (e.g. the same table's
            # column header), not necessarily inside the model's trimmed quote span —
            # requiring the latter rejected correct claims like "...1,500 ml for 3 nozzles"
            # where "3" comes from the table header, not the narrow row the model quoted.
            cited_content = " ".join(by_id[source_id].content for source_id in dict.fromkeys(ids))
            quoted_numbers = _numbers(" ".join(quotes) + " " + cited_content)
            if not numbers.issubset(quoted_numbers):
                raise ValueError("Unsupported numeric claim")
            claims.append(Claim(text.strip(), tuple(dict.fromkeys(ids)), tuple(zip(ids, quotes))))
        if sum(len(c.text) + 4 for c in claims) > MAX_BODY_CHARS:
            raise ValueError("Answer exceeds concise body limit")
        status = data["status"]
        if status == "sufficient" and (not claims or missing):
            raise ValueError("Sufficiency contradicts answer")
        if status == "insufficient" and claims:
            raise ValueError("Insufficient response contains claims")
        if status == "partial" and (not claims or not missing):
            raise ValueError("Partial answer must identify missing evidence")
        return GroundedResult(status, claims, [x.strip() for x in missing], str(data.get("reason", ""))[:300], data.get("is_caat_topic", False))
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        return GroundedResult(reason=f"Evidence validation failed: {exc}")


def render_grounded_answer(result: GroundedResult, evidence: list[Evidence]) -> str:
    if not result.claims:
        return ABSTAIN_MESSAGE
    by_id = {e.id: e for e in evidence}
    used = list(dict.fromkeys(source_id for claim in result.claims for source_id in claim.source_ids))
    if any(source_id not in by_id for source_id in used):
        return ABSTAIN_MESSAGE
    labels = {source_id: index for index, source_id in enumerate(used, 1)}
    body = "\n".join(f"• {claim.text} [{','.join(str(labels[s]) for s in claim.source_ids)}]" for claim in result.claims)
    if result.status == "partial":
        body += "\n\nยังยืนยันไม่ได้: " + "; ".join(result.missing_aspects)
    references = "\n".join(f"[{labels[s]}] {by_id[s].citation}" for s in used)
    answer = f"{body}\n\nแหล่งอ้างอิง:\n{references}"
    return answer if len(answer) <= MAX_ANSWER_CHARS else ABSTAIN_MESSAGE
