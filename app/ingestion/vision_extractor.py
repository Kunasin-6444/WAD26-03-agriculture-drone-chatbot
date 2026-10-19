from pathlib import Path
import json
import hashlib
import os
import re
import time
import zlib
from typing import Literal

import pymupdf
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError
from pydantic import BaseModel, Field, ValidationError


load_dotenv()

VISION_CACHE_VERSION = "v2"  # Bump when the extraction prompt/schema changes.


# --------------------------------------------------
# Output schema
# --------------------------------------------------

class TableRow(BaseModel):
    cells: list[str] = Field(default_factory=list)


class VisualElement(BaseModel):
    """
    A meaningful visual element found on a PDF page.

    extracted_text:
        Text and values directly visible in the visual.

    description:
        Short semantic description of the visual.

    visual_description:
        More detailed interpretation of the visual content,
        grounded in the provided page.

    columns / rows:
        Only for ``type == "table"`` and only when the structured-table prompt is used:
        the printed column headings and every data row, cell by cell.
    """

    type: str | None = None

    columns: list[str] | None = None

    rows: list[TableRow] | None = None

    status: Literal[
        "clear",
        "ambiguous",
        "unreadable",
    ] | None = None

    description: str | None = None

    extracted_text: str | None = None

    visual_description: str | None = None


class VisionPageResult(BaseModel):
    """
    Result of analyzing one PDF page.
    """

    has_meaningful_visual_content: bool = False

    summary: str | None = None

    elements: list[VisualElement] = Field(
        default_factory=list
    )


def validate_vision_result(result: VisionPageResult) -> VisionPageResult:
    """Reject generation loops before they can become cached or published evidence.

    Check individual prose/cell fields rather than all cells together: repeated
    values in a genuine table are allowed. This catches degeneration, not factual
    correctness; visual source review is still required.
    """
    fields = [result.summary or ""]
    for element in result.elements:
        fields.extend([element.description or "", element.extracted_text or "",
                       element.visual_description or "", *(element.columns or [])])
        fields.extend(cell for row in element.rows or [] for cell in row.cells)
    if any(re.search(r"\b(\w{2,})(?:\s+\1){23,}\b", value, re.IGNORECASE) for value in fields):
        raise ValueError("Vision response contains a repeated-token generation loop")
    # A model can also loop over a whole phrase, or over Thai text that has no spaces to split on:
    # all of one table's cells together, and every prose field, must not be almost pure repetition.
    tables = [" ".join(cell for row in element.rows or [] for cell in row.cells) for element in result.elements]
    if any(is_generation_loop(value) for value in [*fields, *tables]):
        raise ValueError("Vision response contains a repeated-phrase generation loop")
    return result


def is_generation_loop(text: str) -> bool:
    words = text.lower().split()
    if len(words) >= 24:
        shingles = [tuple(words[i:i + 4]) for i in range(len(words) - 3)]
        if len(set(shingles)) / len(shingles) < 0.3:
            return True
    raw = text.encode("utf-8")
    return len(raw) >= 400 and len(zlib.compress(raw)) / len(raw) < 0.08


# --------------------------------------------------
# Gemini client
# --------------------------------------------------

api_key = os.getenv("GOOGLE_API_KEY")

client = genai.Client(
    api_key=api_key
) if api_key else None


# --------------------------------------------------
# Parse Gemini response
# --------------------------------------------------

def parse_vision_response(
    response,
) -> VisionPageResult:
    """
    Parse Gemini structured output safely.

    Preferred:
        response.parsed

    Fallback:
        response.text containing JSON
    """

    for candidate in getattr(response, "candidates", None) or []:
        reason = getattr(candidate, "finish_reason", None)
        name = getattr(reason, "name", reason)
        if isinstance(name, str) and name.upper() not in {"STOP", "FINISH_REASON_UNSPECIFIED"}:
            usage = getattr(response, "usage_metadata", None)
            raise RuntimeError(
                f"Vision response did not finish normally ({name}; "
                f"output={getattr(usage, 'candidates_token_count', None)}, "
                f"thinking={getattr(usage, 'thoughts_token_count', None)} tokens)"
            )

    parsed = getattr(
        response,
        "parsed",
        None,
    )

    if parsed is not None:

        if isinstance(
            parsed,
            VisionPageResult,
        ):
            return validate_vision_result(parsed)

        return validate_vision_result(VisionPageResult.model_validate(parsed))

    text = getattr(
        response,
        "text",
        None,
    )

    if not text:
        raise RuntimeError(
            "Gemini returned no structured result"
        )

    text = text.strip()

    # Remove markdown code fences if Gemini returns them.
    if text.startswith("```"):

        lines = text.splitlines()

        if lines:
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        text = "\n".join(lines).strip()

    try:

        raw_data = json.loads(text)

    except json.JSONDecodeError as exc:

        raise RuntimeError(
            "Gemini returned invalid JSON:\n"
            f"{text[:1000]}"
        ) from exc

    try:

        return validate_vision_result(VisionPageResult.model_validate(raw_data))

    except ValidationError as exc:

        raise RuntimeError(
            "Gemini JSON does not match expected schema:\n"
            f"{exc}"
        ) from exc


# --------------------------------------------------
# Gemini request with retry
# --------------------------------------------------

def generate_with_retry(
    image_bytes: bytes,
    prompt: str,
    max_retries: int = 3,
):
    """
    Send image + prompt to Gemini.

    Retries temporary server/network failures and 429 rate limits.

    Backoff:
        5s -> 10s -> 20s (or 10s -> 20s -> 40s for rate limit)
    """

    if client is None:
        raise RuntimeError("GOOGLE_API_KEY is not set")
    timeout = float(os.getenv("VISION_TIMEOUT_SECONDS", "30"))
    if max_retries < 1 or timeout < 10:
        raise ValueError("Vision retries must be positive and timeout at least 10 seconds")
    # A clean page answer is a few thousand tokens; a generation loop runs until this cap, so a
    # low cap fails a looping page fast (finish_reason MAX_TOKENS) instead of waiting for the timeout.
    max_output_tokens = int(os.getenv("VISION_MAX_OUTPUT_TOKENS", "16384"))

    last_exc: Exception | None = None

    for attempt in range(max_retries):

        try:

            response = client.models.generate_content(
                model=os.getenv("VISION_MODEL", "gemini-3.5-flash-lite"),
                contents=[
                    types.Part.from_bytes(
                        data=image_bytes,
                        mime_type="image/png",
                    ),
                    prompt,
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=VisionPageResult,
                    max_output_tokens=max_output_tokens,
                    http_options=types.HttpOptions(timeout=int(timeout * 1000),
                        retry_options=types.HttpRetryOptions(attempts=1)),
                ),
            )

            return response

        except ClientError as exc:

            error_code = getattr(exc, "code", None)
            error_str = str(exc)
            last_exc = exc

            if error_code == 429 or "RESOURCE_EXHAUSTED" in error_str or "429" in error_str:
                if attempt == max_retries - 1:
                    break
                delay = 10 * (2 ** attempt)
                print(
                    f"Gemini Rate Limit (429 / RESOURCE_EXHAUSTED). "
                    f"Retrying in {delay}s "
                    f"(attempt {attempt + 1}/{max_retries})..."
                )
                time.sleep(delay)
                continue

            raise

        except ServerError as exc:

            error_code = getattr(
                exc,
                "code",
                None,
            )

            last_exc = exc

            if error_code not in {
                500,
                502,
                503,
                504,
            }:
                raise

        except Exception as exc:

            last_exc = exc

        if attempt == max_retries - 1:
            break

        delay = 5 * (2 ** attempt)

        print(
            f"Gemini request failed ({last_exc!r}). "
            f"Retrying in {delay}s "
            f"(attempt {attempt + 1}/{max_retries})..."
        )

        time.sleep(delay)

    raise RuntimeError(
        f"Gemini request failed after {max_retries} attempts"
    ) from last_exc


# --------------------------------------------------
# Selective Vision Heuristic
# --------------------------------------------------

def should_use_vision(
    doc_or_path: str | Path | pymupdf.Document,
    page_number: int,
) -> tuple[bool, str]:
    """
    Decide whether a PDF page truly needs Gemini Vision extraction.

    Returns:
        (True, reason) if Vision is needed (images, complex diagrams, corrupted text).
        (False, "pure_text_page") if native text extraction is sufficient.
    """

    should_close = False

    if isinstance(doc_or_path, pymupdf.Document):
        doc = doc_or_path
    else:
        pdf_path = Path(doc_or_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        doc = pymupdf.open(pdf_path)
        should_close = True

    try:

        if page_number < 1 or page_number > len(doc):
            raise ValueError(
                f"Page {page_number} out of range 1..{len(doc)}"
            )

        page = doc[page_number - 1]
        raw_text = page.get_text().strip()

        # 1. Content images (> 150x150, ignoring tiny icons/logos)
        imgs = page.get_images()
        content_imgs = 0
        for img_info in imgs:
            try:
                base_img = doc.extract_image(img_info[0])
                if base_img["width"] > 150 or base_img["height"] > 150:
                    content_imgs += 1
            except Exception:
                pass

        if content_imgs > 0:
            return True, f"has_{content_imgs}_content_images"

        drawings = len(page.get_drawings())

        # 2. Complex vector drawings (diagrams, flowcharts, timelines)
        if drawings > 10:
            return True, f"complex_vector_drawings_{drawings}"

        # 3. Sparse text with graphics (e.g. title slide or visual banner)
        if len(raw_text) < 50 and (len(imgs) > 0 or drawings > 0):
            return True, "sparse_text_with_graphics"

        # 4. Corrupted font encoding (mojibake / replacement chars)
        if "\ufffd" in raw_text:
            return True, "corrupted_font"

        # If none of the above, native text extraction is sufficient
        return False, "pure_text_page"

    finally:
        if should_close:
            doc.close()


# --------------------------------------------------
# Vision Caching
# --------------------------------------------------

def get_cache_path(
    pdf_path: str | Path,
    page_number: int,
    cache_dir: str | Path = "cache/vision",
    document_sha256: str | None = None,
    structured_tables: bool = False,
) -> Path:
    digest = document_sha256 or hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()
    identity = f"{VISION_CACHE_VERSION}:{digest}:{os.getenv('VISION_MODEL', 'gemini-3.5-flash-lite')}"
    if structured_tables:
        identity += ":tables"  # a different prompt/result shape must never reuse older cache entries
    key = hashlib.sha256(identity.encode()).hexdigest()
    return Path(cache_dir) / VISION_CACHE_VERSION / key / f"page_{page_number}.json"


def load_vision_cache(
    cache_path: Path,
) -> VisionPageResult | None:
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        return validate_vision_result(VisionPageResult.model_validate(data))
    except Exception as exc:
        print(f"[load_vision_cache] Failed to read {cache_path}: {exc}")
        return None


def save_vision_cache(
    cache_path: Path,
    result: VisionPageResult,
) -> None:
    validate_vision_result(result)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            result.model_dump_json(indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"[save_vision_cache] Failed to write {cache_path}: {exc}")


# --------------------------------------------------
# Analyze one PDF page
# --------------------------------------------------

STRUCTURED_TABLE_TAIL = """Return ONLY valid JSON.

สำหรับ element ที่ type เป็น "table" ให้ส่งตารางเป็นโครงสร้างเพิ่มเติม:

- columns: หัวคอลัมน์ตามที่พิมพ์ในตาราง เรียงจากซ้ายไปขวา
  ถ้าหน้านี้ไม่มีแถวหัวตาราง (เป็นตารางที่ต่อจากหน้าก่อนหน้า) ให้ columns เป็น []
  ห้ามสร้างหัวคอลัมน์เองหรือคัดลอกหัวตารางจากหน้าอื่น
- rows: ทุกแถวข้อมูลเรียงจากบนลงล่าง แต่ละแถวคือ cells ที่มีจำนวนเท่ากับจำนวนคอลัมน์
  แต่ละ cell เป็นข้อความตามต้นฉบับ รักษาตัวเลขและหน่วยตามที่พิมพ์ ห้ามคำนวณหรือแก้ค่า
  cell ว่างให้ใส่ "" แถวหัวข้อกลุ่มที่รวมเซลล์ข้ามคอลัมน์ให้ใส่ข้อความใน cell แรก
  และปล่อย cell ที่เหลือเป็น ""
- extracted_text ของตารางให้คงไว้ตามเดิมได้ แต่ข้อมูลหลักต้องอยู่ใน columns และ rows

ใช้โครงสร้าง:

{
  "has_meaningful_visual_content": true,
  "summary": "...",
  "elements": [
    {
      "type": "...",
      "status": "clear",
      "description": "...",
      "extracted_text": "...",
      "visual_description": "...",
      "columns": ["..."],
      "rows": [{"cells": ["..."]}]
    }
  ]
}

columns และ rows ใช้เฉพาะ element ประเภท table ส่วน element อื่นไม่ต้องมี
ต้องไม่มี field อื่นนอกเหนือจาก schema นี้
"""


def analyze_pdf_page(
    pdf_path: str | Path,
    page_number: int,
    force_vision: bool = False,
    cache_dir: str | Path = "cache/vision",
    document_sha256: str | None = None,
    structured_tables: bool = False,
    use_heuristic: bool = True,
) -> VisionPageResult:
    """``use_heuristic=False``: the caller already decided this page needs vision; the
    disk cache is still read, unlike ``force_vision`` which always calls the API."""

    pdf = Path(pdf_path)

    if not pdf.exists():
        raise FileNotFoundError(pdf)

    cache_path = get_cache_path(
        pdf_path=pdf,
        page_number=page_number,
        cache_dir=cache_dir,
        document_sha256=document_sha256,
        structured_tables=structured_tables,
    )

    # 1. Check disk cache first
    if not force_vision:
        cached = load_vision_cache(cache_path)
        if cached is not None:
            return cached

    # 2. Check if Vision is actually needed
    if not force_vision and use_heuristic:
        use_vision, reason = should_use_vision(
            doc_or_path=pdf,
            page_number=page_number,
        )
        if not use_vision:
            skipped = VisionPageResult(
                has_meaningful_visual_content=False,
                summary=f"[VISION_SKIPPED] {reason}",
                elements=[],
            )
            save_vision_cache(cache_path, skipped)
            return skipped

    doc = pymupdf.open(pdf)

    try:

        if (
            page_number < 1
            or page_number > len(doc)
        ):
            raise ValueError(
                f"Page must be between 1 and {len(doc)}"
            )

        page = doc[page_number - 1]

        # ------------------------------------------
        # Render PDF page to PNG
        # ------------------------------------------

        zoom = 3

        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(
                zoom,
                zoom,
            ),
            alpha=False,
        )

        image_bytes = pixmap.tobytes("png")

    finally:
        doc.close()

    # --------------------------------------------------
    # Vision prompt
    # --------------------------------------------------

    prompt = """
วิเคราะห์ภาพของหน้าจากเอกสาร PDF ที่ให้มา

หน้าที่ของคุณคือสร้างข้อมูลที่สามารถนำไปใช้ใน Knowledge Base
และ RAG ได้ โดยครอบคลุมทั้งข้อความ ตาราง รูปภาพ diagram chart
และ visual information ที่การดึงข้อความจาก PDF อาจอ่านได้ไม่ครบ

ให้วิเคราะห์ข้อมูลจากภาพโดยตรง
และห้ามใช้ความรู้จากภายนอกเอกสาร

==================================================
1. หลักการ
==================================================

- อ่านและวิเคราะห์เฉพาะข้อมูลที่ปรากฏในภาพ
- ห้ามสร้างข้อมูลที่ไม่มีหลักฐานในภาพ
- ห้ามเดาตัวเลขหรือหน่วย
- รักษาตัวเลข หน่วย และข้อความตามต้นฉบับ
- สามารถอธิบายความหมายของ visual ได้
  เมื่อมีหลักฐานจากภาพเพียงพอ
- หากบางส่วนไม่ชัดเจน ให้ระบุความไม่แน่นอน
  แทนการเดา

จุดประสงค์ของผลลัพธ์คือ:

"สร้าง representation ที่เป็นข้อความของ visual content
เพื่อให้ระบบ RAG สามารถค้นหาและนำข้อมูลไปใช้ต่อได้"

==================================================
2. VISUAL ELEMENTS
==================================================

ระบุ visual element ที่มีสาระสำคัญ เช่น:

- table
- diagram
- chart
- photo
- image_group
- infographic
- figure
- image_text
- other

ไม่ต้องสร้าง element สำหรับ:

- โลโก้
- watermark
- หมายเลขหน้า
- background
- decoration
- branding

เว้นแต่องค์ประกอบนั้นมีข้อมูลที่เกี่ยวข้องกับเนื้อหา

==================================================
3. EXTRACTED TEXT
==================================================

extracted_text คือข้อมูลที่มองเห็นและอ่านได้จาก visual

ให้เก็บ:

- heading
- label
- caption
- paragraph
- ตัวเลข
- หน่วย
- table values
- ข้อความในภาพ
- ข้อความใน diagram
- ข้อมูลบน chart

พยายามรักษาข้อมูลตามต้นฉบับ

ห้าม:

- เปลี่ยนตัวเลข
- คำนวณตัวเลขใหม่
- เติมข้อความที่อ่านไม่ได้
- แปลงหน่วย
- สร้างข้อมูลเพื่อทำให้เนื้อหาสมบูรณ์

หากอ่านไม่ออก ให้ใช้ "[อ่านไม่ชัด]"
หรือละข้อความส่วนนั้น

==================================================
4. TABLES
==================================================

สำหรับตาราง:

- อ่านหัวตาราง
- อ่าน row และ column
- รักษาค่าตัวเลข
- รักษาหน่วย
- รักษาโครงสร้างของตาราง

extracted_text ควรทำให้สามารถเข้าใจ
ความสัมพันธ์ระหว่างหัวตาราง แถว และคอลัมน์ได้

สามารถอธิบายสิ่งที่ตารางแสดงใน:
- description
- visual_description

โดยอิงจากหัวตารางและข้อมูลที่เห็น

ห้ามเติมค่าที่ไม่มีในตาราง

==================================================
5. DIAGRAM / FIGURE / CHART
==================================================

สำหรับ diagram, figure และ chart:

ให้วิเคราะห์:

- วัตถุ
- label
- ตัวเลข
- หน่วย
- เส้น
- ลูกศร
- dimension
- axis
- legend
- annotation
- รูปทรง
- spatial arrangement
- visual grouping

สามารถอธิบายความสัมพันธ์ที่แสดงในภาพ
เมื่อมีหลักฐานชัดเจนจาก:

- label
- arrow
- line
- axis
- legend
- dimension
- caption
- table structure
- layout ของ visual

อย่าบังคับให้ทุก diagram มีความสัมพันธ์ของตัวเลข

ถ้าความสัมพันธ์ชัดเจน:
สามารถอธิบายได้

ถ้าความสัมพันธ์ไม่ชัดเจน:
เก็บตัวเลขไว้ใน extracted_text
และอธิบายเฉพาะสิ่งที่สามารถยืนยันได้

==================================================
6. DESCRIPTION
==================================================

description ต้องเป็นภาษาไทย

ให้บอกสั้น ๆ ว่า visual element นี้คืออะไร

ตัวอย่าง:

"ตารางแสดงอัตราการไหลของหัวฉีดแต่ละชนิด"

"ภาพหัวฉีดหลายชนิดพร้อมป้ายกำกับ"

"แผนภาพแสดงรูปแบบการกระจายของการฉีดพ่น"

==================================================
7. VISUAL DESCRIPTION
==================================================

visual_description ต้องเป็นภาษาไทย

ให้อธิบาย visual อย่างละเอียดพอที่จะใช้เป็น
text representation สำหรับ RAG

สามารถรวม:

- สิ่งที่ปรากฏ
- โครงสร้าง
- ข้อมูลสำคัญ
- ความสัมพันธ์ของข้อมูล
- ความหมายของ diagram
- ความหมายของ chart
- ความสัมพันธ์ของตัวเลข

แต่ทุกอย่างต้องมีหลักฐานจากภาพ

หากไม่แน่ใจ:
อย่าสร้างข้อสรุปเป็นข้อเท็จจริง

==================================================
8. SUMMARY
==================================================

summary ต้องเป็นภาษาไทย

สรุปว่า visual information ที่สำคัญของหน้านี้
เกี่ยวข้องกับอะไร

summary ควรกระชับและเหมาะสำหรับใช้เป็น
context ใน Knowledge Base

สามารถกล่าวถึงข้อมูลเชิงความหมายได้
เมื่อมีหลักฐานจากภาพรองรับ

==================================================
9. STATUS
==================================================

ใช้:

"clear"

เมื่อข้อมูลอ่านได้และตีความได้อย่างน่าเชื่อถือ

"ambiguous"

เมื่อข้อมูลบางส่วนไม่ชัดเจน
หรือความสัมพันธ์บางอย่างไม่สามารถยืนยันได้

"unreadable"

เมื่อข้อมูลสำคัญอ่านไม่ได้

==================================================
10. FINAL RULES
==================================================

- ใช้เฉพาะข้อมูลจากภาพ
- ห้ามใช้ความรู้ภายนอก
- ห้าม hallucinate
- ห้ามสร้างตัวเลข
- ห้ามแก้ตัวเลข
- ห้ามคำนวณค่าที่ไม่ได้แสดง
- สามารถตีความภาพได้เมื่อมีหลักฐานเพียงพอ
- หากข้อมูลไม่แน่นอน ให้ระบุ ambiguous
- extracted_text ต้องรักษา evidence จากภาพ
- description และ visual_description สามารถเป็น semantic
  representation สำหรับการค้นหาใน RAG

summary, description และ visual_description
ต้องเขียนเป็นภาษาไทย

Return ONLY valid JSON.

ใช้โครงสร้าง:

{
  "has_meaningful_visual_content": true,
  "summary": "...",
  "elements": [
    {
      "type": "...",
      "status": "clear",
      "description": "...",
      "extracted_text": "...",
      "visual_description": "..."
    }
  ]
}

ต้องไม่มี field อื่นนอกเหนือจาก schema นี้
"""

    if structured_tables:
        prompt = prompt.rsplit("Return ONLY valid JSON.", 1)[0] + STRUCTURED_TABLE_TAIL

    # ------------------------------------------------
    # Call Gemini
    # ------------------------------------------------

    try:

        response = generate_with_retry(
            image_bytes=image_bytes,
            prompt=prompt,
            max_retries=3,
        )

        result = parse_vision_response(
            response
        )

        save_vision_cache(
            cache_path=cache_path,
            result=result,
        )

        return result

    except Exception as exc:

        print(
            f"[analyze_pdf_page] page {page_number} failed: {exc!r}"
        )

        return VisionPageResult(
            has_meaningful_visual_content=False,
            summary=f"[VISION_EXTRACTION_FAILED] {exc}",
            elements=[],
        )
