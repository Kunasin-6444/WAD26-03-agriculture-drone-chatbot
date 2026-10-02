# Learning Log

บันทึกประวัติการเรียนรู้ ความเข้าใจ จุดแข็ง และสิ่งที่ต้องทบทวนของ Developer ในแต่ละหัวข้อ

---

## Session 1: Day 1 - Topic 1: Project Goal + User Flow
- **วันที่**: 2026-09-27
- **สถานะ**: Completed (ผ่านการประเมินความเข้าใจ 100%)
- **หัวข้อ**: เป้าหมายของระบบโดรนเกษตร, ปัญหาที่แก้, Flow การเดินทางของข้อความจากผู้ใช้ผ่าน LINE จนถึงคำตอบ
- **สิ่งที่เข้าใจแล้ว**:
  1. เข้าใจปัญหา Hallucination ของ AI ทั่วไป และความจำเป็นของการทำ Grounded RAG บนคู่มือเฉพาะ
  2. เข้าใจและอธิบายหลักการ Zero-Hallucination & Strict Abstain เมื่อหาข้อมูลไม่พบได้ถูกต้อง
  3. ไล่เรียงไฟล์และ Data Flow ได้ถูกต้อง: `app/main.py` -> `app/api/webhook.py` -> `app/services/ai_service.py` -> `app/services/line_service.py`
  4. เข้าใจเหตุผลของการมี Dummy Token Filter และ Message Length Guard
- **สิ่งที่ได้เรียนรู้เพิ่มเติม**:
  - ได้อธิบายเหตุผลของการเผื่อ Safety Margin ที่ 4,950 ตัวอักษร (แทนที่จะตัดที่ 5,000 พอดี) เพื่อป้องกันปัญหา Unicode/Surrogate pair ใน UTF-16 ของ Messaging API และการต่อท้ายข้อความ/escape sequences ใน JSON

---

## Session 2: Day 1 - Topic 2: Backend Architecture + Repository Structure
- **วันที่**: 2026-09-27
- **สถานะ**: Completed (ผ่านการประเมินความเข้าใจ 100%)
- **หัวข้อ**: Layered Architecture, ขอบเขตความรับผิดชอบของโฟลเดอร์ใน `app/`, Plain Python vs LangChain, Environment Variables
- **สิ่งที่เข้าใจแล้ว**:
  1. แยกแยะความแตกต่างระหว่าง Offline pipeline (`app/ingestion/`) สำหรับเตรียมและเก็บข้อมูลลง ChromaDB กับ Online pipeline (`app/rag/`) สำหรับค้นหาและตอบคำถามแบบเรียลไทม์ได้ชัดเจน
  2. เข้าใจเหตุผลของการเลือกใช้ Plain Python (ควบคุมระบบและ Debug ง่ายกว่า ไม่ถูกซ่อน Abstraction)
  3. อธิบายความแตกต่างของ `LINE_CHANNEL_SECRET` (ตรวจลายเซ็น Request ขาเข้า) และ `LINE_CHANNEL_ACCESS_TOKEN` (สิทธิ์ Authorization ขาออก) ได้ถูกต้องแม่นยำ
- **สิ่งที่ได้เรียนรู้เพิ่มเติม**:
  - การเตรียมคำตอบสำหรับสอบปากเปล่าเรื่อง Plain Python: เน้นย้ำเรื่อง Transparency, Latency control, และ No hidden prompt injection

---

## Session 3: Day 1 - Topic 3: PDF Ingestion
- **วันที่**: 2026-09-27
- **สถานะ**: Completed (ผ่านการประเมินความเข้าใจ 100%)
- **หัวข้อ**: การสกัดข้อมูลจาก PDF, Native Tables, การแปลงแถวเป็น Pipe-separated Text, Bounding Box De-duplication, Deterministic Unit ID, และข้อยกเว้น Rule R1 (Air Law)
- **สิ่งที่เข้าใจแล้ว**:
  1. เข้าใจเหตุผลของการแปลงตารางเป็น Pipe-separated text (`|`) เพื่อคงความสัมพันธ์เชิงความหมาย (Semantic structure) ของแถวและคอลัมน์ให้กับ Embedding model และ LLM
  2. อธิบายเทคนิค Bounding Box de-duplication ได้ถูกต้อง ว่านำพิกัดตารางมาคัดแยกบล็อกข้อความซ้ำซ้อนออก
  3. เข้าใจเหตุผลของกฎ Rule R1 ที่ยกเว้น `UAV01 Air Law.pdf` และ `UA03 AIR SPACE.pdf` เพราะกฎหมายและเขตพื้นที่การบินอัปเดตบ่อย ต้องใช้ข้อมูลทางการสดใหม่จาก CAAT UAS Portal แทน
- **สิ่งที่ได้เรียนรู้เพิ่มเติม**:
  - การใช้ SHA-1 แฮชสร้าง Deterministic ID ทำให้การรัน Ingestion ซ้ำไม่มีปัญหา DuplicateIDError ใน ChromaDB

---

## Session 4: Day 1 - Topic 4: Vision Extraction & Selective Ingestion
- **วันที่**: 2026-09-27
- **สถานะ**: Completed (ผ่านการประเมินความเข้าใจ 100%)
- **หัวข้อ**: Selective Vision Heuristic, High-Resolution Rendering (zoom=3), Structured Output (Pydantic), Disk Caching (`cache/vision/`), และ Rate Limit Retry
- **สิ่งที่เข้าใจแล้ว**:
  1. เข้าใจปัญหา 429 Resource Exhausted จากการยิง Vision API ทุกหน้าแบบ Brute-force
  2. อธิบายเงื่อนไข Selective Heuristic ได้ชัดเจน (`text_chars < 150`, `image_area_ratio >= 0.70`, full-page visual)
  3. เข้าใจวัตถุประสงค์ของแคชทั้ง 2 ระดับในระบบ
- **สิ่งที่ได้เรียนรู้เพิ่มเติม**:
  - แยกแยะชัดเจนระหว่าง Disk Cache ใน Ingestion (`cache/vision/` เก็บผล Vision เพื่อรัน Re-ingest ซ้ำได้โดยไม่เสียโควตา) กับ In-Memory Model Cache ใน Query Pipeline (`_EXHAUSTED_MODELS` ใน `rag_service.py` ดักโมเดลติด 401 ข้ามไปโมเดลที่เร็วทันที)

---

## Session 5: Day 1 - Topic 5: KnowledgeUnit (Data Contract)
- **วันที่**: 2026-09-27
- **สถานะ**: Completed (ผ่านการประเมินความเข้าใจ 100%)
- **หัวข้อ**: หน้าที่ของ `KnowledgeUnit` ในฐานะ Data Contract กลาง (Intermediate Representation), ฟิลด์สำคัญสำหรับการทำ Traceability (`source_file`, `page_number`), และฟิลด์ `content` สำหรับสร้างเวกเตอร์
- **สิ่งที่เข้าใจแล้ว**:
  1. เข้าใจประโยชน์ของการมีโมเดลมาตรฐานกลางเพื่อจัดระเบียบข้อมูลหลายรูปแบบ (Text, Table, Vision) ก่อนส่งต่อให้ Chunking
  2. ระบุฟิลด์ `source_file` และ `page_number` สำหรับการอ้างอิงแหล่งที่มาตาม Requirement ได้ถูกต้อง
  3. เข้าใจว่าฟิลด์ `content` คือข้อความหลักที่จะถูกนำไปคำนวณเป็นเวกเตอร์และใช้ในการค้นหาแบบ Semantic Search
- **สิ่งที่ได้เรียนรู้เพิ่มเติม**:
  - การตรวจสอบโค้ดจริงพบว่า `page_analyzer.py` เป็น Diagnostic Tool ของ `scripts/analyze_pdf.py` ส่วน Production Pipeline จริงใช้ `should_use_vision()` ใน `vision_extractor.py` โดยตรง ทำให้เห็นภาพ Source of Truth ชัดเจนขึ้น

---

## Session 6: Day 1 - Topic 6: Chunking
- **วันที่**: 2026-09-27
- **สถานะ**: Completed (ผ่านการประเมินความเข้าใจ 100%)
- **หัวข้อ**: Chunk Size (800), Chunk Overlap (120), การป้องกันการตัดขาดของบริบทประโยค, Structured Unit Protection (ตาราง <= 1200 ตัวอักษรไม่ถูกหั่น), และ Metadata Inheritance
- **สิ่งที่เข้าใจแล้ว**:
  1. เข้าใจประโยชน์ของ Overlap ในการป้องกันการสูญเสียบริบทและความหมายของประโยคบริเวณรอยต่อ
  2. เข้าใจและอธิบายเหตุผลของการคงรูปข้อมูลตาราง/ไดอะแกรม/ชาร์ตไว้ทั้งผืน เพื่อไม่ให้แถวหลุดออกจากหัวตาราง
  3. เข้าใจการส่งต่อ Metadata เข้าสู่ ChromaDB
- **สิ่งที่ได้เรียนรู้เพิ่มเติม**:
  - ได้ทำความเข้าใจความแตกต่างระหว่าง Typed Attributes ในคลาส `Chunk` (เพื่อ Type Safety / Autocomplete ในโค้ด Python) กับ `metadata: dict[str, str]` (เพื่อส่งเข้า ChromaDB API `collection.upsert(metadatas=...)`)
  - ยืนยันชัดเจนว่าสิ่งที่ถูกนำไป Embed มีเพียง `chunk.content` เท่านั้น ส่วน Metadata เก็บเป็นคู่ Attribute ไว้ข้างเวกเตอร์ ไม่ได้ถูกนำไปแปลงเป็นเวกเตอร์

---

## Session 7: Day 1 - Topic 7: Embedding
- **วันที่**: 2026-09-27
- **สถานะ**: Completed (ผ่านการประเมินความเข้าใจ 100%)
- **หัวข้อ**: Gemini Embedding 2 (`gemini-embedding-2`), มิติ 3072 มิติ, หลักการ Semantic Similarity (Cosine Distance), จังหวะการใช้งาน (Ingestion vs Query Time), และ Exponential Backoff Retry (5s -> 10s -> 20s)
- **สิ่งที่เข้าใจแล้ว**:
  1. ระบุโมเดล `gemini-embedding-2` และขนาด 3,072 มิติได้อย่างถูกต้อง
  2. เข้าใจการทำงาน 2 จังหวะ: Ingestion Time (แปลง chunk ข้อความเป็นเวกเตอร์หยอดใส่ ChromaDB) และ Query Time (แปลงคำถามของผู้ใช้เป็นเวกเตอร์เพื่อไปเทียบระยะห่าง)
  3. อธิบายหลักการเวกเตอร์ใกล้เคียงกันเมื่อมีความหมายคล้ายกัน (เช่น "nozzle สีส้ม" กับ "หัวฉีดส้ม") แม้จะสะกดคนละคำได้ถูกต้องแม่นยำ
- **สิ่งที่ได้เรียนรู้เพิ่มเติม**:
  - การจัดการ ServerError (500, 502, 503, 504) แบบเฉพาะเจาะจงเพื่อความเสถียรของ Ingestion Pipeline

---

## Session 8: Day 1 - Topic 8: ChromaDB (Vector Store)
- **วันที่**: 2026-09-27
- **สถานะ**: Completed (ผ่านการประเมินความเข้าใจ 100% - จบ Day 1 ครบทุกหัวข้อ)
- **หัวข้อ**: Chroma PersistentClient vs In-Memory, Collection `drone_knowledge`, การบันทึกด้วย `collection.upsert()`, การป้องกัน Duplicate ID, และสิ่งที่ Chroma คืนค่ากลับมาจากการสืบค้น
- **สิ่งที่เข้าใจแล้ว**:
  1. เข้าใจประโยชน์ของ `PersistentClient` ที่บันทึกข้อมูลลงฮาร์ดดิสก์ ทำให้เซิร์ฟเวอร์เปิดใหม่แล้วพร้อมใช้งานทันที ไม่ต้องรัน Ingest ใหม่
  2. ระบุ 4 องค์ประกอบที่ส่งเข้า `collection.upsert()` ได้แม่นยำ: `ids`, `documents`, `embeddings`, `metadatas`
  3. เข้าใจชัดเจนว่า Chroma คืนค่าผลลัพธ์เป็น Dictionary ที่ประกอบด้วย `documents` (ข้อความภาษาไทยจริง), `metadatas` (ชื่อไฟล์และเลขหน้า), และ `distances` (ระยะห่างทางคณิตศาสตร์) ไม่ได้ส่งเวกเตอร์ดิบไปให้ LLM
- **สรุปภาพรวม Day 1**:
  - Developer สามารถไล่เรียงและอธิบาย Data Flow ทั้งหมดตั้งแต่ไฟล์ PDF ดิบ -> การสกัด Text/Table/Vision -> KnowledgeUnit -> Chunks -> Embeddings -> ChromaDB ได้อย่างเข้าใจแท้จริงตามหลักฐานในโค้ดจริง 100%
