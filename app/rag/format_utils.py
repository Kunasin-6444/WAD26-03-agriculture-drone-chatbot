from __future__ import annotations

import re


def format_response_layout(text: str, default_citation: str = "") -> str:
    """
    Ensures clean, consistent, and readable message layout for LINE chat:
    1. Strips unrendered Markdown (**bold**, *italic*, ### headers, backticks).
    2. Converts bullet indicators (*, -) into consistent bullet circles (•) and ensures
       each bullet point starts on its own line.
    3. Guarantees that citations (e.g. '(แหล่งอ้างอิง: ...)' or '(อ้างอิง: ...)')
       are cleanly isolated on their own line at the very bottom, preceded by a blank line (\\n\\n).
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

    # 2. Extract isolated citation block from the text (supports parenthesized and unparenthesized)
    citation = ""
    body = cleaned

    # Try matching parenthesized citation at the end: (แหล่งอ้างอิง: ...) or (อ้างอิง: ...) or (แหล่งที่มา: ...)
    paren_match = re.search(
        r"(\((?:แหล่งอ้างอิง|อ้างอิง|แหล่งที่มา):\s*[\s\S]+?\))\s*$",
        cleaned,
    )
    if paren_match:
        citation = paren_match.group(1).strip()
        body = cleaned[: paren_match.start()].strip()
    else:
        # Try matching unparenthesized citation block at the end
        unparen_match = re.search(
            r"((?:แหล่งอ้างอิง|อ้างอิง|แหล่งที่มา):\s*[\s\S]+)$",
            cleaned,
        )
        if unparen_match:
            raw_cite = unparen_match.group(1).strip()
            # If it's a simple single line or URL list, wrap in parentheses if needed or format nicely
            if not raw_cite.startswith("(") and "\n" not in raw_cite:
                citation = f"({raw_cite})"
            else:
                citation = raw_cite
            body = cleaned[: unparen_match.start()].strip()

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
