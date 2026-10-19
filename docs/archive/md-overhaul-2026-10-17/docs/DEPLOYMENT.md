> Historical snapshot before the 2026-10-17 MD overhaul. Not current instructions or status. Relative Markdown links rebased for this location.

# เตรียม deploy บน Linux host เครื่องเดียว

ขอบเขตรอบนี้คือเตรียมแพ็กเกจและตรวจให้พร้อม deploy ตามที่ผู้ใช้ระบุว่ายังไม่มีโฮสต์ จึงยังไม่มี production URL หรือผลส่งข้อความ LINE จริง

## ข้อมูลที่ต้องเก็บถาวร

| Volume | ข้อมูล | หน้าที่ |
| --- | --- | --- |
| `knowledge` → `/app/chroma_db` | Chroma SQLite, vector segments, embedding cache | ฐานความรู้ |
| `state` → `/app/cache` | LINE inbox SQLite และ direct PDF snapshots/transcripts | งานค้าง การป้องกันซ้ำ และหลักฐาน PDF |

ใช้ 1 host และ 1 Uvicorn worker เป็นค่าเริ่มต้น Worker ของ LINE มี concurrency ที่ตั้งผ่าน `LINE_WORKER_CONCURRENCY` ไม่ใช้ shared SQLite ข้ามหลาย host

## ก่อนเริ่มบริการ

1. เตรียม `.env` จาก `.env.example` ใส่ credential จริงบน host และกำหนดสิทธิ์ไฟล์ให้เฉพาะผู้ดูแล ห้ามนำ credential เข้า image
2. ใช้ `PDF_RETRIEVAL_MODE=text` สำหรับ release ปัจจุบัน และใช้ config retrieval ที่ผ่านรายงานประเมินล่าสุด
3. Build และตรวจ clean install/tests เมื่อ Docker daemon พร้อม:

```powershell
docker build --target test -t drone-chatbot:test .
docker compose build chatbot
```

4. Volume ใหม่ยังไม่มี KB ต้อง restore snapshot ที่ตรวจแล้ว หรือ ingest จาก PDF ใน image ก่อนเปิดรับผู้ใช้ การ ingest ใช้ API และต้องตรวจรายงานการดึงข้อมูลครบทุกหน้า:

```powershell
docker compose run --rm chatbot python -B -m scripts.ingest --dry-run
docker compose run --rm chatbot python -B -m scripts.ingest
docker compose run --rm chatbot python -B -m scripts.verify_ingestion
docker compose up -d chatbot
```

หากนำ index เดิมไปใช้ ให้ย้ายทั้ง directory รวม vector segments และกำหนด `KB_REVISION` ตาม index ที่ publish; ห้ามคัดลอกเฉพาะ `chroma.sqlite3`

## ตรวจบริการและเชื่อม LINE

```powershell
curl.exe --fail http://127.0.0.1:8000/health/live
curl.exe --fail http://127.0.0.1:8000/health/ready
docker compose logs --tail 100 chatbot
```

- `/health/live`: process ตอบ HTTP ได้
- `/health/ready`: index มีข้อมูล, inbox อ่าน/เขียนได้ และ worker ทำงาน; คืน 503 หากไม่พร้อม ไม่แสดงข้อความผู้ใช้หรือ credential
- Readiness ไม่เรียก LLM/Tavily และไม่ยืนยัน quota ของ provider ต้องตรวจ live acceptance และ quota แยกก่อนรับ traffic
- Compose เปิด port เฉพาะ loopback ให้ reverse proxy บน host รับ HTTPS แล้วส่งเข้า `127.0.0.1:8000`
- เมื่อมี host แล้วจึงกำหนด LINE webhook เป็น `https://<production-host>/api/webhook` ตรวจ signature และทดสอบด้วยบัญชี LINE ที่ได้รับอนุญาต

Inbox รับและบันทึก event ก่อน ACK หากบริการหยุดกลางการตอบ งานที่ยังไม่ส่งจะกู้ตาม lease ส่วน reply ที่อาจส่งแล้วแต่ไม่ทราบผลจะไม่ส่งซ้ำโดยเดา การยอมรับคำขอจาก LINE ไม่ยืนยันว่าผู้ใช้ได้รับหรืออ่านข้อความ

## Backup และ restore

เครื่องมือ `scripts.storage_snapshot` ตรวจ SHA-256 ทุกไฟล์ ไม่ทับปลายทางเดิม และ restore ลง directory ใหม่เท่านั้น Snapshot อาจมีข้อความผู้ใช้ที่ยังค้าง จึงต้องจำกัดสิทธิ์และอายุการเก็บตามนโยบายของผู้ใช้งาน

ต้องหยุดทั้ง app และ ingestion ก่อน backup เพื่อให้ SQLite กับ vector segments เป็นสถานะเดียวกัน ตัวอย่างบนเครื่องพัฒนา:

```powershell
.venv/Scripts/python.exe -B -m scripts.storage_snapshot backup --quiesced --output cache/backup-release-01
.venv/Scripts/python.exe -B -m scripts.storage_snapshot restore --snapshot cache/backup-release-01 --destination cache/restore-check-01
```

บน Compose ให้หยุดบริการและงาน ingest แล้วใช้ one-off container โดย mount directory backup ของ host เพิ่มเข้า `/backups`:

```powershell
docker compose stop chatbot
docker compose run --rm -v ./backups:/backups chatbot python -B -m scripts.storage_snapshot backup --quiesced --output /backups/release-01
docker compose run --rm -v ./backups:/backups chatbot python -B -m scripts.storage_snapshot restore --snapshot /backups/release-01 --destination /backups/restore-check-01
docker compose start chatbot
```

เตรียมสิทธิ์ของ directory `backups` ให้ UID/GID 10001 เขียนได้ก่อนรันบน Linux ผล restore มี `chroma_db/` และ `cache/` ให้ตรวจ integrity ในสภาพแวดล้อมแยก แล้วจึงนำข้อมูลไปยัง volume ของ deployment ใหม่ที่หยุดอยู่ ห้ามทับฐานข้อมูลของ app ที่กำลังทำงาน

ก่อนเปิดบริการหลัง restore ให้ตรวจจำนวนเอกสาร/หน้า, index revision, readiness และคำถามตัวอย่างที่มี citation ตรงหน้า ทดสอบการกู้ event และ unknown outcome ด้วยชุด offline ก่อนทดสอบ LINE จริง

## สถานะการตรวจ

ดู [ผลตรวจรุ่นปัจจุบัน](../../../RELEASE_READINESS_2026-10-17.md) ใช้ `scripts.ingest` สำหรับ text pipeline ปัจจุบันและตรวจรายงาน complete/degraded ทุกไฟล์ การผ่าน native integrity ไม่ยืนยันว่าอ่านภาพครบ

Build test/runtime บน Linux ผ่านแล้ว runtime ใช้ UID 10001 และตรวจ HTTP ตาม CMD จริงแบบปิดเครือข่ายแล้ว ดู `DEPLOYMENT_LINUX_HTTP_2026-10-17.json` ใน docs การทดสอบใช้สำเนา KB และ inbox ใหม่ ไม่มี production inbox หรือ LINE ส่งจริง **quality gate ด้านคำตอบ/latency ยังไม่ผ่านทั้งหมด** จึงควรปิด gate นี้ก่อนเปิดให้ผู้ใช้จริง

ผล build image, clean install บน Linux และการทดสอบบน host จริงต้องบันทึกแยกจากผล pytest บน Windows ถ้า Docker daemon ไม่ทำงาน ยังนับว่า build image ผ่านไม่ได้ ดูผลรอบล่าสุดในรายงาน implementation
