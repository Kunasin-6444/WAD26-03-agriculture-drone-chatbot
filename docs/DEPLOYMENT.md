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

## Hugging Face Spaces (Docker ฟรี) — เตรียม 2026-10-21

เจ้าของเลือก Hugging Face เพราะฟรี ไม่ต้องใช้บัตร และรันโค้ดเดิมทั้งก้อนผ่าน Docker (RAM ของบริการ ~260–300 MB หลังเริ่มทำงาน)
ไฟล์ที่ใช้: `deploy/huggingface/Dockerfile` (พอร์ต 7860, user id 1000), `deploy/huggingface/README.md` (ค่าตั้งของ Space)
และ `scripts/fetch_index.py` (ดาวน์โหลด index ตอนเริ่ม)

**ข้อจำกัดที่ต้องรู้ก่อน**
- Space แบบ **private** เข้าถึงได้เฉพาะคนที่ล็อกอิน Hugging Face → LINE ส่ง webhook เข้าไม่ได้ จึงต้องเป็น **public**
  ใครก็เปิดดูโค้ดใน `app/` ของ Space ได้ (ไม่มีกุญแจอยู่ในนั้น) แต่ **index (`chroma_db` ซึ่งมีเนื้อหาเอกสาร) ไม่อยู่ใน Space**
  เก็บแยกใน **dataset แบบ private** แล้ว Space ดาวน์โหลดตอนเริ่มด้วย `HF_TOKEN` (`scripts/fetch_index.py`)
  ถ้าเจ้าของไม่ยอมให้โค้ดเปิดเผยด้วย ให้ใช้เครื่องตัวเองแทน: รัน uvicorn พอร์ต 8000 แล้ว `ngrok http --url=<ชื่อ>.ngrok-free.app 8000`
  (โดเมนถาวรฟรี 1 อันจาก ngrok dashboard → Domains) และตั้ง Webhook URL = `https://<ชื่อ>.ngrok-free.app/webhook`
- เมื่อไม่มี index และไม่ได้ตั้ง `HF_INDEX_REPO` บริการจะไม่ยอมเริ่ม (ดีกว่าตอบ "ไม่พบข้อมูล" ทุกคำถาม) — ดูข้อความใน Logs
- server ของ Hugging Face อยู่ต่างประเทศ ต้องลองว่าเรียก KKU Gen AI (`https://gen.ai.kku.ac.th/api/v1`) ได้หรือไม่ เป็นสิ่งแรกที่ต้องเช็กหลัง deploy
- Space ฟรีหลับเมื่อไม่มีคนใช้ 48 ชม. (ข้อความแรกหลังหลับรอราว 1 นาที) และคิว LINE ใน `/app/cache` หายเมื่อ restart

**ขั้นตอน (เจ้าของทำ ยกเว้นข้อ 3)** — ใน Git Bash ใช้ `/` ในพาธ, `<owner>` คือชื่อบัญชี Hugging Face
1. สมัคร https://huggingface.co → Settings → Access Tokens → สร้าง token 2 อัน:
   **write** (ใช้ในเครื่องตอนอัปโหลด) และ **read** (ใส่เป็น secret ของ Space เพื่ออ่าน dataset private)
   แล้วล็อกอินในเครื่อง: `.venv/Scripts/hf.exe auth login` (วาง token write)
   สร้าง repo 2 อัน:
   `.venv/Scripts/hf.exe repos create <owner>/agri-drone-index --type dataset --private`
   `.venv/Scripts/hf.exe repos create <owner>/agri-drone-bot --type space --sdk docker --public`
2. หน้า Space → Settings → **Variables and secrets**:
   - Secrets: `LINE_CHANNEL_SECRET`, `LINE_CHANNEL_ACCESS_TOKEN`, `API_KEY` (KKU), `GOOGLE_API_KEY` (embedding), `TAVILY_API_KEY`,
     `HF_TOKEN` (token แบบ read จากข้อ 1) และถ้าใช้ Google เป็นตัวสำรอง `LLM_SECONDARY_BASE_URL`, `LLM_SECONDARY_API_KEY`
   - Variables: `HF_INDEX_REPO=<owner>/agri-drone-index`, `ANSWER_MODE=natural`, `RAG_MODEL=gpt-5.6-luna`, `LLM_FALLBACK_MODELS=claude-sonnet-5.5,gemini-3.7-flash,deepseek-v4-pro`,
     `LLM_SECONDARY_ORDER=last`, `LLM_SECONDARY_MODELS=gemini-3.5-flash-lite`, `LLM_REASONING_EFFORT=low`, `LLM_MAX_OUTPUT_TOKENS=6000`,
     `LLM_ATTEMPT_TIMEOUT_SECONDS=35`, `RAG_REQUEST_TIMEOUT_SECONDS=50`
3. สร้างโฟลเดอร์: `.venv/Scripts/python.exe -m scripts.build_hf_space` ได้ 2 โฟลเดอร์ข้าง repo
   - `../agriculture-drone-chatbot-hf-space` (public): `app/`, คู่มือ rich menu, `scripts/fetch_index.py`, Dockerfile — ราว 0.5 MB
   - `../agriculture-drone-chatbot-hf-index` (private): ไฟล์ index อย่างเดียว ไม่รวม embedding cache — ราว 38 MB
   ทั้งคู่ไม่มี PDF, เทสต์, เอกสาร และไม่มี `.env` (สคริปต์ปฏิเสธถ้าเจอ)
4. อัปโหลด index ก่อน แล้วค่อย Space:
   `.venv/Scripts/hf.exe upload <owner>/agri-drone-index ../agriculture-drone-chatbot-hf-index . --repo-type dataset`
   `.venv/Scripts/hf.exe upload <owner>/agri-drone-bot ../agriculture-drone-chatbot-hf-space . --repo-type space`
5. รอ build เสร็จ (แท็บ Logs ต้องเห็น `index downloaded from ...`) แล้วเปิด `https://<owner>-agri-drone-bot.hf.space/health/ready` ต้องได้ 200
6. LINE Developers Console → Webhook URL = `https://<owner>-agri-drone-bot.hf.space/webhook` → Verify → ลองพิมพ์ "เมนู" และถามคำถามจริง 1 ข้อ
   ถ้าคำถามจริงตอบว่าบริการขัดข้อง ให้ดู Logs ว่าเรียก KKU ได้หรือไม่
7. อัปเดตครั้งต่อไป: ทำข้อ 3 แล้วอัปโหลดเฉพาะส่วนที่เปลี่ยน (โค้ด → Space, index ใหม่ → dataset แล้วกด Restart Space) — Webhook URL ไม่เปลี่ยน

ลองในเครื่องก่อน (เปิด Docker Desktop, รันจากโฟลเดอร์ `project` ที่อยู่เหนือ repo):
`docker build -t agri-hf agriculture-drone-chatbot-hf-space`
`docker run --rm -p 7860:7860 --env-file agriculture-drone-chatbot/.env -v "$(pwd)/agriculture-drone-chatbot-hf-index:/app/chroma_db" agri-hf`
แล้วเปิด http://127.0.0.1:7860/health/ready — mount สำเนา index จากข้อ 3 ไม่ใช่ `chroma_db` ตัวจริงของ repo
ระวัง: `--env-file` ของ docker และช่อง Variables ของ Space **ไม่ตัด comment ท้ายบรรทัดและเครื่องหมายคำพูด** แบบที่ python-dotenv ทำ
(เช่น `RAG_MODEL=gpt-5.6-luna  # ...` จะได้ชื่อรุ่นที่มี comment ติดไป) — ใส่เฉพาะค่าเปล่าๆ
ค่าอื่นใน `.env` ที่ไม่ได้อยู่ในรายการข้อ 2 (เช่น `KB_GENERATION_BUDGET_SECONDS`, `LLM_SECONDARY_REASONING_EFFORT`,
`LLM_SECONDARY_STRUCTURED_OUTPUT`) ใส่เป็น Variables ค่าเดียวกับ `.env`
