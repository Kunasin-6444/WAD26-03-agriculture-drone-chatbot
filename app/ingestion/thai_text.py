"""Repair Thai text from PDF text layers.

Several of the source PDFs (PowerPoint exports) have a broken text layer: SARA AM
is split into a base consonant, a space and a bare SARA AA ("ท ากิจกรรม"), or the
glyph for SARA AA is mapped to SARA AM ("ภำพ" for "ภาพ", with the real SARA AM
written as " ำ"). The visible page is fine; only the extracted text is wrong, which
hurts BM25/n-gram retrieval and makes the model's quotes disagree with the evidence.

Only unambiguous patterns are repaired. A Thai word cannot begin with SARA AA, so a
space before it always marks a lost SARA AM.
"""
from __future__ import annotations

import re

_CONSONANT = "ก-ฮ"
_TONE = "่-๋"
_MARK = ""  # private-use placeholder, never present in the extracted text

# Convention A: "ท า" / "น ้า" -> "ทำ" / "น้ำ"
_SPACE_AA = re.compile(rf"([{_CONSONANT}])[ \t]+([{_TONE}]?)า")
# Convention B (SARA AM written as " ำ", SARA AA written as "ำ")
_SPACE_AM = re.compile(rf"([{_CONSONANT}{_TONE}])[ \t]+ำ")
_NIKHAHIT_AA = re.compile(r"ํา")


def repair_sara_am(text: str) -> str:
    if not text:
        return text
    fixed = _NIKHAHIT_AA.sub("ำ", text)
    if _SPACE_AM.search(fixed):
        # Convention B: protect real SARA AM, then turn the remaining ำ back into า.
        fixed = _SPACE_AM.sub(lambda m: m.group(1) + _MARK, fixed)
        fixed = fixed.replace("ำ", "า").replace(_MARK, "ำ")
    fixed = _SPACE_AA.sub(lambda m: m.group(1) + m.group(2) + "ำ", fixed)
    return fixed


# A space before SARA AA ("น้ า", "ท า") or before SARA AM: the text layer lost a SARA AM.
_DAMAGE = re.compile(rf"[{_CONSONANT}][{_TONE}]?[ \t]+[{_TONE}]?[าำ]")


def thai_layer_damaged(text: str) -> bool:
    """True when the text layer shows the lost-SARA-AM damage ``repair_sara_am`` describes.

    Table cells are kept verbatim, so such a table must not replace what vision read."""
    return bool(_DAMAGE.search(text or ""))
