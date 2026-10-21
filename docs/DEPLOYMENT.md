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
3. เมื่อเตรียม deploy จริงและ Docker daemon พร้อม ให้ build runtime (ไม่จำเป็นสำหรับการแก้ MD หรือทดลองหน้าเว็บในเครื่อง):

```powershell
docker compose build chatbot
```

4. Volume ใหม่ยังไม่มี KB ให้ restore snapshot ที่เหมาะสมก่อน หากต้อง ingest ใหม่ให้ทำเฉพาะขอบเขต API ที่ผู้ใช้อนุญาต คำสั่งด้านล่างเป็น reference ไม่ใช่ขั้นตอนที่ต้องรันทุกครั้ง:

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
- Readiness ไม่เรียก LLM/Tavily และไม่ยืนยัน quota ของ provider การตรวจ provider/quality สำหรับ release ต้องกำหนดขอบเขตแยก ไม่ใช่การเรียก live อัตโนมัติจาก health check
- Compose เปิด port เฉพาะ loopback ให้ reverse proxy บน host รับ HTTPS แล้วส่งเข้า `127.0.0.1:8000`
- เมื่อมี host แล้วจึงกำหนด LINE webhook เป็น `https://<production-host>/api/webhook` ตรวจ signature และทดสอบด้วยบัญชี LINE ที่ได้รับอนุญาต

Inbox รับและบันทึก event ก่อน ACK หากบริการหยุดกลางการตอบ งานที่ยังไม่ส่งจะกู้ตาม lease ส่วน reply ที่อาจส่งแล้วแต่ไม่ทราบผลจะไม่ส่งซ้ำโดยเดา การยอมรับคำขอจาก LINE ไม่ยืนยันว่าผู้ใช้ได้รับหรืออ่านข้อความ

## ใช้จริงด้วยเครื่องเจ้าของ + ngrok (เจ้าของเลือก 2026-10-21)

ฟรี เร็วสุด (CPU เต็ม) และไม่ต้องย้าย index หรือ secret ออกจากเครื่อง ข้อแลกคือเครื่องต้องเปิดและไม่หลับตลอดช่วงที่มีคนใช้
ใช้โดเมนถาวรฟรีของ ngrok (1 โดเมนต่อบัญชี) เพื่อให้ Webhook URL ไม่เปลี่ยนทุกครั้งที่เปิด ngrok ใหม่
เครื่องนี้ตั้ง authtoken ของ ngrok ไว้แล้ว (ngrok 3.39 จาก Microsoft Store, ตรวจ 2026-10-21)

1. ครั้งแรกครั้งเดียว: https://dashboard.ngrok.com/domains → ใช้โดเมนฟรีที่ได้ (เช่น `<ชื่อ>.ngrok-free.app`)
2. Terminal 1 (Git Bash ที่ root ของ repo): `.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1`
   รอ `Application startup complete` แล้ว `curl --fail http://127.0.0.1:8000/health/ready`
3. Terminal 2: `ngrok http --url=<ชื่อ>.ngrok-free.app 8000`
4. ครั้งแรกครั้งเดียว: LINE Developers Console → Messaging API → Webhook URL = `https://<ชื่อ>.ngrok-free.app/webhook`
   → Update → Verify → เปิด **Use webhook** และ **Webhook redelivery** (คิวกันข้อความซ้ำด้วย `webhookEventId` แล้ว)
5. ครั้งต่อไปทำแค่ข้อ 2–3; แก้โค้ดแล้ว Ctrl+C ที่ Terminal 1 แล้วรันใหม่ (ngrok เปิดค้างได้)
   ข้อความที่เข้ามาตอนบริการปิด ngrok ตอบ 502 แล้ว LINE ส่งซ้ำให้เองเมื่อเปิด redelivery
6. ช่วงที่มีคนใช้: Settings → System → Power → ตั้ง sleep เป็น Never (ตอนเสียบปลั๊ก) และอย่าพับจอถ้าตั้งให้พับแล้วหลับ

ไม่ใช้ host ภายนอก (ตรวจ 2026-10-21): Hugging Face Spaces แบบ Docker ต้องใช้ PRO ($9/เดือน) และ Render ฟรีได้ CPU 0.1
ซึ่งจำลองในเครื่องแล้วเริ่มบริการ ~110 วิ และค้นต่อครั้ง ~8 วิ (เครื่องเจ้าของ < 1 วิ)

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

ก่อนเปิดบริการหลัง restore ให้ตรวจจำนวนเอกสาร/หน้า, index revision, readiness และคำถามตัวอย่างที่มี citation ตรงหน้า เลือกตรวจการกู้ event และ unknown outcome แบบ offline ตามความเสี่ยงของการเปลี่ยนแปลง; การส่ง LINE จริงทำเฉพาะขอบเขตที่อนุญาต

## สถานะและขอบเขตการตรวจ

ดู [CURRENT_STATE](CURRENT_STATE.md) สำหรับสถานะล่าสุด และ [TEST_PLAN](TEST_PLAN.md) สำหรับการเลือก checks
เคย build/test Linux และตรวจ HTTP ในสภาพปิดเครือข่ายแล้ว หลักฐานอยู่ใน `archive/reports-2026-10-17/DEPLOYMENT_LINUX_HTTP_2026-10-17.json`
เป็นผลรอบก่อน ไม่ใช่การตรวจรอบ MD นี้ และไม่ยืนยันคุณภาพคำตอบหรือการส่ง LINE จริง
ยังไม่มี host จริง การเตรียม production ไม่เป็น gate ก่อนให้เจ้าของทดลองถามในเครื่อง
หากจะเปิด production ให้ตกลงขอบเขตคุณภาพและปิดข้อเสี่ยงสำคัญของรุ่นก่อน โดยไม่ขยาย live batch เอง
