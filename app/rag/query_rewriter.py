from __future__ import annotations

import logging
import re

from openai import OpenAI

from app.rag.rag_service import call_llm

logger = logging.getLogger(__name__)

# Thai Kedmanee layout: English key -> Thai character (for text typed with the wrong keyboard layout)
_KEDMANEE = dict(zip(
    "qwertyuiop[]asdfghjkl;'zxcvbnm,./"
    "QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>?",
    "ๆไำพะัีรนยบลฟหกดเ้่าสวงผปแอิืทมใฝ"
    "๐\"ฎฑธํ๊ณฯญฐ,ฤฆฏโฌ็๋ษศซ.()ฉฮฺ์?ฒฬฦ",
))

# Thai marks that can never start a word; a conversion starting with one is not a real Thai word
_THAI_NON_LEADING = set("ะัาำิีึืฺุู็่้๊๋์ํ")

# Latin terms that legitimately appear in agricultural drone questions
_LATIN_WHITELIST = {
    "drone", "dji", "uav", "uas", "gps", "rtk", "gsd", "ndvi", "vari", "caat", "pdf",
    "agras", "xag", "app", "rpm", "lidar", "fpv", "rgb", "nir", "ml", "km", "cm", "kg",
}

_LATIN_TOKEN_RE = re.compile(r"[a-z][a-z;'\[\],./]{2,}")

HELP_PATTERNS = (
    "วิธีพิมพ์คำถาม",
    "วิธีใช้งาน",
    "ใช้งานยังไง",
    "ใช้งานอย่างไร",
    "ถามอะไรได้บ้าง",
)

HELP_MESSAGE = (
    "💡 วิธีพิมพ์คำถามให้ได้คำตอบตรงที่สุด\n\n"
    "1. ระบุพืชและช่วงเวลาให้ชัด\n"
    "- เช่น \"ฉีดยาคุมก่อนอ้อยงอก ใช้สารอะไร สำหรับวัชพืชใบแคบ\"\n"
    "2. ระบุอุปกรณ์หรือค่าที่ต้องการ\n"
    "- เช่น \"หัวฉีดพัดส้มอัตราการไหลเท่าไร\" หรือ \"บินพ่นยาสูงกี่เมตร\"\n"
    "3. ถามต่อเนื่องได้\n"
    "- ระบบจำคำถามล่าสุดของคุณ เช่น ถามต่อว่า \"แล้วใบกว้างล่ะ\"\n"
    "4. ถามทีละเรื่อง\n"
    "- คำถามสั้น ชัด 1 เรื่อง จะได้คำตอบแม่นกว่าคำถามรวมหลายเรื่อง\n\n"
    "หัวข้อที่ตอบได้: การฉีดพ่นด้วยโดรน หัวฉีดและอัตราการไหล สารกำจัดวัชพืช "
    "การสำรวจแปลงและถ่ายภาพทางอากาศ และการขออนุญาตบินโดรน (CAAT)"
)


def is_help_request(text: str) -> bool:
    return any(p in text for p in HELP_PATTERNS)


def _convert_token(token: str) -> str:
    vowels = sum(ch in "aeiou" for ch in token)
    if token in _LATIN_WHITELIST or vowels / len(token) >= 0.34:
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
    return _LATIN_TOKEN_RE.sub(lambda m: _convert_token(m.group(0)), text)


def rewrite_query(
    query: str,
    history: list[tuple[str, str]] | None = None,
    client: OpenAI | None = None,
) -> str:
    """
    Turn the user's message into a standalone, correctly spelled search question.
    Resolves follow-ups ('ช่วงเวลานี้', 'แล้วใบกว้างล่ะ') using recent conversation turns.
    Falls back to the layout-fixed message on any error.
    """
    fixed = fix_keyboard_layout(query.strip())

    history_text = "\n".join(
        f"ผู้ใช้: {q}\nบอท: {a[:200]}" for q, a in (history or [])
    ) or "(ไม่มี)"

    system_prompt = (
        "คุณคือตัวช่วยเรียบเรียงคำถามสำหรับระบบค้นหาเอกสารโดรนเกษตร (ห้ามตอบคำถาม)\n"
        "งาน: เขียนคำถามล่าสุดของผู้ใช้ใหม่ให้เป็นคำถามภาษาไทยที่สมบูรณ์ในตัวเอง 1 ประโยค\n"
        "1. แก้คำสะกดผิด/พิมพ์ตก (เช่น คุมดิน -> คลุมดิน, ฉีดดพ่น -> ฉีดพ่น, ช่วงเวลาน้ -> ช่วงเวลานี้)\n"
        "2. ถ้าคำถามอ้างถึงบทสนทนาก่อนหน้า (เช่น 'ช่วงเวลานี้', 'แล้วใบกว้างล่ะ', 'สารนั้น') ให้เติมพืช ช่วงเวลา หรือหัวข้อจากบทสนทนาให้ครบ\n"
        "3. ถ้าคำถามเป็นเรื่องใหม่ ไม่เกี่ยวกับบทสนทนาก่อนหน้า ห้ามนำบริบทเก่ามาใส่\n"
        "4. คงรายละเอียดเดิมไว้ทั้งหมด (ชื่อพืช อายุพืช ชนิดวัชพืช ตัวเลข) ห้ามเพิ่มข้อมูลที่ผู้ใช้ไม่ได้ถาม\n"
        "5. ตอบเฉพาะคำถามที่เรียบเรียงแล้วเท่านั้น ไม่ต้องมีคำอธิบาย"
    )
    user_prompt = (
        f"บทสนทนาก่อนหน้า:\n{history_text}\n\n"
        f"คำถามล่าสุด:\n{fixed}\n\n"
        f"คำถามที่เรียบเรียงแล้ว:"
    )

    try:
        rewritten = call_llm(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            client=client,
            temperature=0.0,
            max_tokens=150,
        ).strip().strip('"').strip()
    except Exception as e:
        logger.warning(f"Query rewrite failed, using original query: {e}")
        return fixed

    if not rewritten or len(rewritten) > 300 or "\n" in rewritten:
        return fixed

    logger.info(f"Rewrote query '{query}' -> '{rewritten}'")
    return rewritten
