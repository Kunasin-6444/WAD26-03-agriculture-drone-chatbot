# เตรียม Docker สำหรับ host เครื่องเดียว

อัปเดต 2026-11-01: เส้นทางหลักคือ Docker target `runtime` + `compose.yaml` และ `compose.storage.yaml` สำหรับ LINE ผ่าน `exclusive_pipeline`.
`compose.support.yaml`, `requirements-rag-standard.txt` และ Docker target `support` ถูกถอดออกแล้ว จึงไม่ใช้คำสั่งชุดนั้นสำหรับส่งงาน

ผล build/smoke กับ KB 982 records วันที่ 31 ต.ค. เป็นผลเก่า ไม่ได้ build ซ้ำรอบตรวจ 1 พ.ย.; ดูสถานะและข้อจำกัดล่าสุดที่ [CURRENT_STATE](CURRENT_STATE.md)
หน้าทดลองในเครื่องใช้ `.venv/Scripts/python.exe -m scripts.playground` แล้วเปิด `http://127.0.0.1:8080` โดยไม่เปิด LINE worker

## เปิด Docker ด้วยข้อมูลเดิม (เส้นทางหลัก)

1. เปิด Docker Desktop ให้ Linux engine พร้อม (`docker info` ต้องสำเร็จ) หรือเตรียม Docker Engine + Compose บน Linux
2. ใช้ `.env` เดิมของเจ้าของบนเครื่องนี้; เครื่องใหม่ให้เจ้าของสร้างจาก `.env.example` แล้วใส่คีย์เอง ห้ามนำ secrets เข้า image
   โปรไฟล์ปัจจุบันคือ `ANSWER_MODE=natural`, `RAG_MODEL=gemini-3.7-flash` (เจ้าของสั่ง 1 พ.ย.), fallback ตาม config เดิม และ `LLM_SECONDARY_ORDER=last`
   Compose จะไม่เริ่มถ้าไม่ได้ระบุ 4 ค่านี้ (fallback ตั้งว่างได้) เพื่อป้องกันเผลอใช้ค่าเริ่มต้นรุ่นเก่าในโค้ด
3. หยุด app/playground/ingestion เดิมก่อนใช้ข้อมูลชุดเดียวกันใน container และสำรองข้อมูลตามหัวข้อ Backup ด้านล่าง
   ต้องมี `chroma_db/chroma.sqlite3` พร้อม vector segments ทั้ง directory และ `cache/` อยู่แล้ว
4. ที่ root ของ repo รันใน Git Bash/Linux shell:

```bash
docker compose -f compose.yaml -f compose.storage.yaml config --quiet
docker compose -f compose.yaml -f compose.storage.yaml build chatbot
# ตรวจ startup + KB โดยใช้ inbox ชั่วคราว ไม่ประมวลผลงาน LINE ค้าง
docker compose -f compose.yaml -f compose.storage.yaml run --rm chatbot python -B -m scripts.smoke_deployment
# เปิดบริการจริง: worker จะกู้งาน LINE ที่ค้างใน inbox เดิมตามปกติ
docker compose -f compose.yaml -f compose.storage.yaml up -d --wait chatbot
curl --fail http://127.0.0.1:8000/health/ready
docker compose -f compose.yaml -f compose.storage.yaml logs --tail 100 chatbot
```

ใช้ `config --quiet` แทนการพิมพ์ config ทั้งชุด เพราะ config ที่ resolve แล้วมีคีย์จริง
`compose.storage.yaml` mount `./chroma_db` และ `./cache` แทน named volumes โดยไม่สร้าง directory ที่หายเอง
จึงไม่เปิดฐานว่างเพราะพิมพ์พาธผิด; ใช้พฤติกรรม merge ตาม mount target ของ [Docker Compose](https://docs.docker.com/reference/compose-file/merge/#unique-resources)
ข้อมูลอยู่นอก image และยังอยู่เมื่อสร้าง container ใหม่ ถ้า `/health/ready` คืน 503 ให้ตรวจ index, สิทธิ์เขียน directory และ log ก่อน
เมื่อใช้ override ต้องใส่ `-f` ทั้งสองไฟล์ทุกคำสั่งที่จัดการบริการ:

```bash
docker compose -f compose.yaml -f compose.storage.yaml stop chatbot
# หลังแก้ .env ให้สร้าง container ใหม่ (restart อย่างเดียวไม่โหลด environment ใหม่)
docker compose -f compose.yaml -f compose.storage.yaml up -d --force-recreate --wait chatbot
```

## ย้ายไป Linux host

ใช้ image/source แบบ private เพราะมีเอกสาร PDF ของโปรเจกต์อยู่ใน image เครื่องปลายทางต้องใช้ persistent disk
หยุดต้นทางและสร้าง snapshot ตามหัวข้อ Backup แล้วส่ง snapshot พร้อม source ไป host ผ่านช่องทางส่วนตัว; ส่ง `.env` แยกจาก image
บน host build runtime แล้ว restore ไป directory ใหม่ (ตัวอย่างใช้ `backups/restore-01`):

```bash
docker compose build chatbot
# เตรียม backups ให้ UID/GID 10001 เขียนได้ก่อน แล้วค่อย restore
docker compose run --rm -v ./backups:/backups chatbot python -B -m scripts.storage_snapshot restore --snapshot /backups/release-01 --destination /backups/restore-01
export CHATBOT_DATA_ROOT=./backups/restore-01
docker compose -f compose.yaml -f compose.storage.yaml run --rm chatbot python -B -m scripts.smoke_deployment
docker compose -f compose.yaml -f compose.storage.yaml up -d --wait chatbot
```

`CHATBOT_DATA_ROOT` ต้องชี้ไป directory ที่มีทั้ง `chroma_db/` และ `cache/`; ตั้งค่านี้ใน shell ทุกครั้ง หรือให้เจ้าของเพิ่มลง `.env` ของ host
บน Linux directory ข้อมูลต้องอ่าน/เขียนได้ด้วย UID/GID `10001:10001` ของ container (ตั้งเจ้าของเฉพาะ directory deployment ที่ตรวจพาธแล้ว)
Snapshot ตรวจ checksum และไม่ทับปลายทางเดิม ไม่ต้อง ingest ใหม่/เสีย quota เพื่อย้าย host
เก็บ snapshot และ source รุ่นเดิมไว้สำหรับ rollback: หยุด container ใหม่ก่อน restore ไป directory ใหม่ แล้วเลือก `CHATBOT_DATA_ROOT` ชุดที่ต้องการ
อย่าเปิดต้นทางและปลายทางพร้อมกันโดยใช้ inbox ที่คัดลอกชุดเดียวกัน เพราะอาจต่างฝ่ายต่างประมวลผลงานค้าง

## ลำดับโมเดลที่อ่านจาก .env วันที่ 2026-10-24

| ลำดับ | Provider | โมเดล |
| --- | --- | --- |
| 1 | KKU Gen AI | `gpt-5.6-luna` |
| 2 | KKU Gen AI | `claude-sonnet-5.5` |
| 3 | KKU Gen AI | `gemini-3.7-flash` |
| 4 | KKU Gen AI | `deepseek-v4-pro` |
| 5 | Google secondary | `gemini-3.5-flash-lite` |
| 6 | Google secondary | `gemini-3.1-flash-lite` |

โค้ด `app/rag/rag_service.py` สร้างลำดับนี้จาก `RAG_MODEL`, `LLM_FALLBACK_MODELS`, `LLM_SECONDARY_MODELS`, `LLM_SECONDARY_ORDER=last`
ใช้ secondary เมื่อมี URL+key และ primary เกิดข้อผิดพลาดที่เข้าเงื่อนไขหรืออยู่ใน cooldown
ไม่ได้เรียกครบ 6 ตัวทุกคำถาม: เลือกคำตอบแรกที่สมบูรณ์ ข้ามตัวที่ cooldown และหยุดเมื่อหมด deadline/attempt budget
โหมด natural ให้ 2 attempts ที่กินเวลาต่อขั้นสร้างคำตอบ; 401/403/429 ไม่นับในโควตา attempts แต่ยังมี deadline รวม
ตั้งเวลาแต่ละครั้ง 35 วินาที, pipeline 50 วินาที และตัวหุ้ม `ask_ai` รอได้ 52 วินาที; ไม่ใช่ SLA เวลาส่งถึง LINE
daily limit cooldown 30 นาที, transient cooldown 60 วินาที เก็บในหน่วยความจำและหายเมื่อ restart

Embedding ใช้ Google `gemini-embedding-2` แยกจาก fallback ของโมเดลตอบคำถาม; ไม่มี fallback embedding ไป KKU
Vision ค่าเริ่มต้น `gemini-3.5-flash-lite` ใช้ตอน ingestion หน้าภาพ; โหมดปัจจุบัน `PDF_RETRIEVAL_MODE=text` ไม่อ่านภาพใหม่ทุกคำถาม
เมนูสำเร็จรูปและ cache hit อาจตอบโดยไม่เรียก LLM; Tavily เป็นบริการค้นเว็บ ไม่ใช่โมเดลสำรอง
นี่คือลำดับจาก config/โค้ด ไม่ใช่ผลยืนยันว่าแต่ละ provider พร้อมหรือยังมี quota วันนี้

## ข้อมูลที่ต้องเก็บถาวร (กรณีใช้ compose.yaml เดี่ยว)

| Volume | ข้อมูล | หน้าที่ |
| --- | --- | --- |
| `knowledge` → `/app/chroma_db` | Chroma SQLite, vector segments, embedding cache | ฐานความรู้ |
| `state` → `/app/cache` | LINE inbox SQLite และ direct PDF snapshots/transcripts | งานค้าง การป้องกันซ้ำ และหลักฐาน PDF |

ใช้ 1 host และ 1 Uvicorn worker เป็นค่าเริ่มต้น Worker ของ LINE มี concurrency ที่ตั้งผ่าน `LINE_WORKER_CONCURRENCY` ไม่ใช้ shared SQLite ข้ามหลาย host

## ทางเลือก named volumes สำหรับผู้ดูแล

1. เตรียม `.env` จาก `.env.example` ใส่ credential จริงบน host และกำหนดสิทธิ์ไฟล์ให้เฉพาะผู้ดูแล ห้ามนำ credential เข้า image
2. ใช้ `PDF_RETRIEVAL_MODE=text` สำหรับ release ปัจจุบัน และใช้ config retrieval ที่ผ่านรายงานประเมินล่าสุด
3. เมื่อเตรียม deploy จริงและ Docker daemon พร้อม ให้ build runtime (ไม่จำเป็นสำหรับการแก้ MD หรือทดลองหน้าเว็บในเครื่อง):

```powershell
docker compose build chatbot
```

4. Volume ใหม่ยังไม่มี KB เส้นทางหลักด้านบนใช้ bind mount ของข้อมูลเดิมเพื่อไม่ต้อง ingest ซ้ำ หากเลือก named volumes ต้องนำ snapshot ที่ตรวจแล้วเข้าทั้งสอง volume ก่อนเปิดบริการ
   การ ingest ต่อไปนี้เป็น reference เฉพาะกรณีเจ้าของอนุญาต API ไม่ใช่ขั้นตอนย้าย host ตามปกติ:

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

## เชื่อม HTTPS/LINE ด้วย ngrok (เจ้าของเลือก 2026-10-21)

ใช้เครื่องเจ้าของและโดเมน ngrok ที่ตั้งไว้เดิม เครื่องต้องเปิดและไม่หลับตลอดช่วงที่มีคนใช้
หากใช้ Linux host กับโดเมนของตัวเอง ให้ reverse proxy บน host จัดการ HTTPS และส่งต่อเข้า `127.0.0.1:8000`

1. ครั้งแรกครั้งเดียว: https://dashboard.ngrok.com/domains → ใช้โดเมนฟรีที่ได้ (เช่น `<ชื่อ>.ngrok-free.app`)
2. เปิด container ตามหัวข้อแรกและตรวจ `/health/ready` ผ่านก่อน ไม่เปิด Uvicorn ในเครื่องซ้ำบน port 8000
3. Terminal 2: `ngrok http --url=<ชื่อ>.ngrok-free.app 8000`
4. ครั้งแรกครั้งเดียว: LINE Developers Console → Messaging API → Webhook URL = `https://<ชื่อ>.ngrok-free.app/webhook`
   → Update → Verify → เปิด **Use webhook** และ **Webhook redelivery** (คิวกันข้อความซ้ำด้วย `webhookEventId` แล้ว)
5. ครั้งต่อไปทำแค่ข้อ 2–3; แก้โค้ดแล้วใช้ Compose `up -d --build --wait chatbot` พร้อม `-f` ทั้งสองไฟล์ (ngrok เปิดค้างได้)
   ข้อความที่เข้ามาตอนบริการปิด ngrok ตอบ 502 แล้ว LINE ส่งซ้ำให้เองเมื่อเปิด redelivery
6. ช่วงที่มีคนใช้: Settings → System → Power → ตั้ง sleep เป็น Never (ตอนเสียบปลั๊ก) และอย่าพับจอถ้าตั้งให้พับแล้วหลับ

รอบนี้ไม่ได้เปลี่ยน webhook, ตั้ง rich menu หรือเปิด tunnel จริง เจ้าของเป็นผู้ดำเนินการเชื่อม LINE เมื่อพร้อม

## Backup และ restore

เครื่องมือ `scripts.storage_snapshot` ตรวจ SHA-256 ทุกไฟล์ ไม่ทับปลายทางเดิม และ restore ลง directory ใหม่เท่านั้น Snapshot อาจมีข้อความผู้ใช้ที่ยังค้าง จึงต้องจำกัดสิทธิ์และอายุการเก็บตามนโยบายของผู้ใช้งาน

ต้องหยุดทั้ง app และ ingestion ก่อน backup เพื่อให้ SQLite กับ vector segments เป็นสถานะเดียวกัน ตัวอย่างบนเครื่องพัฒนา:

```powershell
.venv/Scripts/python.exe -B -m scripts.storage_snapshot backup --quiesced --output cache/backup-release-01
.venv/Scripts/python.exe -B -m scripts.storage_snapshot restore --snapshot cache/backup-release-01 --destination cache/restore-check-01
```

บน Compose แบบ named volumes ให้หยุดบริการและงาน ingest แล้วใช้ one-off container โดย mount directory backup ของ host เพิ่มเข้า `/backups`
ถ้าใช้เส้นทางหลัก `compose.storage.yaml` ให้เติม `-f compose.yaml -f compose.storage.yaml` หลัง `docker compose` ในทุกคำสั่งด้านล่าง:

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
เป็นผลรอบก่อน ไม่ใช่การ build/check container รอบ 2026-10-24 และไม่ยืนยันคุณภาพคำตอบหรือการส่ง LINE จริง
ยังไม่มี host จริง การเตรียม production ไม่เป็น gate ก่อนให้เจ้าของทดลองถามในเครื่อง
หากจะเปิด production ให้ตกลงขอบเขตคุณภาพและปิดข้อเสี่ยงสำคัญของรุ่นก่อน โดยไม่ขยาย live batch เอง
