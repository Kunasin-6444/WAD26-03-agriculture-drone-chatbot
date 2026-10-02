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


# Keywords indicating questions strictly related to Air Law or Air Space (UAV01 / UA03)
CAAT_KEYWORDS = [
    "กฎหมาย",
    "พ.ร.บ.",
    "พระราชบัญญัติ",
    "ขึ้นทะเบียน",
    "ลงทะเบียนโดรน",
    "กสทช",
    "caat",
    "กพท",
    "น่านฟ้า",
    "เขตห้ามบิน",
    "air space",
    "air law",
    "ใบอนุญาตนักบิน",
    "ใบอนุญาตบิน",
    "ขออนุญาต",
    "ขออนุญาตบิน",
    "ระยะห่างสนามบิน",
    "ห้ามบินสูงเกิน",
    "ยื่นขออนุญาต",
    "ขออนุญาตปฏิบัติการบิน",
    "uas portal",
    "โทษของการบินโดรน",
    "ปรับกี่บาท",
    "ผิดกฎหมายการบิน",
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
    model: str = "gemini-3.5-flash-lite",
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
        "คุณคือผู้ประเมินความเกี่ยวข้องของข้อมูล (Relevance Grader & Semantic Classifier) ในระบบ RAG สำหรับโดรนการเกษตร\n"
        "หน้าที่ของคุณคือ:\n"
        "1. ประเมินความเพียงพอของข้อมูลในบริบท (grade): ตรวจสอบว่าบริบทเอกสารโดรนการเกษตรที่ค้นหามา มีข้อเท็จจริงหรือหลักฐานตรงประเด็นสำหรับคำถามของผู้ใช้หรือไม่\n"
        "   - CORRECT: บริบทมีข้อมูลตรงประเด็นที่จะตอบคำถามหลักได้จริง (รวมถึงคำถามผสมที่เอกสารตอบสาระหลักได้ เช่น พืช สารเคมี วัชพืช หัวฉีด หรืออุปกรณ์ แม้จะมีส่วนถามนอกขอบเขตปนมา เช่น สภาพอากาศเรียลไทม์)\n"
        "   - AMBIGUOUS: บริบทมีข้อมูลที่เกี่ยวข้องกับสิ่งที่ถาม แต่คลุมเครือ ไม่ชัดเจน หรือหลักฐานอ่อนเกินกว่าจะสรุปตอบคำถามหลักได้อย่างมั่นใจ\n"
        "   - INCORRECT: บริบทไม่มีข้อมูลที่เกี่ยวข้องกับสิ่งที่ถามเลย หรือเป็นคำถามด้านกฎหมายการบินโดรนที่ต้องใช้ CAAT Portal แทน PDF ตามกฎ R1\n"
        "2. ตรวจสอบข้อยกเว้นเรื่องกฎหมายการบิน (is_caat_topic): ระบุว่าคำถามเกี่ยวข้องกับ กฎหมายการบินโดรน, กฎระเบียบ, การขึ้นทะเบียนโดรน, กสทช., เขตห้ามบิน หรือไม่ (ตอบ true หรือ false)\n"
        "3. ความเข้าใจภาษาพูดและบริบทเกษตรกร (Semantic Domain Understanding): "
        "ผู้ใช้อาจใช้ภาษาพูด คำเรียกสีทั่วไป หรือคำย่อของอุปกรณ์การเกษตร (เช่น เรียกหัวฉีดพัดสีฟ้า/พัดฟ้า แทนพัดน้ำเงิน, ฉีดยา/พ่นยา แทนการฉีดพ่นสารเคมี) "
        "ให้ประเมินความเกี่ยวข้องที่เนื้อหาของอุปกรณ์หรือข้อเท็จจริงตามเจตนา ไม่จับคู่คำแบบตรงตัวอักษร หากบริบทมีข้อมูลของอุปกรณ์หรือสารนั้นๆ อย่างชัดเจน ให้ถือว่าหลักฐานตรงประเด็นและเพียงพอ (CORRECT)\n\n"
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
            max_tokens=300,
        )
        # Clean markdown and extract JSON object between first { and last }
        match = re.search(r"\{[\s\S]*\}", raw_content)
        clean_content = match.group(0) if match else raw_content.strip()

        try:
            data = json.loads(clean_content)
        except Exception:
            # Resilient fallback regex extraction if LLM formatting had minor syntax issues
            data = {}
            grade_match = re.search(r'"grade"\s*:\s*"([^"]+)"', raw_content, re.IGNORECASE)
            if grade_match:
                data["grade"] = grade_match.group(1).upper()
            caat_match = re.search(r'"is_caat_topic"\s*:\s*(true|false)', raw_content, re.IGNORECASE)
            if caat_match:
                data["is_caat_topic"] = caat_match.group(1).lower() == "true"
            reason_match = re.search(r'"reason"\s*:\s*"([^"]+)"', raw_content)
            if reason_match:
                data["reason"] = reason_match.group(1)

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
