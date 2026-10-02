from __future__ import annotations

import logging
import re

from openai import OpenAI

from app.config import API_KEY
from app.rag.format_utils import format_response_layout
from app.rag.vector_store import search

logger = logging.getLogger(__name__)


_llm_client: OpenAI | None = None


def get_llm_client() -> OpenAI:
    global _llm_client
    if _llm_client is None:
        _llm_client = OpenAI(
            api_key=API_KEY,
            base_url="https://gen.ai.kku.ac.th/api/v1",
        )
    return _llm_client


def retrieve_context(
    query: str,
    n_results: int = 20,
) -> str:
    """
    Retrieve relevant chunks from Chroma
    and format them as context for the LLM.
    """

    results = search(
        query=query,
        n_results=n_results,
    )

    documents = results.get(
        "documents",
        [[]],
    )[0]

    metadatas = results.get(
        "metadatas",
        [[]],
    )[0]

    distances = results.get(
        "distances",
        [[]],
    )[0]

    context_parts: list[str] = []

    for index, document in enumerate(
        documents
    ):
        raw_meta = metadatas[index] if index < len(metadatas) else None
        metadata = raw_meta if isinstance(raw_meta, dict) else {}

        source_file = metadata.get(
            "source_file",
            "unknown",
        )

        page_number = metadata.get(
            "page_number",
            "unknown",
        )

        source_type = metadata.get(
            "source_type",
            "text",
        )

        context_parts.append(
            "\n".join(
                [
                    f"[แหล่งข้อมูล {index + 1}]",
                    f"ไฟล์: {source_file}",
                    f"หน้า: {page_number}",
                    f"ประเภท: {source_type}",
                    f"เนื้อหา:",
                    document,
                ]
            )
        )

    return "\n\n".join(
        context_parts
    )


FALLBACK_MODELS = [
    "gemini-3.5-flash-lite",
    "gpt-5.6-luna",
    "nova-2-lite-v1",
    "llama-4-scout",
    "deepseek-v4-flash",
]

_EXHAUSTED_MODELS: set[str] = set()


def call_llm(
    messages: list[dict],
    client: OpenAI | None = None,
    preferred_model: str = "gemini-3.5-flash-lite",
    temperature: float = 0.0,
    max_tokens: int | None = None,
) -> str:
    """
    Call KKU GenAI OpenAI-compatible API with automatic fallback across models.
    Caches models that hit daily limit (401) to eliminate cascading retry delay.
    Supports max_tokens to prevent bloated output and minimize generation latency.
    """
    ai_client = client or get_llm_client()
    candidates = [preferred_model] + [m for m in FALLBACK_MODELS if m != preferred_model]
    available = [m for m in candidates if m not in _EXHAUSTED_MODELS]
    models_to_try = available if available else candidates

    last_error: Exception | None = None
    for model_name in models_to_try:
        try:
            kwargs: dict = {
                "model": model_name,
                "messages": messages,
                "temperature": temperature,
                "stream": False,
            }
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens

            response = ai_client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""
        except Exception as e:
            last_error = e
            err_msg = str(e).lower()
            if "daily limit" in err_msg or "401" in err_msg or "rate limit" in err_msg:
                _EXHAUSTED_MODELS.add(model_name)
                logger.warning(
                    f"Model '{model_name}' hit daily limit. Bypassing and falling back to next available model."
                )
                continue
            raise

    raise RuntimeError(f"All LLM models failed or reached limit: {last_error}")


def generate_grounded_answer(
    query: str,
    context: str,
    client: OpenAI | None = None,
    model: str = "gemini-3.5-flash-lite",
    max_tokens: int = 500,
) -> str:
    """
    Generate an answer strictly grounded in the retrieved context,
    with explicit file and page citations.
    """

    if not context.strip():
        return "ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้"

    system_prompt = (
        "คุณคือผู้เชี่ยวชาญด้านโดรนเกษตร หน้าที่ของคุณคือตอบคำถามเกษตรกรหรือนักบินโดรนใน LINE ให้มีระเบียบ สวยงาม อ่านง่าย ครบถ้วน ได้ใจความ ตรงประเด็น และเป็นประโยชน์แก่ผู้อ่านสูงสุด โดยไม่ตอบสั้นห้วนจนขาดสาระสำคัญ\n\n"
        "หลักการจัดโครงสร้างคำตอบให้อ่านง่ายบน LINE (Adaptive Layout Principles):\n"
        "1. ห้ามใช้เครื่องหมาย Markdown ทุกชนิด (ห้ามใส่ ** ตัวหนา, * ตัวเอียง, หรือ # หัวข้อ) เพราะ LINE จะแสดงเป็นเครื่องหมายดอกจันรกสายตา\n"
        "2. ลำดับชั้นสายตาและการจัดกลุ่ม (Visual Hierarchy):\n"
        "   - เริ่มต้นตอบประเด็นสำคัญทันที ไม่ต้องเกริ่นอารัมภบทหรือพูดทวนคำถามยืดยาว\n"
        "   - หากมีหัวข้อหลักและรายละเอียดปลีกย่อย ให้ระบุหัวข้อหลักให้ชัดเจน แล้วขึ้นบรรทัดใหม่ใช้ขีดย่อย (- ) สำหรับรายละเอียด เพื่อให้ผู้อ่านแยกแยะระหว่างหัวข้อกับเนื้อหาได้ทันที\n"
        "   - ห้ามทำหัวข้อเป็น bullet เปล่าๆ แล้วตามด้วยเนื้อหาที่เป็น bullet เดียวกัน (หลีกเลี่ยง bullet แบนราบที่กลืนกันไปหมด)\n"
        "3. ปรับสไตล์คำตอบให้สอดคล้องกับลักษณะคำถาม (Context-Aware Adaptation):\n"
        "   - คำถามเปรียบเทียบ (Comparison): จัดกลุ่มตามสิ่งที่นำมาเปรียบเทียบให้ชัดเจน พร้อมแจกแจงคุณสมบัติย่อยด้วย (- ) โดยเน้นประเด็นสำคัญที่ต่างกันจริง และหลีกเลี่ยงการเขียนซ้ำว่า 'ไม่มีข้อมูลในเอกสาร' หลายๆ รอบ\n"
        "   - คำถามขั้นตอน (Steps / How-to): ใช้ลำดับตัวเลข 1. 2. 3. เพื่อให้อ่านตามและทำตามลำดับได้สะดวก\n"
        "   - คำถามข้อควรระวัง / ความปลอดภัย: แยกประเด็นข้อควรระวังให้เด่นชัด พร้อมอธิบายผลกระทบและแนวทางป้องกัน\n"
        "   - คำถามสั้น / สเปกตรงไปตรงมา: ตอบใจความสำคัญให้ชัดเจนใน 1-2 ย่อหน้า ไม่จำเป็นต้องฝืนแจกแจงเป็นรายการยาว\n"
        "4. การใช้ Emoji อย่างเป็นธรรมชาติ (Contextual Emojis):\n"
        "   - สามารถเลือกใช้ emoji ประกอบหัวข้อหรือเน้นประเด็นสำคัญได้ตามความเหมาะสมของบริบท (เช่น 💡/📌 นำหน้าสรุป, ⚙️ สเปกเครื่อง, ⚠️ ข้อควรระวัง, 🟠/🔵 แยกสีหัวฉีด) เพื่อความสบายตาในการอ่านบนมือถือ แต่ไม่จำเป็นต้องใส่ทุกจุด และห้ามใส่มากเกินไปจนรกสายตา\n"
        "5. ตำแหน่งแหล่งอ้างอิง (Bottom Isolated Citation):\n"
        "   - ต้องเว้นบรรทัดว่าง 1 บรรทัด ก่อนใส่แหล่งอ้างอิงเสมอ\n"
        "   - ต้องวางแหล่งอ้างอิงไว้ที่ 'บรรทัดล่างสุดเพียงที่เดียว' ในรูปแบบ: (แหล่งอ้างอิง: [ชื่อไฟล์], หน้า [เลขหน้า])\n"
        "   - ห้ามใส่แหล่งอ้างอิงติดกับประโยคเนื้อหาในบรรทัดเดียวกันโดยเด็ดขาด\n\n"
        "6. ความน่าเชื่อถือ (Strict Grounding): ตอบเฉพาะข้อมูลที่ปรากฏใน 'บริบทที่กำหนดให้' เท่านั้น ห้ามเดา ห้ามใช้ความรู้ภายนอก\n"
        "   - การเข้าใจภาษาพูดของเกษตรกร: หากผู้ใช้ใช้คำเรียกสีหรือชื่อเรียกทั่วไปที่ตรงกับอุปกรณ์ในบริบท (เช่น เกษตรกรเรียก พัดฟ้า หรือ สีฟ้า ซึ่งในเอกสารระบุเป็น พัดน้ำเงิน/สีน้ำเงิน, โดรนพ่นยา หมายถึง โดรนฉีดพ่น) "
        "ให้ตอบข้อมูลของอุปกรณ์นั้นตามบริบทได้เลย โดยสามารถระบุชื่อทางการตามเอกสาร เช่น พัดฟ้า (พัดน้ำเงิน)\n"
        "7. กรณีนอกเหนือบริบท: หากไม่มีข้อมูลในบริบท ให้ตอบเพียงว่า 'ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้'\n"
        "8. หากคำถามมีบางส่วนที่อยู่นอกเหนือเอกสารฐานความรู้ (เช่น ถามสภาพอากาศแบบเรียลไทม์ หรือข้อมูลในอนาคต) ให้ตอบเฉพาะส่วนที่มีหลักฐานในเอกสาร และระบุอย่างสุภาพว่าระบบไม่มีข้อมูลแบบเรียลไทม์ในส่วนนั้น ห้ามคิดค้นหรือเดาข้อมูลเอง"
    )

    user_prompt = (
        f"บริบทที่กำหนดให้:\n"
        f"{context}\n\n"
        f"คำถาม:\n"
        f"{query}\n\n"
        f"คำตอบที่ครบถ้วนและชัดเจน:"
    )

    raw_answer = call_llm(
        messages=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        client=client,
        preferred_model=model,
        temperature=0.0,
        max_tokens=max_tokens,
    )

    default_cite = ""
    file_match = re.search(r"ไฟล์:\s*([^\n]+)", context)
    page_match = re.search(r"หน้า:\s*([^\n]+)", context)
    if file_match and page_match:
        default_cite = f"(แหล่งอ้างอิง: {file_match.group(1).strip()}, หน้า {page_match.group(1).strip()})"

    return format_response_layout(raw_answer, default_citation=default_cite)