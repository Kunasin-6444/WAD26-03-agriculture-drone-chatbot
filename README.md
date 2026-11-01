# Agriculture Drone Chatbot

แชตบอตภาษาไทยสำหรับความรู้โดรนเกษตร ใช้เอกสารเป็นหลัก หากเอกสารตอบไม่ได้จึงค้นเว็บและตอบจากเว็บเพียงแหล่งประเภทเดียว พร้อมอ้างอิงหลักฐานที่ใช้จริง

เริ่มที่ [สารบัญเอกสาร](docs/README.md), [ข้อกำหนด](docs/PROJECT_REQUIREMENTS.md), [สถานะจริง](docs/CURRENT_STATE.md) และ [งานถัดไป](docs/NEXT_STEPS_PLAN.md)
แนวทางทำงานสำหรับ AI อยู่ที่ [AGENTS.md](AGENTS.md)

## ทดลองระบบ

มีหน้าทดลองถามตอบในเครื่องแล้ว เปิดด้วยคำสั่งนี้จากโฟลเดอร์โปรเจกต์:

```powershell
.venv/Scripts/python.exe -m scripts.playground
```

เปิด **http://127.0.0.1:8080** แล้วพิมพ์คำถาม เริ่มต้นเป็นโหมด **ข้อมูลจำลอง** ใช้ได้แม้ไม่มี quota/credentials
เลือกจำลอง KB+web, KB อย่างเดียว, หลักฐานไม่พอ หรือ quota หมดได้ คำตอบและแหล่งอ้างอิงในโหมดนี้ไม่ใช่ข้อมูลจริง

เมื่อ quota พร้อม เลือก **ถามระบบจริง** แล้วกดส่ง จะใช้ `ask_ai` เดียวกับ LINE ผ่าน config/KB ในเครื่อง
แสดงคำตอบ ชื่อไฟล์/หน้า ลิงก์ web ตรงหน้าที่ใช้ และเวลาประมวลผล ไม่มีการเรียก API จากการเปิดหน้า/เปลี่ยนโหมด
คำถามจริงใช้ API ตามปกติ รวม fallback ของ pipeline เดิม หน้าทดลองไม่เพิ่มการ retry หรือส่ง batch เอง
ครั้งแรกอาจช้าจากการโหลดโมดูล/index; เวลาโหมดจำลองไม่ใช่ latency ของโมเดล

ตั้งแต่ 2026-10-25 ระบบตอบแต่ละคำถามแยกกัน ไม่จำหัวข้อก่อนหน้าและไม่บังคับถามกลับให้เลือกหัวข้อ
ตั้งแต่ 2026-11-01 ถอดแคชคำตอบและการแชร์คำตอบระหว่างคำถามที่เข้าพร้อมกันแล้ว ถามข้อความเดิมเป็นข้อความใหม่จะประมวลผลใหม่; rich menu ยังคงใช้คู่มือสำเร็จรูป ส่วนคิว SQLite ป้องกันเฉพาะ LINE ส่ง event เดิมซ้ำ
โมเดลหลักกำหนดด้วย `RAG_MODEL` ใน `.env` (ค่าที่ตรวจล่าสุดคือ `gemini-3.5-flash-lite` ผ่าน KKU และมี fallback ตาม `LLM_FALLBACK_MODELS`) หลังเปลี่ยนโค้ด/ค่าใน `.env` ต้องเริ่ม process ใหม่; Docker ต้อง build และ recreate ตามคู่มือ deployment เพื่อโหลดโค้ดและ environment ใหม่
ระบุพืช/งาน/อุปกรณ์ในคำถามให้ครบ เช่น “หัวฉีดพัดส้มมีอัตราการไหลเท่าไร” แทน “แล้วไหลเท่าไร”
รุ่นส่งใช้ `exclusive_pipeline`: เลือก KB หรือเว็บต่อคำตอบ ไม่รวมหลักฐานสองประเภท คำถามกฎหมาย/ข้อมูลปัจจุบันใช้เว็บ คำถามที่รวมงานจากเอกสารกับข้อมูลปัจจุบันจะขอให้แยกถาม หากยังยืนยันไม่ได้จะระบุข้อจำกัด

Playground ไม่เปิด LINE worker ไม่อ่าน inbox และไม่บันทึกประวัติสนทนา รับฟังเฉพาะ `127.0.0.1`
หยุดด้วย `Ctrl+C` หรือเปลี่ยน port ด้วย `--port 8081` หาก 8080 ถูกใช้อยู่
ห้ามนำ playground ไปเปิดสาธารณะ ใช้ [deployment](docs/DEPLOYMENT.md) สำหรับบริการ LINE

## Backend สำหรับ LINE

ถ้ามี dependencies และ `.env` อยู่แล้ว สามารถเปิด backend ในเครื่องได้:

```powershell
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
curl.exe --fail http://127.0.0.1:8000/health/live
curl.exe --fail http://127.0.0.1:8000/health/ready
```

คำสั่งนี้เปิดบริการจริงรวม worker ของ LINE ซึ่งอาจประมวลผลงานค้างใน inbox หากใช้ state เดิม ใช้คำสั่ง playground ด้านบนสำหรับทดลองโดยไม่ส่ง LINE
Health endpoints ไม่ได้ส่งคำถามหา LLM และไม่ได้ยืนยันว่า provider มี quota ดู [การเตรียม deploy](docs/DEPLOYMENT.md)
ยังไม่มีโฮสต์ production และยังไม่ผ่านการยืนยันคุณภาพคำตอบทั้งหมด

## Docker สำหรับข้อมูลเดิม

เปิด Docker Desktop ให้ engine พร้อม หยุด backend/ingestion เดิมและสำรองข้อมูลก่อน แล้วใช้ `.env`, `chroma_db/` และ `cache/` เดิม:

```bash
docker compose -f compose.yaml -f compose.storage.yaml config --quiet
docker compose -f compose.yaml -f compose.storage.yaml up -d --build --wait chatbot
curl --fail http://127.0.0.1:8000/health/ready
```

คำสั่งเปิด worker จริงและอาจประมวลผล LINE ค้าง ดูวิธี smoke ด้วย inbox ชั่วคราวและการย้ายไป Linux host ใน [DEPLOYMENT](docs/DEPLOYMENT.md)
Compose เดี่ยวใช้ named volumes ใหม่ที่ยังไม่มี KB; ใช้ `-f` ทั้งสองไฟล์ด้านบนสำหรับฐานข้อมูลที่มีอยู่แล้ว
