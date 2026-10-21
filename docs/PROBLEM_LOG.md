# Problem Log

บันทึกปัญหาที่เกิดขึ้นจริงระหว่างการพัฒนาและการทดสอบ (ห้ามสร้างปัญหาปลอม ทุกปัญหาต้องมีหลักฐานและบันทึกการแก้ไขจริง)

---

## ปัญหาที่ 1: Google Gemini Vision Free-tier Quota หมด (HTTP 429 Resource Exhausted)
- **วันที่พบ**: ช่วงพัฒนา Ingestion Pipeline
- **สถานะ**: Resolved (แก้ไขแล้ว)
- **อาการ / ผลกระทบ**: เมื่อรันสคริปต์ดึงข้อมูลจาก PDF ทั้งเล่มผ่าน Gemini Vision API ระบบติด Rate Limit (429) ทำให้ Ingestion พังกลางคัน
- **หลักฐาน (Evidence)**: รหัสข้อผิดพลาด 429 `RESOURCE_EXHAUSTED` จาก Google GenAI SDK
- **สาเหตุรากเหง้า (Root Cause)**: หน้ากระดาษส่วนใหญ่เป็นตัวหนังสือทั่วไป แต่ระบบส่งทุกหน้าไปประมวลผล Vision ทำให้โควตา Request ต่อนาทีและต่อวันหมดลงอย่างรวดเร็ว
- **วิธีแก้ไข (Resolution)**:
  1. สร้าง Selective Vision Heuristic ใน `app/ingestion/vision_extractor.py` คัดกรองหน้าที่มีรูปภาพขนาดใหญ่ (>150x150) หรือ vector drawing ซับซ้อนเท่านั้นที่จะส่งไป Vision API หน้าที่เป็นข้อความธรรมดาใช้ PyMuPDF ดึงตรง (0 API cost, เร็วกว่า 100 เท่า)
  2. เพิ่ม Disk Cache เก็บผลลัพธ์ Vision ลงที่ `cache/vision/<doc_name>/page_<n>.json` ทำให้เมื่อรันซ้ำไม่ต้องเสียโควตาซ้ำ

---

## ปัญหาที่ 2: Grader เข้มงวดเกินไปจนปฏิเสธข้อมูลสเปกทางเทคนิค (False Abstain)
- **วันที่พบ**: 2026-09-24
- **สถานะ**: Resolved (แก้ไขแล้ว)
- **อาการ / ผลกระทบ**: ถามคำถาม "พัดส้มกับพัดน้ำเงินใช้ต่างกันยังไง" (ข้อมูลหัวฉีด) ระบบดึง Chunks มาได้ถูกต้องสมบูรณ์ แต่บอทกลับตอบว่า "ขออภัยครับ ไม่พบข้อมูล..." (Abstain)
- **หลักฐาน (Evidence)**: Log ใน `crag_grader.py` พบว่าโมเดลประเมิน Chunks ที่มีตารางอัตราการไหลและขนาดละอองฝอยว่า `INCORRECT` เพราะมองหาข้อความเปรียบเทียบตรงตัวคำว่า "ใช้ต่างกันอย่างไร"
- **สาเหตุรากเหง้า (Root Cause)**: Prompt ของ CRAG Grader กำหนดเงื่อนไขเข้มงวดเกินไป ขาดคำสั่งชี้นำให้โมเดลพิจารณาตัวเลขสเปกทางเทคนิค (เช่น อัตราการไหล, ขนาดละออง, ความถี่การใช้) ว่าเป็นข้อมูลที่ตอบคำถามเปรียบเทียบได้
- **วิธีแก้ไข (Resolution)**:
  - ปรับ Prompt ใน `app/rag/crag_grader.py` ให้ระบุชัดเจนว่า หากในบริบทมีคุณลักษณะทางเทคนิคที่สามารถนำมาเปรียบเทียบหรือตอบคำถามได้ ให้ตัดสินเป็น `CORRECT` ทันที

---

## ปัญหาที่ 3: Latency ตอบกลับสูงถึง 30-50 วินาที
- **วันที่พบ**: 2026-09-24
- **สถานะ**: Resolved (แก้ไขแล้ว ปัจจุบันอยู่ที่ ~8-10 วินาที)
- **อาการ / ผลกระทบ**: ผู้ใช้ส่งข้อความใน LINE แต่ต้องรอนานเกิน 30-50 วินาทีจนอาจเกิด Webhook Timeout หรือผู้ใช้คิดว่าระบบค้าง
- **หลักฐาน (Evidence)**: สคริปต์จับเวลา Profiling ใน `scratch/measure_latency_steps.py`
- **สาเหตุรากเหง้า (Root Cause)**:
  1. โมเดลเริ่มต้นบางตัวบน KKU GenAI (`gemini-3.5-flash-lite`, `qwen3.6-flash`) โควตาหมด (HTTP 401) ทำให้เสียเวลา Fallback วนซ้ำทุก Request
  2. Tavily Web Fallback ตั้งค่า `search_depth="advanced"` ซึ่งใช้เวลาดึงและ scrape หน้าเว็บนาน 8-15 วินาที
  3. Prompt ของ Grader ส่ง context ยาวเกินไปทำให้ LLM ใช้เวลาประมวลผลนาน
- **วิธีแก้ไข (Resolution)**:
  1. เพิ่มระบบ In-Memory Model Cache ใน `app/rag/rag_service.py` เมื่อโมเดลใดติด 401 จะขึ้นบัญชีพักไว้ 10 นาที ข้ามไปเรียกโมเดลที่เสถียร (`gpt-5.6-luna`, `nova-2-lite-v1`) ทันที
  2. ปรับ Tavily ให้ใช้ `search_depth="basic"`
  3. ตัดทอน Context ของ Grader ให้กะทัดรัด (จำกัด 2,500 ตัวอักษร)

---

## ปัญหาที่ 4: ความซ้ำซ้อนและการไม่ได้ใช้งานของ `page_analyzer.py` ใน Production Ingestion
- **วันที่พบ**: 2026-09-27 (ตรวจพบระหว่างการ Review โค้ดจริง)
- **สถานะ**: Documented & Clarified (ชี้แจงสถานะชัดเจน)
- **อาการ / ข้อเท็จจริง**: `app/ingestion/page_analyzer.py` ไม่ได้ถูกเรียกใช้ใน `scripts/ingest_pdf.py` หรือ `vision_extractor.py`
- **หลักฐาน (Evidence)**:
  - การค้นหา `grep_search` พบว่า `page_analyzer.py` ถูกเรียกใช้เพียงจุดเดียวคือ `scripts/analyze_pdf.py` (สคริปต์ CLI สำหรับพิมพ์สถิติตรวจสอบหน้า PDF)
  - ใน Production Ingestion Pipeline จริง (`scripts/ingest_pdf.py`) มีฟังก์ชัน Selective Heuristic ที่ถูกเขียนไว้ใน `app/ingestion/vision_extractor.py` ชื่อว่า `should_use_vision()` ซึ่งทำงานโดยตรงอยู่แล้ว
- **ข้อสรุป (Conclusion)**:
  - `app/ingestion/page_analyzer.py` เป็น Standalone Diagnostic Tool สำหรับสคริปต์ `scripts/analyze_pdf.py` เท่านั้น ไม่ใช่แกนหลักของ Production Ingestion Pipeline
  - ตรวจสอบและอัปเดตเอกสาร `docs/PROJECT_CODE_GUIDE.md` ให้ระบุบทบาทที่แท้จริง ไม่ให้เกิดความเข้าใจผิด
