"""Drop native-PDF content that the vision pass of the same page already covers.

Every page is read twice: the PDF text layer (``native``) and Gemini vision. For the
slide decks in data/ the text layer is often damaged Thai and almost always a subset of
what vision returned, so indexing both only adds noisy near-duplicates that compete for
the top-k and give the model garbled text to quote. A native unit is kept when it carries
something vision did not: text vision did not transcribe, or numbers it does not contain.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.ingestion.models import KnowledgeUnit

COVERAGE_THRESHOLD = 0.85
NOISE_MAX_LEN = 3
NATIVE_SOURCES = {"pdf_text", "pdf_native_table"}
VISION_SOURCES = {"vision", "vision_summary"}


@dataclass(frozen=True)
class NativeAssessment:
    drop: bool
    reason: str
    coverage: float
    missing_numbers: tuple[str, ...]


def skeleton(text: str) -> str:
    """Thai consonants + ASCII letters/digits only, so vowel/tone/space noise cannot matter."""
    return "".join(ch for ch in text.lower() if "ก" <= ch <= "ฮ" or (ch.isascii() and ch.isalnum()))


def _grams(text: str, n: int = 4) -> set[str]:
    return {text[i:i + n] for i in range(max(0, len(text) - n + 1))}


def numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text.replace(",", "")))


def benign_numbers(text: str, page: int) -> set[str]:
    """Slide/page numbers printed in the native layer are not content."""
    tokens = text.split()
    edge = {t for t in (tokens[:1] + tokens[-1:]) if t.isdigit()}
    return edge | {str(page), f"{page:03d}", f"{page + 1:03d}"}


def assess_native(native_text: str, page: int, vision_text: str) -> NativeAssessment:
    sk = skeleton(native_text)
    if len(sk) <= NOISE_MAX_LEN:
        return NativeAssessment(True, "noise", 0.0, ())
    grams = _grams(sk)
    vision_grams = _grams(skeleton(vision_text))
    coverage = len(grams & vision_grams) / len(grams) if grams else 0.0
    missing = tuple(sorted(numbers(native_text) - numbers(vision_text) - benign_numbers(native_text, page)))
    drop = bool(vision_grams) and coverage >= COVERAGE_THRESHOLD and not missing
    return NativeAssessment(drop, f"covered {coverage:.2f}" if drop else "unique", round(coverage, 2), missing)


def drop_covered_native_units(units: list[KnowledgeUnit], page: int) -> list[KnowledgeUnit]:
    """Return the page's units without native units that add nothing over vision."""
    vision_text = " ".join(u.content for u in units if u.metadata.get("source") in VISION_SOURCES)
    kept = []
    for unit in units:
        if unit.metadata.get("source") in NATIVE_SOURCES and assess_native(unit.content, page, vision_text).drop:
            continue
        kept.append(unit)
    return kept
