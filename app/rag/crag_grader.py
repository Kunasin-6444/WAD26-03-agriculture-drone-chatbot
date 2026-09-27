from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from openai import OpenAI

from app.rag.rag_service import call_llm, get_llm_client


GradeType = Literal["CORRECT", "INCORRECT", "AMBIGUOUS"]


@dataclass
class GradeResult:
    grade: GradeType
    is_relevant: bool
    reason: str
    is_caat_topic: bool = False


# Keywords indicating questions related to Air Law or Air Space (UAV01 / UA03)
CAAT_KEYWORDS = [
    "กฎหมาย",
    "กฎหมายโดรน",
    "พ.ร.บ.",
    "พระราชบัญญัติ",
    "ขึ้นทะเบียน",
    "ลงทะเบียนโดรน",
    "กสทช",
    "caat",
    "น่านฟ้า",
    "เขตห้ามบิน",
    "air space",
    "air law",
    "ใบอนุญาตนักบิน",
    "ขออนุญาตบิน",
    "ระยะห่างสนามบิน",
    "ความสูงการบิน",
    "ห้ามบินสูงเกิน",
    "บินโดรนที่นา",
    "บินในนา",
    "บินในที่ตัวเอง",
    "บินโดรนครั้งแรก",
    "ก่อนบินโดรน",
    "จะบินโดรน",
    "ยื่นขออนุญาต",
    "ขออนุญาตปฏิบัติการบิน",
    "uas portal",
    "บินเพื่อตนเอง",
]


def is_caat_air_law_or_airspace_topic(query: str) -> bool:
    """
    Check if the user query is about Air Law or Air Space
    which requires the designated CAAT UAS Portal infographic source (R1).
    """
    q_lower = query.lower()
    return any(keyword in q_lower for keyword in CAAT_KEYWORDS)


def grade_retrieval(
    query: str,
    context: str,
    client: OpenAI | None = None,
    model: str = "gpt-5.6-luna",
) -> GradeResult:
    """
    Grade the retrieved context against the user query.
    Determines if the context contains sufficient evidence to answer accurately.
    """
    # Check if query falls under the CAAT Air Law / Air Space exception
    is_caat = is_caat_air_law_or_airspace_topic(query)

    # Empty context check
    if not context or not context.strip():
        return GradeResult(
            grade="INCORRECT",
            is_relevant=False,
            reason="Retrieved context is empty.",
            is_caat_topic=is_caat,
        )

    # If it is a CAAT law/airspace query, knowledge from local PDFs (UAV01/UA03)
    # is excluded by rule R1.
    if is_caat:
        return GradeResult(
            grade="INCORRECT",
            is_relevant=False,
            reason="Subject belongs to Air Law/Air Space (R1 rule: must use CAAT infographic instead of local PDF).",
            is_caat_topic=True,
        )

    ai_client = client or get_llm_client()

    system_prompt = (
        "คุณคือผู้ประเมินคุณภาพข้อมูล (Relevance Grader & Semantic Intent Classifier) ในระบบ CRAG สำหรับโดรนการเกษตร\n"
        "หน้าที่ของคุณคือ:\n"
        "1. วิเคราะห์เจตนาของคำถาม (is_caat_topic): "
        "ตรวจสอบว่าคำถามเกี่ยวข้องกับ กฎหมายการบินโดรน, กฎระเบียบ, การขึ้นทะเบียนโดรน/ผู้บังคับโดรน, กสทช., "
        "การขออนุญาตบิน (รวมถึงการบินในที่ดิน/ที่นาตนเอง, การบินครั้งแรก), น่านฟ้า, เขตห้ามบิน, ระยะห่างสนามบิน, "
        "หรือเงื่อนไขความปลอดภัยทางกฎหมายก่อนบิน หรือไม่ (ตอบ true หรือ false)\n"
        "2. ประเมินความเพียงพอของข้อมูล (grade): "
        "ตรวจสอบว่า 'บริบทที่ค้นหาได้' มีหลักฐานข้อมูลตรงประเด็นและเพียงพอต่อการตอบคำถามหรือไม่\n"
        "   - CORRECT: บริบทมีข้อมูลข้อเท็จจริงหรือตัวเลขตรงประเด็นเพียงพอที่จะตอบได้ "
        "(เช่น คำถามถามถึงความแตกต่าง, คุณสมบัติ, การใช้งาน, หรือสเปกของหัวฉีดหรืออุปกรณ์ แล้วบริบทมีข้อมูลอัตราการไหล ตัวเลขตาราง ขนาดละออง หรือความนิยมใช้ของอุปกรณ์เหล่านั้นอย่างชัดเจน ให้ตอบ CORRECT เสมอ ห้ามตอบ AMBIGUOUS)\n"
        "   - AMBIGUOUS: บริบทมีข้อมูลที่คลุมเครือ ไม่ระบุตัวเลขหรือคุณสมบัติที่ชัดเจน หรือไม่มีข้อเท็จจริงที่นำไปใช้อธิบายได้\n"
        "   - INCORRECT: บริบทไม่มีข้อมูลที่ตรงกับสิ่งที่ถามเลย หรือเป็นเรื่องกฎหมาย/การขึ้นทะเบียนการบินโดรน (ซึ่งต้องอ้างอิง CAAT Portal แทน PDF ตามกฎ R1)\n\n"
        "ให้ตอบกลับเป็น JSON รูปแบบนี้เท่านั้น:\n"
        "{\n"
        '  "is_caat_topic": true | false,\n'
        '  "grade": "CORRECT" | "AMBIGUOUS" | "INCORRECT",\n'
        '  "reason": "เหตุผลสั้นๆ ภาษาไทย"\n'
        "}"
    )

    user_prompt = (
        f"คำถามของผู้ใช้:\n{query}\n\n"
        f"บริบทที่ค้นหาได้:\n{context}\n\n"
        "ผลการประเมิน (JSON):"
    )

    try:
        raw_content = call_llm(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            client=client,
            preferred_model=model,
            temperature=0.0,
        )
        # Clean markdown code block if present
        clean_content = re.sub(r"```(?:json)?\n?", "", raw_content).strip("` \n")

        data = json.loads(clean_content)

        # Semantic classification result
        semantic_caat = bool(data.get("is_caat_topic", False))
        final_is_caat = is_caat or semantic_caat

        grade_str = str(data.get("grade", "INCORRECT")).upper()
        if final_is_caat or grade_str not in ("CORRECT", "AMBIGUOUS", "INCORRECT"):
            grade_str = "INCORRECT"

        reason_str = str(data.get("reason", ""))
        is_relevant = (grade_str == "CORRECT") and not final_is_caat

        return GradeResult(
            grade=grade_str,  # type: ignore
            is_relevant=is_relevant,
            reason=reason_str,
            is_caat_topic=final_is_caat,
        )

    except Exception as e:
        # Fallback heuristic: check if query key terms appear in context
        return GradeResult(
            grade="INCORRECT",
            is_relevant=False,
            reason=f"Grader parsing/API error: {e}",
            is_caat_topic=False,
        )
