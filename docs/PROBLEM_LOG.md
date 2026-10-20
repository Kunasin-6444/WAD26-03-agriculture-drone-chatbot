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

---

## ตรวจความพร้อมใช้งานจริง 2026-10-19 (Codex)

**ขอบเขตล่าสุดจากเจ้าของ (2026-10-19):** ใช้เอง ถามไม่เยอะ ใช้บริการมหาวิทยาลัยไปก่อน และยังไม่ต้องสนเรื่อง billing ดังนั้น billing, เพดานคิวสำหรับผู้ใช้จำนวนมาก และ production host ไม่ใช่เงื่อนไขก่อนใช้ส่วนตัว

**ข้อสรุปตามขอบเขตนี้:** โครงสร้างรองรับการใช้เป็นผู้ช่วยส่วนตัวเมื่อโควตาพร้อม แต่คุณภาพคำตอบยังไม่ได้ยืนยัน โดยเฉพาะความครบถ้วนและเงื่อนไขด้านสารเคมี/ความปลอดภัย งานหลักคือความถูกต้องของคำตอบและการแจ้งบริการขัดข้องให้ตรงเหตุ ปัจจุบันเจ้าของแจ้งว่าโควตา chatbot หมด รอบตรวจนี้จึงใช้โค้ดและการจำลอง offline ไม่ตรวจโควตาจริง

อ่าน requirements, current state, next steps, problem log และรายงาน audit/release เดิม แล้วตรวจ runtime ตั้งแต่ webhook → inbox → retrieval → generation/validation → web → delivery รวม config, Docker และการกู้ข้อมูล ไม่แก้โค้ดระบบ, prompt, โมเดล, gold set, `.env` หรือฐานจริง และไม่เรียก LLM/embedding/Vision/Tavily/LINE จริง

ระดับ **P1/P2** เดิมใช้ประเมินการเปิดสาธารณะ ไม่ใช่ข้อบังคับให้ทำทุกข้อก่อนใช้ส่วนตัว ขอบเขตล่าสุดให้เน้น A01–A03 และ A05–A07; A04 และ A08 เลื่อนไว้ก่อน ข้อเสนอด้านการออกแบบยังไม่ได้ลงมือหรือพิสูจน์ผล

### จุดที่มีพื้นฐานรองรับแล้ว

- LINE ตรวจ signature ก่อนบันทึก; SQLite transaction รับงานก่อน ACK, dedup ด้วย event ID, lease/claim token ช่วยกู้งานและกัน worker เก่าเขียนทับ
- แยกผลส่งสำเร็จ/ล้มเหลว/ไม่ทราบผล; ไม่ push ซ้ำเมื่อ reply อาจส่งถึงแล้ว; push retry มี key คงที่; ล้างข้อความ/token/คำตอบเมื่อจบงาน
- อ้างอิงสร้างจาก metadata ฝั่งระบบ ตรวจ source ID, quote, ตัวเลข/หน่วย/เงื่อนไขตารางบางประเภท และคงข้อเท็จจริง KB เมื่อเติม web
- จำกัดเวลา/attempt ของ provider มี cooldown และ cache เฉพาะคำตอบ KB ที่ผ่านเงื่อนไข
- Docker ใช้ผู้ใช้ที่ไม่ใช่ root, pin base image/dependencies, แยก volumes, เปิด port เฉพาะ loopback; มี local readiness และ snapshot/restore ที่ตรวจ hash

สิ่งเหล่านี้เป็นคุณสมบัติที่พบในโค้ดและมี offline contracts บางส่วน ไม่ใช่การรับรอง deployment หรือความถูกต้องทุกคำตอบ

### A01 — P1: ประโยคเกริ่นแสดงข้อเท็จจริงที่ไม่ผ่านการตรวจหลักฐานได้

**ยืนยันด้วยข้อมูลจำลองรอบนี้** — [`evidence.py`](../app/rag/evidence.py) `_intro()` บรรทัด 272 ตรวจเพียงประเภท ความยาว ตัวเลข และ URL แล้ว renderer บรรทัด 336 นำไปแสดงเหนือ claims โดยไม่ตรวจ quote/ความสอดคล้อง

Probe ส่ง claim ที่รองรับว่า “ตรวจสอบสภาพเครื่องก่อนใช้งาน” พร้อม intro จำลอง “สามารถผสมสารทุกชนิดร่วมกันได้อย่างปลอดภัย” ได้ `sufficient` และ intro ถูกแสดงจริง นี่คือข้อความผิดที่จงใจป้อนเพื่อตรวจตัวกรอง ไม่ใช่คำแนะนำ และไม่ใช่หลักฐานว่าโมเดลจริงเคยตอบเช่นนี้

แนวทาง: ให้ข้อเท็จจริงใน intro อยู่ภายใต้การตรวจเดียวกับ claims หรือออกแบบส่วนเกริ่นให้ระบบกำหนดข้อความที่ไม่บรรจุข้อเท็จจริงเอง หากเปลี่ยน prompt/รูปแบบคำตอบต้องวัดก่อนและหลังตาม AGENTS; ไม่แก้ใน audit นี้

### A02 — P1: quote ถูกต้นฉบับยังไม่รับรองว่าความหมายของ claim ถูก

**ยืนยันด้วยข้อมูลจำลองรอบนี้** — [`evidence.py`](../app/rag/evidence.py) `_parse_claim()` บรรทัด 183 และ [`claim_consistency.py`](../app/rag/claim_consistency.py) ตรวจ pattern/label หลายประเภท แต่ไม่มีการตรวจความหมายทั่วไปหรือการกลับข้อความห้ามเป็นอนุญาต

หลักฐานจำลอง “ห้ามผสมสารโดยไม่มีข้อมูลความเข้ากันได้” ถูกใช้รองรับ claim ผิด “ผสมสารทุกชนิดเข้าด้วยกันได้อย่างปลอดภัย” และ parser ยังคืน `sufficient`, 1 claim ตัวตรวจจึงช่วยลดความผิดบางประเภท แต่รับรองว่าไม่มี hallucination ไม่ได้

แนวทาง: เพิ่มกรณีทดสอบคำปฏิเสธ/ข้อห้าม/เงื่อนไขที่มีนัยความปลอดภัย และวัดความถูกต้องเชิงความหมายจากคำตอบจริงก่อนเลือกวิธีแก้ ไม่เพิ่ม LLM grader หรือขยาย prompt อัตโนมัติจาก probe ข้อเดียว

### A03 — P1: ยังไม่มีคะแนนคุณภาพของรุ่นและค่าที่จะใช้งานจริง

**ช่องว่างหลักฐานเดิมที่ยังคงอยู่** — [CURRENT_STATE](CURRENT_STATE.md) ระบุว่าลองสด 13 ข้อแล้วมีทั้งคำตอบไม่ครบ ปนบริบท และ false abstain แต่ยังไม่รันชุดวัดที่เจ้าของรับรอง ค่าที่อ่านแบบปิดบัง secrets รอบนี้คือ `gpt-5.6-terra`, timeout 25/25/40 วินาที; ไม่ใช่ผลประเมินของ `gemini-3.8-flash` ที่วางแผนเลือก

การผ่าน offline tests พิสูจน์พฤติกรรมที่ fixture ครอบคลุม ไม่ให้คะแนนความครบถ้วน/ความถูกต้องของคำตอบจริง เกณฑ์คุณภาพใน NEXT_STEPS ยังเป็นข้อเสนอ ไม่ใช่เกณฑ์ที่ตกลงและผ่านแล้ว

แนวทาง: เมื่อเจ้าของอนุมัติและโควตาพร้อม ให้ทำขั้นวัด dev/ตรวจคะแนนตาม [NEXT_STEPS](NEXT_STEPS_PLAN.md) ด้วยโมเดลเดียว ปิด fallback เก็บก่อน/หลัง และใช้ holdout ตามขอบเขตเดิม รอบนี้ไม่ใช้โควตา

### A04 — ข้อสังเกต config; เลื่อนไว้ก่อน: เมื่อ KKU ใช้ไม่ได้มีทางไป Google โดยอัตโนมัติ

**ยืนยันจากโค้ดและ config โดยไม่เรียก provider** — [`rag_service.py`](../app/rag/rag_service.py) บรรทัด 102–130 เปิด secondary เมื่อมี URL และ key และเรียง secondary ก่อน fallback ที่เหลือของ primary หลังเข้าเงื่อนไข quota/auth/transport failure

`.env` ปัจจุบันตั้ง secondary ของ `generativelanguage.googleapis.com` ไว้ครบ จึงมีทางส่งคำถามและหลักฐานออกจาก KKU ได้ ข้อนี้ไม่พิสูจน์ว่าเกิดค่าใช้จ่ายแล้ว และไม่ได้ตรวจ billing/free tier ของบัญชี Google แต่โค้ดยังไม่มีข้อบังคับว่าคำตอบต้องใช้เฉพาะ KKU ตามเงื่อนไขอาจารย์

แนวทางตามคำชี้แจงล่าสุด: ใช้บริการมหาวิทยาลัยต่อ ไม่ทำ billing audit หรือเสนอปิด secondary เป็นงานเร่งด่วน และไม่เปลี่ยน provider/`.env` ในรอบนี้ เก็บข้อเท็จจริงเรื่องเส้นทาง fallback ไว้ให้เข้าใจพฤติกรรมระบบ

### A05 — P2: retrieval/web ล่มอาจถูกแสดงเป็น “ไม่มีหลักฐานเพียงพอ”

**สถานะหลังเจ้าของอนุมัติให้ลงมือ 2026-10-19: แก้แล้วตามขอบเขต offline** — ส่งต่อรหัสเหตุขัดข้องจาก retrieval/web/LLM ถึง response และ playground; เก็บคำตอบบางส่วนพร้อมอ้างอิงเมื่อขั้นถัดไปล้ม ยังไม่ได้ยืนยันกับ provider จริง

**หลักฐานก่อนแก้จาก stub ในรอบ review** — [`crag_service.py`](../app/rag/crag_service.py) บรรทัด 90–95 ของรุ่นก่อนแก้จับ retrieval exception แต่ไม่เก็บสถานะ unavailable แบบ LLM; บรรทัด 137–138 เมื่อ web ว่างสร้างผล “No verified web evidence” แทนเหตุขัดข้อง

Probe retrieval exception + web ว่าง ได้ข้อความ “ยังไม่พบหลักฐานเพียงพอจากเอกสารและเว็บไซต์” และ `degraded=false` อีก probe ให้ web timeout ก็ได้ข้อความเดียวกัน ทั้งที่ diagnostics ระบุ `provider_timeout` จึงยังไม่ตรง R6 ทุกเส้นทาง

แนวทาง: ส่งต่อสถานะ retrieval/web unavailable จนถึง response และ UI แยกจากผลค้นสำเร็จแต่ไม่มีหลักฐาน โดยเก็บคำตอบบางส่วนที่รองรับไว้

### A06 — P2: LLM หมดโควตาแล้ว ยังเดินเส้นทาง retrieval และ web ต่อ

**สถานะหลังเจ้าของอนุมัติให้ลงมือ 2026-10-19: แก้แล้วตามขอบเขต offline** — ตรวจโมเดลทั้งหมดที่ config อนุญาตจาก cooldown ที่ทราบ ก่อนเริ่ม retrieval และก่อน web ไม่หยุดเพียงเพราะ primary ตัวเดียวหมดโควตา และยังใช้ cache/bot usage ได้ เมื่อไม่มีข้อมูลสถานะหรือเริ่ม process ใหม่ยังต้องเรียนรู้จากการเรียกตามปกติ; transient cooldown ระยะสั้นยังใช้นโยบายลองใหม่เดิม

**หลักฐานก่อนแก้จาก stub ในรอบ review** — จำลองโมเดลเดียวตอบ daily limit แล้วถามสองคำถามคนละข้อความ พบ LLM ถูกเรียกครั้งเดียวเพราะ cooldown ทำงาน แต่ retrieval ถูกเรียก 2 ครั้ง และ web search ถูกเรียก 2 ครั้ง ใน runtime retrieval นี้มี query embedding ภายนอกด้วย

ตำแหน่ง: [`crag_service.py`](../app/rag/crag_service.py) บรรทัด 88–138 และ [`rag_service.py`](../app/rag/rag_service.py) `call_llm()` ระบบลดการเรียกโมเดลที่หมดโควตาแล้ว แต่ยังไม่มีการหยุดทั้ง pipeline เมื่อไม่มีโมเดลสำหรับสร้างคำตอบเหลือ

แนวทาง: ใช้สถานะ pool unavailable หยุดงานภายนอกที่ตอบต่อไม่ได้เร็วขึ้น โดยยังอนุญาต bot usage และ cache ที่มีสิทธิ์ใช้ ต้องไม่สรุปว่า primary หมดแล้วทุก fallback หมดตามโดยไม่ตรวจสถานะที่มีอยู่

### A07 — P2: คำถาม “ตอนนี้” อาจตอบราคาจาก PDF โดยไม่บังคับหาเว็บ

**ยืนยันเงื่อนไข routing ด้วย stub รอบนี้** — [`crag_service.py`](../app/rag/crag_service.py) บรรทัด 110 ตรวจคำว่า “วันนี้/ล่าสุด/ปัจจุบัน” แต่ไม่รวม “ตอนนี้” แม้ answer cache จะรู้จักคำนี้

Probe ใช้ผล KB `sufficient` ที่รองรับราคาจำลอง แล้วถาม “ตอนนี้โดรนรุ่นตัวอย่างราคาเท่าไร” ได้ `knowledge_base`, web calls = 0 นี่พิสูจน์ช่องว่างของกฎ routing เมื่อโมเดลคืน sufficient ไม่ใช่ความถี่ของคำตอบราคาผิดจริง และการมีเว็บเพียงอย่างเดียวก็ยังไม่รับรองวันที่ของข้อมูล

แนวทาง: ใช้นโยบาย freshness ร่วมกันระหว่าง cache/routing/generation และตรวจว่าหลักฐานมีช่วงเวลารองรับคำถาม

### A08 — เลื่อนไว้ก่อนสำหรับการใช้ส่วนตัว: จำนวน worker จำกัดงานพร้อมกัน แต่ยังไม่คุมอัตรารับงานและอายุคิว

**พบจาก static review; ไม่ได้ load test** — [`webhook.py`](../app/api/webhook.py) รับ event ที่ signature ถูกต้อง; [`line_inbox.py`](../app/services/line_inbox.py) `add_events()` บรรทัด 115 บันทึก event ใหม่โดยไม่มีเพดานต่อผู้ใช้/คิว ส่วน `_run()` จำกัดเพียง concurrency (ค่าเริ่มต้น 3) และ `_deliver()` ไม่ตัดงานตามอายุ `received_at`

ผู้ใช้จริงที่ส่งคำถามไม่ซ้ำจำนวนมากจึงเพิ่มคิวและใช้โควตาจนกระทบคนอื่นได้ งานเก่าอาจยังสร้างคำตอบแล้วไป push fallback หลังรอนาน `prune()` ลบเฉพาะ terminal rows และถูกเรียกตอน start จึงไม่ใช่การควบคุม backlog

แนวทาง: กำหนดงบคำถามต่อผู้ใช้/ช่วงเวลา, เพดาน pending, อายุงาน และพฤติกรรมแจ้งเมื่อบริการเต็มก่อนเปิดรับวงกว้าง ไม่จำเป็นต้องเพิ่ม Redis/หลายโฮสต์เพื่อแก้เรื่องนี้

### A09 — P2: embedding ล่มทำให้ค้น KB ไม่ได้ แม้ BM25 ทำงานในเครื่องได้

**พบจาก static review และสัมพันธ์กับ probe A05** — [`slide_retriever.py`](../app/rag/slide_retriever.py) บรรทัด 301 เรียก Google query embedding ก่อน dense query และก่อน `_apply_global_bm25()` บรรทัด 355 ไม่มีทางไปค้นแบบ lexical อย่างเดียวเมื่อ embedding exception

ดังนั้น KB เก็บในเครื่องไม่ได้แปลว่าค้นได้เมื่อ Google ใช้ไม่ได้ และอาจหลุดไป web ทั้งที่เอกสารมีคำตอบ แนวทาง: ประเมิน BM25-only fallback ที่แจ้งสถานะ degraded และรักษา source scope โดยตรวจ retrieval คุณภาพก่อนเลือกใช้ ไม่เปลี่ยน embedding model หรือ re-ingest ทั้งคลังใน audit นี้

### ข้อจำกัดด้านการเปิดบริการที่ยังต้องยืนยัน

- `/health/ready` ตรวจเฉพาะ index/inbox/worker; `external_providers=not_probed` เป็นการออกแบบที่ช่วยไม่ใช้โควตา health ผ่านจึงไม่แปลว่าบอตตอบได้ ขณะนี้ยังไม่มีภาพรวมแจ้งเตือน quota, backlog age และอัตราส่งล้มเหลวให้ผู้ดูแลจาก runtime หลัก
- ยังไม่มีหลักฐานรอบนี้ของ host/HTTPS/reverse proxy, LINE end-to-end หรือความจุตามจำนวนผู้ใช้จริง ใช้ขั้น deploy เมื่อมีโฮสต์และขอบเขตอนุมัติ ไม่ต้องมี production host ก่อนทดลองในเครื่อง
- Legacy table และภาพหน้า 38 ที่อ่านไม่ได้ยังเป็นข้อจำกัดตาม CURRENT_STATE; รอบนี้ไม่เปิดฐานจริงนับ chunks และไม่อ้างผล ingestion รอบก่อนเป็นผลใหม่
- Publisher เตรียม embeddings ก่อน upsert และลบ stale หลัง upsert แต่ไม่ใช่การสลับ index ทั้งชุดแบบ transaction; คงการสำรองและหยุด app/ingestion ตามคู่มือเมื่อย้ายข้อมูล ไม่ได้ทดสอบ crash ระหว่าง publish ในรอบนี้
- `PROBLEM_LOG` ข้อ 1–4 เป็นบันทึกเก่า คำว่า Resolved และ latency ~8–10 วินาทีในข้อ 3 ไม่รับรอง latency ของรุ่น/โมเดลปัจจุบัน

### การตรวจที่ทำจริงและวิธีทำซ้ำ

คำสั่งเฉพาะส่วน (fixtures ปิดเครือข่ายภายนอกและใช้ฐานชั่วคราวผ่าน `tests/__init__.py`):

```powershell
.venv/Scripts/python.exe -B -m pytest -q tests/test_line_inbox_contract.py tests/test_health_contract.py tests/test_llm_degraded_contract.py tests/test_llm_cooldown_policy_contract.py tests/test_llm_budget_contract.py tests/test_evidence_contract.py tests/test_answer_cache_contract.py tests/test_query_and_web_policy_contract.py -p no:cacheprovider
.venv/Scripts/python.exe -B -m pip check
.venv/Scripts/python.exe -B scratch/readiness_review_20261019.py
```

- **88 passed, 22 subtests passed**, 40.78 วินาที; มี 1 Starlette/AnyIO deprecation warning ไม่ใช่ test failure
- `pip check`: **No broken requirements found** ตรวจความสอดคล้อง dependency ที่ติดตั้ง ไม่ใช่ vulnerability scan
- สคริปต์ probe เป็น artifact ใน `scratch/` ของเครื่องนี้ (git ignore) ใช้ข้อมูลสมมติ ไม่อ่าน gold/holdout ไม่เปิดฐานจริง และปิด external network ก่อนเรียกส่วน runtime; อ่าน config เฉพาะค่าที่ไม่ใช่ secrets
- ไม่รัน full suite, live evaluation, quota check, ingestion, Docker build, load test, penetration test หรือ dependency advisory scan การตรวจนี้ไม่ใช่ใบรับรองมาตรฐานภายนอก

ลำดับแก้/วัดชุดเดียวอยู่ที่ [NEXT_STEPS_PLAN](NEXT_STEPS_PLAN.md) ไม่ถือว่าข้อเสนอในรายงานนี้แก้เสร็จแล้ว

### ผลตรวจหลังแก้ A05–A06 ตามคำอนุญาตเจ้าของ (2026-10-19)

เพิ่ม `app/service_status.py` สำหรับรหัส/ข้อความที่ปลอดภัยและแยก KKU daily-limit 401 ออกจาก auth error; เพิ่ม `error_code` ในผล pipeline และส่งต่อเหตุจาก exception ที่ถูก wrap โดยไม่เผยรายละเอียดลับ ปรับ playground/evaluator ให้รู้จักข้อความใหม่ ไม่เปลี่ยนรูปแบบคำตอบปกติหรือกฎตรวจข้อเท็จจริง

Regression ใหม่อยู่ที่ `tests/test_service_availability_contract.py`: empty results กับ outage ให้ผลต่างกัน, partial KB/อ้างอิงยังอยู่เมื่อ web/final generation ล้ม, pool หมดหยุดงานภายนอก, fallback/secondary ที่ยังพร้อมไม่ถูกบล็อก, cooldown หมดอายุแล้วลองได้, cache/bot usage ยังใช้ได้ และ UI ไม่เปลี่ยน daily-limit เป็นคีย์เสีย

- ชุดหลัก 11 ไฟล์: **106 tests + 36 subtests ผ่าน**, 7.04 วินาที
- หลังปรับเพิ่มกรณี timeout และตรวจ LINE integration: **53 tests + 22 subtests ผ่าน**, 8.98 วินาที ชุดนี้ทับซ้อนชุดแรก ไม่ใช่จำนวนข้อไม่ซ้ำเพิ่มเติม
- ทั้งสองรอบมี Starlette/AnyIO deprecation warning เดิม 1 รายการ ไม่ใช่ failure; ไม่เรียก API/live/quota check ไม่รัน full suite ไม่เปลี่ยน `.env`/prompt/model/gold/index

ทำซ้ำชุดตรวจล่าสุดได้ด้วย:

```powershell
.venv/Scripts/python.exe -B -m pytest -q tests/test_service_availability_contract.py tests/test_line_integration_contract.py tests/test_llm_cooldown_policy_contract.py tests/test_llm_failover_contract.py tests/test_playground.py -p no:cacheprovider
```
