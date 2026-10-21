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

## Render (Docker ฟรี) — เตรียม 2026-10-21

**ทำไมไม่ใช่ Hugging Face Spaces:** ตั้งแต่ปี 2026 Space แบบ Docker/Gradio บน CPU ฟรีต้องสมัคร PRO ($9/เดือน)
(สร้างแล้วได้ `402 ... requires a PRO subscription`) ผิดเงื่อนไขห้ามใช้บริการเสียเงิน — ใช้ HF แค่เก็บ index ใน dataset private

**ภาพรวม**
- Render สร้าง image จาก GitHub ตาม `render.yaml` + `deploy/render/Dockerfile` (มีแค่ `app/`, คู่มือ rich menu, `scripts/fetch_index.py` ไม่มี PDF/เทสต์/เอกสาร)
- index (`chroma_db` = เนื้อหาเอกสาร) ไม่อยู่ใน git: เก็บใน dataset private `Kunasin/agri-drone-index`
  ตอนเริ่ม `scripts/fetch_index.py` ดาวน์โหลดด้วย `HF_TOKEN` (~10 วิ); ไม่มี index และไม่ตั้ง `HF_INDEX_REPO` → ไม่ยอมเริ่ม
- ฟรี ไม่ต้องใช้บัตร: RAM 512 MB (ใช้ ~250 MB), CPU 0.1, 750 ชม./เดือน, ดิสก์ชั่วคราว (คิว LINE หายเมื่อ restart/deploy/หลับ)
- **หลับหลังไม่มีคนเรียก 15 นาที** ปลุกราว 1 นาที + เริ่มบริการ — ต้องมีตัวปลุก (ข้อ 6) ไม่งั้นข้อความแรกหลังหลับจะช้าหรือหลุด
- **ช้ากว่าเครื่องเจ้าของ:** ลองในเครื่องด้วย `--cpus 0.1 --memory 512m` (2026-10-21): เริ่มบริการ ~110 วิ (เต็ม CPU 12 วิ),
  ค้นหนึ่งครั้ง ~8 วิ (เต็ม CPU < 1 วิ) → คำตอบช้าขึ้นราว 15–20 วิ และตอบทีละข้อความ ถ้าคนถามพร้อมกันหลายคนจะต่อคิว
  วันทดสอบจริงที่คนใช้พร้อมกันเยอะ พิจารณาสลับ Webhook URL ไปเครื่องเจ้าของ + ngrok ชั่วคราว แล้วสลับกลับ
- ต้องเช็กหลัง deploy: server ของ Render (สิงคโปร์) เรียก KKU Gen AI ได้ไหม

**ขั้นตอน (เจ้าของทำ)** — index อัปโหลดเข้า dataset แล้ว 2026-10-21 (982 ชิ้น)
1. Token อ่าน index: https://huggingface.co/settings/tokens → Create new token → **Fine-grained** ชื่อ `render-read-index`
   → Repositories permissions เลือก `Kunasin/agri-drone-index` → ติ๊ก **Read access to contents of selected repos** → Create (เห็นครั้งเดียว)
2. สมัคร https://dashboard.render.com/register ด้วย **GitHub** (ไม่ต้องใส่บัตร) แล้วอนุญาต Render เข้า repo `WAD26-03-agriculture-drone-chatbot`
3. Dashboard → **New → Blueprint** → เลือก repo → Branch ที่มี `render.yaml` (ตอนนี้ `wip/ingest-v2-eval-2026-10-19`; `main` ยังไม่มีจนกว่าจะ merge)
   → Render อ่าน `render.yaml` แล้วขอค่า secret 8 ตัว: `HF_TOKEN` (token จากข้อ 1), `LINE_CHANNEL_SECRET`, `LINE_CHANNEL_ACCESS_TOKEN`,
   `API_KEY`, `GOOGLE_API_KEY`, `TAVILY_API_KEY`, `LLM_SECONDARY_BASE_URL`, `LLM_SECONDARY_API_KEY` — คัดลอกจาก `.env`
   **เฉพาะค่า ไม่เอาเครื่องหมายคำพูดหรือ comment** → Apply (ค่าที่ไม่ลับเช่นชื่อโมเดลอยู่ใน `render.yaml` แล้ว)
4. รอ build ครั้งแรก ~5–10 นาที: Logs ต้องเห็น `index downloaded from Kunasin/agri-drone-index` แล้ว `Uvicorn running on ...:10000`
5. เปิด `https://<ชื่อ service>.onrender.com/health/ready` (URL อยู่บนหัวหน้า service) ต้องได้ 200
6. ตัวปลุก: https://cron-job.org (ฟรี) → Create cronjob → URL `https://<ชื่อ service>.onrender.com/health/live` → ทุก 10 นาที
   (เปิดตลอดเดือนใช้ ~744 ชม. ไม่เกิน 750 ชม. ของ Render; อย่าสร้าง service ฟรีตัวที่สองใน workspace เดียวกัน)
7. LINE Developers Console → Messaging API → Webhook URL = `https://<ชื่อ service>.onrender.com/webhook` → Update → Verify
   → เปิด **Use webhook** และ **Webhook redelivery** (ระบบคิวกันข้อความซ้ำด้วย `webhookEventId` แล้ว)
   → ลองพิมพ์ "เมนู" และถามคำถามจริง 1 ข้อ ถ้าตอบว่าบริการขัดข้อง ดู Logs ว่าเรียก KKU ได้ไหม

**อัปเดตครั้งต่อไป**
- โค้ด: push เข้า branch ที่ผูกไว้ → หน้า service กด **Manual Deploy → Deploy latest commit**
  (`autoDeployTrigger: "off"` จนส่งงาน 2 พ.ย.; อยากให้ deploy เองทุก push เปลี่ยนเป็น `"commit"` ใน `render.yaml` = CI/CD)
- index ใหม่ (หลัง ingest): `.venv/Scripts/python.exe -m scripts.build_index_bundle` →
  `.venv/Scripts/hf.exe upload Kunasin/agri-drone-index ../agriculture-drone-chatbot-hf-index . --repo-type dataset`
  → Render กด **Manual Deploy → Restart service** (ดิสก์ชั่วคราว เริ่มใหม่จึงดาวน์โหลด index ใหม่เอง)
- เลี่ยง deploy ช่วงที่คนกำลังใช้ (ระหว่างเริ่มใหม่ ~2 นาทีตอบไม่ได้)

**ลองในเครื่องก่อน** (Docker Desktop, รันจาก root ของ repo):
`docker build -f deploy/render/Dockerfile -t agri-render .` แล้ว
`docker run --rm -p 10000:10000 --cpus 0.1 --memory 512m --env-file <ไฟล์ env ที่ไม่มี comment/quote> -v "<โฟลเดอร์ index จาก build_index_bundle>:/app/chroma_db" agri-render`
— `--env-file` ของ docker ไม่ตัด comment ท้ายบรรทัดและเครื่องหมายคำพูดแบบ python-dotenv (เช่น `RAG_MODEL=gpt-5.6-luna  # ...` จะพัง)
และ mount สำเนา index ไม่ใช่ `chroma_db` ตัวจริงของ repo
ถ้าเจ้าของไม่ใช้ host ภายนอก: เครื่องตัวเองรัน uvicorn พอร์ต 8000 + `ngrok http --url=<ชื่อ>.ngrok-free.app 8000` (โดเมนถาวรฟรี 1 อัน)
