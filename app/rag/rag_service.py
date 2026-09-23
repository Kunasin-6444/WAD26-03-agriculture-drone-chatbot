from __future__ import annotations

from openai import OpenAI

from app.config import API_KEY
from app.rag.vector_store import search


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
    n_results: int = 15,
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


def generate_grounded_answer(
    query: str,
    context: str,
    client: OpenAI | None = None,
    model: str = "gemini-3.5-flash-lite",
) -> str:
    """
    Generate an answer strictly grounded in the retrieved context,
    with explicit file and page citations.
    """

    if not context.strip():
        return "ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้"

    ai_client = client or get_llm_client()

    system_prompt = (
        "คุณคือผู้ช่วยผู้เชี่ยวชาญด้านโดรนการเกษตร หน้าที่ของคุณคือตอบคำถามของผู้ใช้โดยอิงจาก 'บริบทที่กำหนดให้' (Retrieved Context) เท่านั้น\n\n"
        "กฎการตอบ:\n"
        "1. ตอบเป็นภาษาไทยอย่างชัดเจน ถูกต้อง และตรงประเด็น\n"
        "2. ห้ามคิดค้นหรือเดาข้อมูลเองโดยเด็ดขาด (Strictly Grounded, No Hallucination) ใช้เฉพาะข้อมูลที่มีอยู่ในบริบทเท่านั้น\n"
        "3. ต้องระบุแหล่งที่มาอ้างอิงท้ายคำตอบเสมอ ในรูปแบบ: (แหล่งอ้างอิง: [ชื่อไฟล์], หน้า [เลขหน้า])\n"
        "4. หากในบริบทไม่มีข้อมูลเพียงพอที่จะตอบได้อย่างมั่นใจ ให้ตอบอย่างสุภาพว่า 'ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้'"
    )

    user_prompt = (
        f"บริบทที่กำหนดให้:\n"
        f"{context}\n\n"
        f"คำถาม:\n"
        f"{query}\n\n"
        f"คำตอบ:"
    )

    response = ai_client.chat.completions.create(
        model=model,
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
        temperature=0.0,
        stream=False,
    )

    return response.choices[0].message.content or ""