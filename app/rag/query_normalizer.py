"""
Query Normalizer
================
Normalizes Thai agricultural drone queries:
- Fixes Thai typed with the wrong (English) keyboard layout (e.g. 'gfnvo' -> 'เดือน')
- Normalizes colloquialisms (e.g. 'พัดฟ้า' -> 'พัดฟ้า (พัดน้ำเงิน)')
- Normalizes agricultural common terms ('คุมดิน' -> 'คลุมดิน/คุมดิน')
- Cleans typos from LINE keyboard ('ดพ่น', 'ฉีดดพ่น' -> 'ฉีดพ่น')
- Collapses consecutive whitespace
"""
from __future__ import annotations

import re

# Thai Kedmanee layout: English key -> Thai character (for text typed with the wrong keyboard layout)
_KEDMANEE = dict(zip(
    "qwertyuiop[]asdfghjkl;'zxcvbnm,./"
    "QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>?",
    "ๆไำพะัีรนยบลฟหกดเ้่าสวงผปแอิืทมใฝ"
    "๐\"ฎฑธํ๊ณฯญฐ,ฤฆฏโฌ็๋ษศซ.()ฉฮฺ์?ฒฬฦ",
))

# Thai marks that can never start a word; a conversion starting with one is not a real Thai word
_THAI_NON_LEADING = set("ะัาำิีึืฺุู็่้๊๋์ํ")

# Latin terms that legitimately appear in agricultural drone questions
_LATIN_WHITELIST = {
    "drone", "dji", "uav", "uas", "gps", "rtk", "gsd", "ndvi", "vari", "caat", "pdf",
    "agras", "xag", "app", "rpm", "lidar", "fpv", "rgb", "nir", "ml", "km", "cm", "kg",
}

_LATIN_TOKEN_RE = re.compile(r"[a-z][a-z;'\[\],./]{2,}")


def _convert_keyboard_token(token: str) -> str:
    vowels = sum(ch in "aeiou" for ch in token)
    if token.lower() in _LATIN_WHITELIST or vowels / len(token) >= 0.34:
        return token
    converted = "".join(_KEDMANEE.get(ch, ch) for ch in token)
    if converted[0] in _THAI_NON_LEADING:
        return token
    return converted


def fix_keyboard_layout(text: str) -> str:
    """
    Convert words typed with the English keyboard layout while meaning Thai
    (e.g. 'gfnvo' -> 'เดือน'). Only applied when the message already contains Thai,
    so genuine English questions are left untouched.
    """
    if not re.search(r"[฀-๿]", text):
        return text
    return _LATIN_TOKEN_RE.sub(lambda m: _convert_keyboard_token(m.group(0)), text)


SYNONYM_REPLACEMENTS = [
    # Typos from rapid Thai mobile keyboard input
    (r"ฉีดดพ่น", "ฉีดพ่น"),
    (r"(?<!ฉี)ดพ่น", "ฉีดพ่น"),
    
    # Agricultural colloquialisms
    (r"พัดฟ้า(?:\s*\(พัดน้ำเงิน\))?", "พัดฟ้า (พัดน้ำเงิน)"),
    
    # Soil coverage & pre-emergence herbicide term
    (r"คุมดิน(?:/คลุมดิน)?", "คุมดิน/คลุมดิน"),
]


def normalize_query(query: str) -> str:
    """
    Clean and normalize user query for higher retrieval recall and consistency.
    """
    text = query.strip()
    if not text:
        return ""

    # Fix text typed with the wrong keyboard layout before anything else
    text = fix_keyboard_layout(text)

    # Normalize multiple whitespace
    text = re.sub(r"\s+", " ", text)

    # Apply synonym & typo replacements
    for pattern, replacement in SYNONYM_REPLACEMENTS:
        text = re.sub(pattern, replacement, text)

    return text.strip()
