> Historical snapshot before the 2026-10-17 MD overhaul. Not current instructions or status. Relative Markdown links rebased for this location.

# ทดลองสร้างเวกเตอร์จาก PDF โดยตรง

โหมด `direct` ส่ง PDF ต้นฉบับครั้งละหนึ่งหน้าเข้า `gemini-embedding-2`
โดยใช้ PyMuPDF สำหรับแบ่งหน้าเท่านั้น ไม่มีการเรียก Vision หรือดึงข้อความ/ตารางก่อนสร้างเวกเตอร์
แต่ละเวกเตอร์เก็บชื่อไฟล์ เลขหน้า โมเดล และ SHA-256 ของ PDF หน้านั้น

โหมดนี้ใช้ collection `drone_pdf_pages_v1` แยกจาก `drone_knowledge` ของระบบเดิม
ค่าเริ่มต้นยังเป็น `PDF_RETRIEVAL_MODE=text` เพื่อให้ทดลองเทียบผลก่อนเปิดใช้กับบอต

แผนงานถัดไปและเกณฑ์ตัดสินใจเปลี่ยนค่าเริ่มต้น: [NEXT_STEPS_PLAN.md](../../../NEXT_STEPS_PLAN.md)

## การค้นหาและตอบ

1. สร้างเวกเตอร์คำถามแล้วค้นหา PDF แต่ละหน้าด้วย dense retrieval
2. อ่านเฉพาะหน้าที่ค้นเจอผ่าน `PDF_READER_MODEL` (เริ่มต้น `gemini-3.5-flash-lite`)
3. ให้โมเดลถอดข้อความ ตัวเลข หน่วย และความสัมพันธ์ในตารางเป็นหลักฐาน
4. ส่งหลักฐานเข้ากระบวนการตอบและตรวจคำอ้างอิงเดิม พร้อมชื่อไฟล์และเลขหน้าต้นฉบับ

เวกเตอร์เองไม่มีข้อความสำหรับอ้างอิง จึงยังมีขั้นตอนอ่านเอกสารตอนตอบ
ข้อความที่ถอดจาก PDF เป็นผลจากโมเดลและอาจอ่านผิดได้ ต้องตรวจตัวเลขกับต้นฉบับในการประเมินจริง
โหมดนี้ไม่ใช้ BM25 เพราะไม่ได้ดึงข้อความของทุกหน้ามาทำดัชนี

เก็บ PDF รายหน้าและแคช embedding/transcript ใน `cache/direct_pdf/`
แคช embedding อิง hash ของ PDF และโมเดล ส่วนแคช transcript แยกตาม hash/reader model/version
PDF ที่ใช้ตอบเป็น snapshot เดียวกับที่สร้างเวกเตอร์ แม้ไฟล์ใน `data/` จะถูกแก้ภายหลัง
ต้องเก็บ directory นี้คู่กับ ChromaDB เมื่อย้ายเครื่องหรือ deploy

## ทดลองหนึ่งหน้าก่อน

รันจาก root ของ repository ใน PowerShell:

```powershell
$pdfPath = (Get-ChildItem -LiteralPath data -Filter 'UAV07*.pdf').FullName
.venv/Scripts/python.exe -m scripts.ingest_pdf "$pdfPath" UAV07 --mode direct --pages 12
```

คำสั่งทดสอบ API จริงด้านล่างใช้ collection/cache แยกสำหรับ smoke test เท่านั้น
ตรวจการสร้างเวกเตอร์ ค้นหน้า อ่านตาราง และตอบพร้อมอ้างอิง โดยไม่มีการส่งข้อความ LINE:

```powershell
.venv/Scripts/python.exe -m scripts.smoke_direct_pdf
```

ดูผลใน `docs/DIRECT_PDF_SMOKE_REPORT.json` การทดสอบหนึ่งหน้าไม่สามารถสรุปคุณภาพการค้นหาได้

ผลทดสอบจริงวันที่ 2026-10-16: ค้นและอ่านตาราง UAV07 หน้า 12 ได้ ตอบอัตราการไหล 500 ml/หัวฉีด
ที่ 1600 rpm พร้อมอ้างหน้าเดิม รอบที่ยังไม่มี transcript cache ใช้เวลาค้นและอ่านประมาณ 10.0 วินาที
และสร้างคำตอบอีก 4.5 วินาที จึงยังไม่สรุปว่าโหมดใหม่เร็วกว่าระบบเดิม
การสร้างเวกเตอร์จาก PDF ครั้งแรกใน probe นี้ใช้ประมาณ 3.5 วินาทีต่อหนึ่งหน้า เป็นเพียงตัวอย่างครั้งเดียว

รอบที่มีแคช (`docs/DIRECT_PDF_WARM_SMOKE_REPORT.json`) ค้นและอ่านใช้ 0.750 วินาที
โดยเรียก query embedding หนึ่งครั้ง ไม่เรียก PDF embedding หรือ PDF reader ซ้ำ
การตอบใช้ 5.984 วินาทีและได้สถานะ `partial` จึงไม่ผ่าน smoke criterion ที่กำหนดให้ตอบครบ:
ตอบตัวเลข 500 ml/หัวฉีด ที่ 1600 rpm พร้อมอ้างอิงได้ แต่ไม่ยืนยันหน่วยเวลา เช่น ml/นาที
ตรวจภาพต้นฉบับหน้า 12 แล้ว หัวตารางระบุปริมาณ ml/หัวฉีด โดยไม่มีหน่วยเวลา
ผลนี้จึงควรเก็บไว้เป็นข้อจำกัดของการตอบคำถามอัตราการไหลจากหลักฐานหน้านี้ ไม่แก้โดยเติมหน่วยเอง

Offline verification: `python -m pytest -q tests -p no:cacheprovider` ผ่าน **162 tests และ 41 subtests**
มี warning เดิมจาก Starlette/AnyIO หนึ่งรายการ และ `scripts.verify_ingestion` ยืนยันว่า collection
เดิมยังมี 774 chunks พร้อมผ่าน integrity check

## นำเข้าครบและเปรียบเทียบ

หลังตรวจหน้าตัวอย่างแล้ว:

```powershell
.venv/Scripts/python.exe -m scripts.ingest_all_data --mode direct
.venv/Scripts/python.exe -m scripts.eval_retrieval --config global/none --verbose --output docs/RETRIEVAL_TEXT_REPORT.json
.venv/Scripts/python.exe -m scripts.eval_retrieval --mode direct --verbose --output docs/RETRIEVAL_DIRECT_REPORT.json
```

การประเมินใช้คำถามและ gold predicates ชุดเดิมใน `tests/data/retrieval_gold.json`
และอ้างอิง gold pages จากข้อความใน collection เดิม รายงาน direct จะแสดงจำนวนหน้าที่ทำดัชนีแล้ว
ต้องใช้เอกสารครบชุดเดียวกันจึงจะเปรียบเทียบได้ และต้องตรวจความแม่นของคำตอบจากตารางเพิ่มเติม
สคริปต์นี้วัดเฉพาะ retrieval โดยใช้ timeout สำหรับ evaluation ที่มากกว่าบอตจริง

## เปิดใช้กับบอต

หลังเปรียบเทียบผลแล้ว ตั้งค่าใน `.env` และ restart application:

```dotenv
PDF_RETRIEVAL_MODE=direct
PDF_READER_MODEL=gemini-3.5-flash-lite
PDF_READ_MAX_PAGES=3
PDF_READ_TIMEOUT_SECONDS=10
```

กลับไปใช้ระบบเดิมได้โดยตั้ง `PDF_RETRIEVAL_MODE=text` แล้ว restart
การนำเข้ารองรับ `--mode text` หรือ `--mode direct` แยกจากโหมดค้นหาเสมอ

## ข้อจำกัดและพฤติกรรมเมื่อผิดพลาด

- ครั้งแรกที่ถามถึงหน้าซึ่งยังไม่มี transcript จะมี API call เพิ่ม จึงอาจช้ากว่าระบบเดิม
- จำกัดการอ่านเริ่มต้นสามหน้าต่อคำถาม (ปรับได้ 1–6 หน้า) และสงวนเวลาแปดวินาทีสำหรับการตอบใน CRAG
- API timeout เป็น request budget ไม่ใช่การรับประกัน latency ของระบบทั้งหมด
- Gemini ไม่รับ generation deadline ที่ต่ำกว่า 10 วินาที จึงตั้ง `PDF_READ_TIMEOUT_SECONDS` อย่างน้อย 10
  หากเวลาเหลือไม่พอ จะใช้เฉพาะ transcript ที่แคชแล้ว
- เมื่ออ่านหน้าไม่ได้หรือผลลัพธ์ไม่ครบ จะใช้ได้เฉพาะหลักฐานที่แคชสำเร็จแล้ว จากนั้น CRAG จัดการ web fallback/abstain ตามเดิม
- ก่อน publish เวกเตอร์ ต้องสร้าง embedding ของหน้าที่ขอให้ครบก่อน; API ล้มเหลวระหว่างทางไม่ลบข้อมูลที่ publish แล้ว
- นำเข้าไฟล์ครบทุกหน้าจะลบหน้าที่เกินจากเวอร์ชันเก่า; `--pages` แทนที่เฉพาะหน้าที่ระบุ
- หลังแก้ไฟล์ต้นฉบับควรนำเข้าไฟล์ครบ เพื่อไม่ให้หน้าอื่นยังอ้าง snapshot เวอร์ชันก่อน
- ขีดจำกัด Gemini Embedding 2 คือ 8,192 tokens ต่อ input แม้ส่งเพียงหน้าเดียวก็อาจเกินได้สำหรับหน้าที่แน่นมาก
  Gemini Developer API อาจตัด input ที่เกินโดยไม่แจ้ง ต้องตรวจการครอบคลุมเนื้อหาในการประเมิน
- การถอด PDF ด้วยโมเดลอาจตกหล่นหรืออ่านผิด การตรวจ quote ยืนยันกับ transcript ไม่ได้ยืนยันว่าถอดตรงกับต้นฉบับทุกตัว

เอกสารอ้างอิง: [Google PDF embeddings](https://ai.google.dev/gemini-api/docs/embeddings#embedding-documents)
