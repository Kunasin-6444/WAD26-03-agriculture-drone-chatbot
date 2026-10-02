# Project Code Guide

คู่มืออธิบายโครงสร้างซอร์สโค้ด หน้าที่ของแต่ละโมดูล Input, Output, Data Flow และการทำงานร่วมกัน สำหรับการสอบและดูแลรักษาระบบ

---

## สารบัญโมดูล

1. **API & Webhook Entrypoint** (`app/api/`, `app/main.py`)
2. **Services Layer** (`app/services/`)
3. **Configuration & Environment** (`app/config.py`)
4. **Data Ingestion & Multimodal Processing** (`app/ingestion/`)
5. **RAG & Vector Storage** (`app/rag/`)

---

## 1. API & Webhook Layer

### `app/main.py`
- **หน้าที่ (Responsibility)**: Entrypoint ของ FastAPI Application สำหรับรันเซิร์ฟเวอร์
- **สิ่งที่ทำ**: ลงทะเบียน Router จาก `app/api/webhook.py` และให้บริการ Health check endpoint ที่ `GET /`

### `app/api/webhook.py`
- **หน้าที่ (Responsibility)**: รับ Webhook Request จาก LINE Platform
- **Input**:
  - `Request`: HTTP POST request body (JSON)
  - `x-line-signature` (Header): ลายเซ็นดิจิทัลสำหรับตรวจสอบความถูกต้อง
- **Output**: JSON `{"status": "OK"}`
- **Data Flow**:
  1. นำ Request body และ signature ส่งให้ `WebhookParser` ตรวจสอบความถูกต้อง
  2. สกัด `MessageEvent` และข้อความ `TextMessageContent`
  3. ส่ง `user_message` ไปประมวลผลที่ `ask_ai()` ใน `app/services/ai_service.py`
  4. นำคำตอบส่งกลับหาผู้ใช้ผ่าน `reply_text()` ใน `app/services/line_service.py`
- **Error Handling**:
  - ตรวจจับ `InvalidSignatureError` และโยน HTTP 400 Bad Request
  - หาก `ask_ai()` ขัดข้อง จะตอบกลับข้อความสุภาพขออภัย โดยไม่ทำให้ Webhook ล่ม

---

## 2. Services Layer

### `app/services/ai_service.py`
- **หน้าที่ (Responsibility)**: Facade / Abstraction Layer ระหว่าง Webhook กับระบบ RAG
- **ฟังก์ชันสำคัญ**: `ask_ai(user_message: str) -> str`
- **สิ่งที่ทำ**: เรียก `run_crag_pipeline(user_message)` และส่งออกเฉพาะข้อความคำตอบสุดท้าย

### `app/services/line_service.py`
- **หน้าที่ (Responsibility)**: ส่งข้อความตอบกลับไปยังผู้ใช้ผ่าน LINE Messaging API
- **ฟังก์ชันสำคัญ**: `reply_text(reply_token: str, text: str) -> bool`
- **จุดสำคัญด้านความปลอดภัย (Defensive Design)**:
  1. กรอง dummy tokens ที่ LINE Developers Console ใช้ ping ทดสอบ (`00000000000000000000000000000000`, `ffffffffffffffffffffffffffffffff`) ไม่ให้ระบบพยายามส่งข้อความหา token ปลอม
  2. จำกัดความยาวข้อความไม่เกิน 4,950 ตัวอักษร เพื่อป้องกันข้อผิดพลาด HTTP 400 จากขีดจำกัด 5,000 ตัวอักษรของ LINE Messaging API

---

## 3. Ingestion Layer

### `app/ingestion/models.py`
- **หน้าที่ (Responsibility)**: กำหนด Schema มาตรฐานกลาง (Data Contract / Intermediate Representation) สำหรับเนื้อหาที่สกัดได้จาก PDF ก่อนส่งเข้า Chunking
- **โมเดลสำคัญ**:
  - `KnowledgeUnit`:
    - `id`: รหัสเอกลักษณ์ของหน่วยความรู้ (Deterministic SHA-1 Hash)
    - `source_file`, `page_number`: ข้อมูลระบุแหล่งที่มาตามข้อกำหนด Traceability
    - `source_type`: ประเภทของแหล่งข้อมูล (`text`, `table`, `image`, `diagram`, `chart`, `mixed`)
    - `content`: ข้อความที่ผ่านการจัดโครงสร้างแล้ว สำหรับนำไป Chunk และคำนวณเวกเตอร์
    - `extracted_text`, `visual_description`: หลักฐานข้อความดิบและคำอธิบายจาก Vision
    - `metadata`: ข้อมูลกำกับเพิ่มเติมสำหรับส่งต่อให้ ChromaDB

### `scripts/ingest_pdf.py`
- **หน้าที่ (Responsibility)**: สคริปต์ CLI รันการแปลงเอกสาร PDF ทั้งเล่มหรือแบบระบุช่วงหน้าเข้าสู่ ChromaDB
- **Flow**:
  1. เปิดไฟล์ PDF นับจำนวนหน้าด้วย PyMuPDF
  2. วนลูปทีละหน้า เรียก `analyze_pdf_page()` เพื่อวิเคราะห์ภาพ/ตาราง (Vision)
  3. เรียก `build_page_knowledge_units()` เพื่อสร้าง `list[KnowledgeUnit]`
  4. ทำ Chunking ด้วย `chunk_knowledge_units()` (ขนาด 800 ตัวอักษร, overlap 120)
  5. ฝังเวกเตอร์และบันทึกลง ChromaDB ด้วย `add_chunks()`

### `app/ingestion/knowledge_builder.py`
- **หน้าที่ (Responsibility)**: แกะองค์ประกอบในระดับหน้า PDF (Text, Native Tables, Vision) แล้วรวมเป็น `KnowledgeUnit`
- **ฟังก์ชันสำคัญ**:
  - `make_unit_id(document_id, page_number, source_type, index, source_origin)`: สร้าง ID แบบระบุตัวตนแน่นอน (Deterministic ID) ด้วย SHA-1 ป้องกันปัญหา ID ชนกันใน ChromaDB
  - `rows_to_text(rows)`: แปลงตาราง 2 มิติให้อยู่ในรูปข้อความที่มีท่อคั่น (`Header | Col\nVal | Val`) เพื่อคงความสัมพันธ์ของข้อมูล
  - `extract_native_tables(page)`: ดึงตารางที่ PyMuPDF ตรวจจับได้อัตโนมัติ
  - `build_page_knowledge_units(...)`:
    - ค้นหาพิกัดตาราง (`tab_rects`)
    - กรองข้อความทั่วไปโดยตัดบล็อกที่ทับซ้อนกับพิกัดตารางออก (De-duplication)
    - รวมผลลัพธ์จาก Text, Table, และ Vision กลายเป็นชุด `KnowledgeUnit` ประจำหน้า

### `app/ingestion/page_analyzer.py`
- **หน้าที่ (Responsibility)**: โมดูลเครื่องมือวินิจฉัย (Standalone Diagnostic Tool) สำหรับวิเคราะห์สถิติภาพรวมของหน้า PDF
- **การใช้งานจริง**: ถูกเรียกใช้เฉพาะจาก `scripts/analyze_pdf.py` เพื่อพิมพ์รายงานสรุปสถิติตัวอักษรและรูปภาพในหน้า PDF สำหรับตรวจสอบก่อน Ingestion
- **หมายเหตุสถาปัตยกรรม**: ใน Production Ingestion Loop จริง (`scripts/ingest_pdf.py`) ระบบใช้ฟังก์ชัน `should_use_vision()` ที่อยู่ใน `app/ingestion/vision_extractor.py` โดยตรง ไม่ได้ผ่านโมดูลนี้

### `app/ingestion/vision_extractor.py`
- **หน้าที่ (Responsibility)**: สกัดข้อมูลสาระสำคัญจากรูปภาพ แผนภาพ และตารางสแกนด้วย Gemini Vision
- **ความสามารถสำคัญ**:
  - `analyze_pdf_page(...)`: ตรวจสอบ Disk Cache ก่อน หากไม่มีจึงตรวจสอบ Selective Heuristic ถ้าผ่านเกณฑ์จะเรนเดอร์เป็นภาพความละเอียดสูง 300 DPI (`zoom=3`)
  - ใช้ Pydantic Structured Output ผ่านโมเดล `VisionPageResult` และ `VisualElement`
  - มีระบบหน่วงเวลา Exponential Backoff สำหรับดักจับ Rate Limit 429
  - บันทึกผลลัพธ์ลงแคชที่ `cache/vision/<doc_name>/page_<n>.json`

---

## 4. RAG & Vector Storage Layer

### `app/rag/chunking.py`
- **หน้าที่ (Responsibility)**: แบ่งข้อความจาก `KnowledgeUnit` ให้เป็น `Chunk` ย่อยที่เหมาะกับการคำนวณเวกเตอร์และการค้นหา
- **พารามิเตอร์มาตรฐาน (Baseline)**:
  - `chunk_size = 800`: ขนาดตัวอักษรต่อชิ้น
  - `chunk_overlap = 120`: ตัวอักษรที่ซ้อนทับกันระหว่างชิ้นที่ติดกัน
- **ฟังก์ชันและเทคนิคสำคัญ**:
  - `split_text(text, chunk_size, chunk_overlap)`: ใช้วิธี Sliding Window (`start = end - chunk_overlap`) เพื่อรักษาความต่อเนื่องของประโยคบริเวณรอยต่อ
  - `chunk_knowledge_unit(unit)`: มีการป้องกันพิเศษ (**Structured Unit Protection**) หากเป็นข้อมูลประเภท `table`, `diagram`, `chart` ที่ยาวไม่เกิน 1,200 ตัวอักษร จะคงไว้ทั้งผืน ไม่หั่นซอย เพื่อไม่ให้ข้อมูลสเปกหลุดออกจากหัวตาราง
  - ถ่ายทอด `document_id`, `source_file`, `page_number`, `source_type` ไปเป็นทั้ง Typed Attributes ของคลาส `Chunk` และ `metadata: dict[str, str]` สำหรับส่งเข้า ChromaDB

### `app/rag/embedding.py`
- **หน้าที่ (Responsibility)**: สื่อสารกับ Google GenAI SDK เพื่อแปลงข้อความเป็นเวกเตอร์ความหมาย 3,072 มิติ
- **การตั้งค่าสำคัญ**:
  - `EMBEDDING_MODEL = "gemini-embedding-2"`
  - มิติเวกเตอร์ (Dimension): 3,072
- **ฟังก์ชันสำคัญ**:
  - `embed_text(text)`: ส่งข้อความเข้ารับชุดตัวเลขทศนิยม (`list[float]`) จาก Gemini
  - มีระบบหน่วงเวลา Exponential Backoff สำหรับ ServerError ชั่วคราว (HTTP 500, 502, 503, 504) โดยรอ 5s -> 10s -> 20s
- **จุดที่ถูกเรียกใช้งาน**:
  1. `app/rag/vector_store.py`: ใน `add_chunks()` เพื่อแปลง `chunk.content` ก่อนบันทึกลง ChromaDB
  2. `app/rag/rag_service.py`: ใน `retrieve_context()` เพื่อแปลงคำถามของผู้ใช้เป็น Query Vector ก่อนค้นหา

### `app/rag/vector_store.py`
- **หน้าที่ (Responsibility)**: จัดการการเชื่อมต่อ จัดเก็บเวกเตอร์ และสืบค้นแบบความหมาย (Semantic Search) บนฐานข้อมูล ChromaDB
- **การตั้งค่าสำคัญ**:
  - `CHROMA_PATH = Path("chroma_db")`: จัดเก็บข้อมูลแบบ Local Persistent บนดิสก์
  - `COLLECTION_NAME = "drone_knowledge"`: ชื่อคอลเลกชันหลักสำหรับจัดเก็บความรู้โดรนเกษตร
- **ฟังก์ชันสำคัญ**:
  - `add_chunks(chunks)`:
    - รับ `list[Chunk]`
    - ตรวจจับและแก้ปัญหา Duplicate ID ภายในแบทช์
    - เรียก `embed_text()` เพื่อแปลงข้อความเป็นเวกเตอร์ 3,072 มิติ
    - สั่ง `collection.upsert(ids, documents, embeddings, metadatas)` บันทึกลงดิสก์
  - `search(query, n_results=5)`:
    - แปลงคำถามของผู้ใช้เป็น Query Vector ด้วย `embed_text()`
    - สั่ง `collection.query()` ค้นหาชิ้นที่ใกล้เคียงที่สุดตาม Cosine Similarity
    - คืนค่าผลลัพธ์เป็น Dictionary ที่ประกอบด้วย `documents`, `metadatas`, และ `distances`

---

*(โมดูล RAG, CRAG, Grader, Web Fallback จะถูกเพิ่มเติมใน Day 2 และ Day 3)*
