from __future__ import annotations

import re

_CITATION_LABEL = r"(?:แหล่งอ้างอิง|อ้างอิง|แหล่งที่มา|แหล่งข้อมูล)"
_PAREN_CITATION_RE = re.compile(rf"\(\s*{_CITATION_LABEL}\s*:\s*([^()]+?)\s*\)")
_LINE_CITATION_RE = re.compile(rf"^[ \t]*\(?\s*{_CITATION_LABEL}\s*:\s*(.+?)\)?[ \t]*$", re.MULTILINE)


def format_response_layout(text: str, default_citation: str = "") -> str:
    """
    Ensures clean, consistent, and readable message layout for LINE chat:
    1. Strips unrendered Markdown (**bold**, *italic*, ### headers, backticks).
    2. Converts bullet indicators (*, -) into consistent bullet circles (•) and ensures
       each bullet point starts on its own line.
    3. Collects every citation ('(แหล่งอ้างอิง: ...)', 'แหล่งข้อมูล: ...', inline or at the end),
       de-duplicates them and merges them into ONE line at the very bottom, preceded by a blank line (\\n\\n).
    4. If the LLM omitted the citation on a grounded answer, uses default_citation as a safety guardrail.
    """
    if not text or not text.strip():
        return ""

    raw = text.strip()

    # Short abstain answers without citations can be returned cleanly
    if raw.startswith("ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้") and len(raw) < 120:
        return raw
    if raw.startswith("กรุณาระบุคำถาม") and len(raw) < 100:
        return raw

    # 1. Convert markdown asterisk bullets (* ) to bullet circles (• )
    cleaned = re.sub(r"^\*\s+", "• ", raw, flags=re.MULTILINE)

    # 2. Strip Markdown headers, bold, and italic markup
    cleaned = re.sub(r"^#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    # Remove any dangling or unpaired Markdown tokens
    cleaned = cleaned.replace("**", "").replace("###", "").replace("##", "")

    # 2. Collect every citation (end, inline, or broken across lines) and merge them into one
    citations: list[str] = []

    def _collect(match: re.Match) -> str:
        cite = re.sub(r"\s+", " ", match.group(1)).strip().rstrip(".")
        if cite and cite not in citations:
            citations.append(cite)
        return ""

    body = _PAREN_CITATION_RE.sub(_collect, cleaned)
    body = _LINE_CITATION_RE.sub(_collect, body)
    body = re.sub(r"\(\s*\)", "", body)
    body = re.sub(r"[ \t]+$", "", body, flags=re.MULTILINE).strip()
    citation = f"(แหล่งอ้างอิง: {' / '.join(citations)})" if citations else ""

    # 3. Standardize bullet points in the body
    # Convert asterisk bullets at line start to '• ', while keeping dashes (-) for sub-items
    body = re.sub(r"^\*\s+", "• ", body, flags=re.MULTILINE)
    # Ensure inline bullet points are split onto a fresh newline: e.g. "ประเด็น 1 • ประเด็น 2" -> "ประเด็น 1\n• ประเด็น 2"
    body = re.sub(r"([^\n])\s*•\s*", r"\1\n• ", body)

    # 4. Normalize consecutive blank lines (maximum 1 blank line between paragraphs)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    # 5. Recombine body and citation with strict separation
    final_citation = citation
    if not final_citation and default_citation:
        # Only inject default citation if response is grounded (not an abstain message)
        if "ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้" not in raw and not raw.startswith("กรุณาระบุคำถาม"):
            final_citation = default_citation.strip()

    if final_citation:
        if not final_citation.startswith("(") and "\n" not in final_citation:
            final_citation = f"({final_citation})"
        return f"{body}\n\n{final_citation}".strip()

    return body
