# Agriculture Drone Chatbot

แชตบอตภาษาไทยสำหรับความรู้โดรนเกษตร ใช้เอกสารเป็นหลัก ค้นเว็บเติมข้อมูลที่ขาด และอ้างอิงหลักฐานที่ใช้จริง

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
