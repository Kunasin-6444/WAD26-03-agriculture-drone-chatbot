"""Deterministic claim <-> cited-evidence consistency checks.

``evidence.parse_grounded_result`` already proves that a quote is a literal substring of the
cited evidence and that every number in a claim exists in it. Neither proves the claim
*means* what the quote says: the model can quote a real table row and attach the wrong
nozzle colour, crop, weed class or unit to it. These checks close that gap for the label
families where a swap changes the agronomic advice, without another LLM call:

- units          claim "500 ลิตร" while the evidence states its volumes in "ml"
- Latin terms    claim names "glyphosate"/"GSD" that the evidence never mentions
- crops          claim says อ้อย, evidence/quote is about ข้าวโพด
- nozzle colours claim says พัดส้ม, the quote it cites is the พัดน้ำเงิน row
- weed class     claim says ใบแคบ, the quote says ใบแคบและกว้าง (or only ใบกว้าง)

They only ever *reject* (never rewrite) and only compare labels the claim itself states, so a
claim that names none of these is unaffected. Known limit: a quote that spans two table rows
still lets a claim pick the wrong row's label; that needs row-level parsing, not term checks.
"""
from __future__ import annotations

import re

from app.rag.source_policy import SUPPORTED_CROPS

# canonical unit -> spellings. Claim side is only checked when the unit directly follows a digit.
_UNITS: dict[str, tuple[str, ...]] = {
    "ml": ("ml", "มล.", "มิลลิลิตร", "cc", "ซีซี"),
    "l": ("l", "ลิตร"),
    "g": ("g", "กรัม"),
    "kg": ("kg", "กก.", "กิโลกรัม"),
    "m": ("m", "ม.", "เมตร"),
    "cm": ("cm", "ซม.", "เซนติเมตร"),
    "mm": ("mm", "มม.", "มิลลิเมตร"),
    "km": ("km", "กม.", "กิโลเมตร"),
    "rai": ("ไร่",),
    "ha": ("ha", "เฮกตาร์"),
    "pct": ("%", "เปอร์เซ็นต์", "เปอร์เซนต์"),
    "rpm": ("rpm", "รอบ/นาที", "รอบต่อนาที", "รอบ"),
    "sec": ("วินาที",),
    "min": ("นาที",),
    "hr": ("ชั่วโมง", "ชม."),
    "deg": ("องศา", "°"),
}
# Units of one dimension are mutually exclusive: a claim may not use "l" when the evidence
# measures that quantity in "ml". Tables often leave units implicit (a bare "1.0 | 2.8"
# under "ความสูง | หน้ากว้าง"), so a unit with no same-dimension unit in the evidence is not
# rejected: there is nothing to contradict.
_DIMENSIONS = (("ml", "l"), ("g", "kg"), ("m", "cm", "mm", "km"), ("rai", "ha"), ("sec", "min", "hr"))
_ALIAS_TO_UNIT = {alias: unit for unit, aliases in _UNITS.items() for alias in aliases}
_ALTERNATION = "|".join(re.escape(a) for a in sorted(_ALIAS_TO_UNIT, key=len, reverse=True))
_CLAIM_UNIT = re.compile(rf"\d\s*({_ALTERNATION})(?![A-Za-z])", re.IGNORECASE)


def _alias_pattern(alias: str) -> str:
    if re.fullmatch(r"[A-Za-z]+", alias):
        return rf"(?<![A-Za-z]){re.escape(alias)}(?![A-Za-z])"
    return re.escape(alias)


_EVIDENCE_UNIT = {unit: re.compile("|".join(_alias_pattern(a) for a in aliases), re.IGNORECASE)
                  for unit, aliases in _UNITS.items()}

_LATIN_TERM = re.compile(r"[A-Za-z][A-Za-z0-9\-]{2,}")
_NOZZLE = re.compile(r"พัด(?:อัด)?(?:น้ำเงิน|น้ำตาล|ส้ม|แดง|เหลือง|ฟ้า|เขียว|ม่วง|ขาว|เทา|ดำ)")
# ISO nozzle colour codes are often printed in English ("01 | Orange"); a Thai claim of the
# same colour is a translation, not an addition.
_NOZZLE_ENGLISH = {"ส้ม": "orange", "แดง": "red", "เหลือง": "yellow", "น้ำเงิน": "blue", "ฟ้า": "light blue",
                   "น้ำตาล": "brown", "เขียว": "green", "ม่วง": "purple", "ขาว": "white", "ดำ": "black"}
_NOZZLE_ENGLISH_RE = {th: re.compile(rf"(?<![a-z]){en}(?![a-z])") for th, en in _NOZZLE_ENGLISH.items()}
_WEED_CLASS = re.compile(r"ใบ(?:แคบ|กว้าง)(?:(?:และ|หรือ|,|/|-)(?:ประเภท)?(?:ใบ)?(?:แคบ|กว้าง))*")
_CROPS_LONGEST_FIRST = sorted(SUPPORTED_CROPS, key=len, reverse=True)


def _flat(text: str) -> str:
    """Layout-insensitive form (same idea as evidence._canonical) used only for label lookup."""
    return re.sub(r"[\s|​‌‍﻿]+", "", text.replace("ํา", "ำ"))


def _units(text: str) -> set[str]:
    return {unit for unit, pattern in _EVIDENCE_UNIT.items() if pattern.search(text)}


def _claim_units(text: str) -> set[str]:
    return {_ALIAS_TO_UNIT[m.group(1).lower()] for m in _CLAIM_UNIT.finditer(text)}


def _crops(flat: str) -> set[str]:
    found = set()
    for crop in _CROPS_LONGEST_FIRST:  # "ข้าวโพด" must not also count as "ข้าว"
        if crop in flat:
            found.add(crop)
            flat = flat.replace(crop, "\0")
    return found


def _nozzles(raw: str) -> set[str]:
    """Nozzle colour labels stated in Thai ("พัดส้ม") or by their English colour word."""
    found = set(_NOZZLE.findall(_flat(raw)))
    lowered = raw.lower()
    for thai, pattern in _NOZZLE_ENGLISH_RE.items():
        if pattern.search(lowered):
            found |= {f"พัด{thai}", f"พัดอัด{thai}"}
    return found


def _weed_groups(flat: str) -> set[frozenset[str]]:
    return {frozenset(re.findall(r"แคบ|กว้าง", m.group(0))) for m in _WEED_CLASS.finditer(flat)}


def claim_inconsistency(claim_text: str, quotes: list[str] | tuple[str, ...], cited_content: str) -> str:
    """Return a short reason when the claim states a label its evidence contradicts, else ''."""
    quote_text = " ".join(quotes)
    evidence_text = f"{cited_content} {quote_text}"
    claim_flat, quote_flat, evidence_flat = _flat(claim_text), _flat(quote_text), _flat(evidence_text)

    evidence_units = _units(evidence_text)
    for dimension in _DIMENSIONS:
        stated = set(dimension) & _claim_units(claim_text)
        present = set(dimension) & evidence_units
        if stated and present and not stated & present:
            return f"unit conflicts with evidence: claim {sorted(stated)}, evidence {sorted(present)}"

    evidence_words = {w.lower() for w in _LATIN_TERM.findall(evidence_text)}
    for word in _LATIN_TERM.findall(claim_text):
        if word.lower() not in evidence_words and word.lower() not in _ALIAS_TO_UNIT:
            return f"term not in evidence: {word}"

    claimed_nozzles = set(_NOZZLE.findall(claim_flat))
    in_quote, in_evidence = _nozzles(quote_text), _nozzles(evidence_text)
    if claimed_nozzles - in_evidence:
        return f"nozzle not in evidence: {sorted(claimed_nozzles - in_evidence)}"
    if in_quote and claimed_nozzles - in_quote:
        return f"nozzle not in cited quote: {sorted(claimed_nozzles - in_quote)}"

    # A generic page (no crop named at all) is not contradicted by a claim that names the crop
    # asked about: the crop usually sits in a slide title outside the page text. A page that
    # names *other* crops is, and so is a quote about a different crop.
    claimed_crops = _crops(claim_flat)
    in_quote, in_evidence = _crops(quote_flat), _crops(evidence_flat)
    if in_evidence and claimed_crops - in_evidence:
        return f"crop not in evidence: {sorted(claimed_crops - in_evidence)}"
    if in_quote and claimed_crops - in_quote:
        return f"crop not in cited quote: {sorted(claimed_crops - in_quote)}"

    # "ใบแคบและกว้าง" is one class; a claim for only ใบแคบ (or the reverse) is a different claim.
    quote_groups, evidence_groups = _weed_groups(quote_flat), _weed_groups(evidence_flat)
    for group in _weed_groups(claim_flat):
        if group in quote_groups:
            continue
        if any(group < other for other in quote_groups):
            return f"weed class narrowed from combined class: {sorted(group)}"
        if quote_groups and all(not group & other for other in quote_groups):
            return f"weed class contradicts cited quote: {sorted(group)}"
        if group in evidence_groups:
            continue
        if any(group < other for other in evidence_groups):
            return f"weed class narrowed from combined class: {sorted(group)}"
        # Two classes printed in separate cells ("ประเภทใบแคบ | ประเภทใบกว้าง") are still both
        # stated by the evidence; a class the evidence never names is not.
        if not group <= set().union(*evidence_groups):
            return f"weed class not matching evidence: {sorted(group)}"
    return ""
