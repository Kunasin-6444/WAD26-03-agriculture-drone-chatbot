# Agriculture Drone Chatbot

แชตบอตภาษาไทยสำหรับความรู้โดรนเกษตร ใช้เอกสารเป็นหลัก หากเอกสารตอบไม่ได้จึงค้นเว็บและตอบจากเว็บเพียงแหล่งประเภทเดียว พร้อมอ้างอิงหลักฐานที่ใช้จริง

เริ่มที่ [สารบัญเอกสาร](docs/README.md), [ข้อกำหนด](docs/PROJECT_REQUIREMENTS.md), [สถานะจริง](docs/CURRENT_STATE.md) และ [งานถัดไป](docs/NEXT_STEPS_PLAN.md)
แนวทางทำงานสำหรับ AI อยู่ที่ [AGENTS.md](AGENTS.md)

## API สำหรับส่งงาน — WAD26-03

### Developed Web API: LINE Webhook

| รายการ | รายละเอียด |
| --- | --- |
| Public API URL ที่ตรวจเมื่อ 2 พ.ย. 2026 | `https://viper-shopping-untainted.ngrok-free.dev/webhook` |
| Local URL | `http://127.0.0.1:8000/webhook` |
| Method | `POST` |
| Content type | `application/json` |
| Authentication | Header `X-Line-Signature` ตรวจลายเซ็นด้วย LINE SDK และ Channel Secret ที่เก็บบนเซิร์ฟเวอร์ |
| Source code | [`webhook()` ใน app/api/webhook.py](app/api/webhook.py); ลงทะเบียน router ใน [app/main.py](app/main.py) |

**URL นี้ผ่าน ngrok สำหรับสาธิต ไม่ใช่ production host ถาวร:** ต้องเปิด Docker, ngrok และเครื่องไว้ และตรวจ URL อีกครั้งก่อนส่งงาน หาก URL เปลี่ยนต้องใช้ URL ใหม่ที่ตรงกับ LINE Developers Console

ลำดับการทำงาน: LINE ส่ง event → webhook ตรวจ signature → เก็บ event ที่รองรับลงคิว SQLite → ตอบรับ HTTP → worker ประมวลผลและส่งคำตอบกลับผ่าน LINE Messaging API. รหัส `webhookEventId` ใช้ป้องกันการประมวลผล event เดิมซ้ำ ไม่ใช่แคชคำตอบจากข้อความคำถาม ([webhook.py](app/api/webhook.py), [line_inbox.py](app/services/line_inbox.py))

**ตัวอย่าง request สำหรับตรวจ webhook:** ค่า signature ด้านล่างเป็น placeholder ไม่สามารถใช้ยืนยันตัวตนได้จริง ต้องคำนวณจาก body ที่ส่งตรงตัวด้วย Channel Secret และไม่เปิดเผย secret หรือ signature ในภาพสาธารณะ ([วิธีตรวจ signature ของ LINE](https://developers.line.biz/en/docs/messaging-api/verify-webhook-signature/))

```http
POST /webhook HTTP/1.1
Content-Type: application/json
X-Line-Signature: <signature-for-this-exact-body>

{"events":[]}
```

**ตัวอย่าง response เมื่อ signature ถูกต้อง:**

```http
HTTP/1.1 200 OK
Content-Type: application/json

{"status":"OK"}
```

`200 OK` หมายถึง webhook ตอบรับ request แล้ว ไม่ใช่ข้อความตอบใน LINE; สำหรับ `events: []` จะไม่มี event ให้บันทึกหรือส่งคำตอบ ส่วนข้อความจริงจะถูกจัดการโดย worker และส่งกลับแยกผ่าน LINE Messaging API

| กรณี | ผลตอบกลับ |
| --- | --- |
| Signature ถูกและเก็บ event ที่รองรับได้ หรือไม่มี event ให้ทำงาน | `200 {"status":"OK"}` |
| Signature ไม่ถูกต้อง | `400 {"detail":"Invalid signature"}` |
| ไม่มี header `X-Line-Signature` | `422` จาก FastAPI validation |
| เก็บ event ที่ต้องประมวลผลลงคิวไม่ได้ | `503 {"detail":"Inbox unavailable"}` |
| JSON ผิดรูปแบบหรือ field `events` ไม่ถูกต้อง แต่ signature ถูก | การทดสอบ offline เคยพบ `500`; ยังเป็นข้อจำกัดที่ต้องแก้ ไม่ควรระบุว่า API จัดการกรณีนี้สมบูรณ์ |

เมื่อ 2 พ.ย. 2026 ตรวจ public URL ผ่าน ngrok ด้วย empty event ที่ลงลายเซ็นถูก ได้ `200` และลายเซ็นผิดได้ `400`; สถานะ LINE webhook เปิดและตรงกับ tunnel ณ เวลาตรวจ ผลนี้ไม่ได้ยืนยันคุณภาพคำตอบ AI หรือว่า provider มีโควตา ในการทดสอบจริงก่อนหน้าผู้ใช้ส่ง “เมนู” ผ่าน LINE และได้รับ Flex กลับมา

### API อื่นที่พัฒนาใน LINE backend

| Method และ path | หน้าที่ | ตัวอย่าง response |
| --- | --- | --- |
| `POST /api/webhook` | เรียก handler เดียวกับ `/webhook` เป็นอีก path ไม่ใช่ API คนละฟังก์ชัน | เหมือน `/webhook` |
| `GET /health/live` | ตรวจว่า backend ตอบสนอง | `{"status":"alive"}` |
| `GET /health/ready` | ตรวจ index, inbox และ worker ในเครื่อง | `{"status":"ready","checks":{"knowledge_index":true,"inbox":true,"worker":true},"external_providers":"not_probed"}` เมื่อตรวจในเครื่องผ่าน |
| `GET /` | ข้อความสถานะพื้นฐาน | `{"message":"Agriculture Drone Chatbot API is running!"}` |

โค้ด: [app/api/health.py](app/api/health.py) และ [app/main.py](app/main.py). `health/ready` ไม่ตรวจโควตา KKU หรือการส่งข้อความถึง LINE และคืน `503` เมื่อ local checks ไม่ผ่าน. Local Playground มี `POST /api/ask` ใน [app/playground.py](app/playground.py) แต่เป็นแอปแยก ไม่ได้ mount ใน LINE backend

### Called External APIs

| Provider / API | HTTP URL หรือ SDK method | จุดใช้งานและสถานะ |
| --- | --- | --- |
| KKU Gen AI | `POST https://gen.ai.kku.ac.th/api/v1/chat/completions` เมื่อใช้ gateway ค่าเริ่มต้น; SDK `chat.completions.create()` | สร้างคำตอบจากหลักฐาน: [rag_service.py](app/rag/rag_service.py). ตรวจโค้ดแล้ว; ผลทดสอบสดก่อนหน้าไม่สำเร็จเพราะระบบจำแนกข้อผิดพลาดเป็น quota หมด |
| LINE Messaging API | `POST https://api.line.me/v2/bot/message/reply`; `POST https://api.line.me/v2/bot/message/push`; [เอกสารทางการ](https://developers.line.biz/en/reference/messaging-api/) | ส่งคำตอบ/Flex และ push fallback ตามเงื่อนไข: [line_service.py](app/services/line_service.py). เคยตรวจ LINE validation และผู้ใช้ได้รับ Flex จริง; validation ไม่ใช่การตรวจความถูกต้องทุกคำตอบ |
| LINE Loading Animation | `POST https://api.line.me/v2/bot/chat/loading/start`; SDK `show_loading_animation()` | แสดงสถานะกำลังทำงานในแชต: [line_service.py](app/services/line_service.py). ตรวจโค้ดและ SDK แล้ว |
| LINE Rich Menu Administration | `POST https://api.line.me/v2/bot/richmenu`; `POST https://api-data.line.me/v2/bot/richmenu/{richMenuId}/content`; `POST https://api.line.me/v2/bot/user/all/richmenu/{richMenuId}` | สร้างเมนู อัปโหลดภาพ และตั้งเป็นเมนูเริ่มต้น: [rich_menu_service.py](app/services/rich_menu_service.py). เป็นคำสั่งตั้งค่าแยก ไม่ได้เรียกทุกครั้งที่ตอบข้อความ |
| Tavily | `POST https://api.tavily.com/search`; `POST https://api.tavily.com/extract`; [Search](https://docs.tavily.com/documentation/api-reference/endpoint/search), [Extract](https://docs.tavily.com/documentation/api-reference/endpoint/extract) | ค้นและดึงหลักฐานเว็บ: [web_fallback.py](app/rag/web_fallback.py). ตรวจโค้ดและ SDK; ไม่ได้เรียกใหม่ในการทำเอกสารนี้ |
| Google Gen AI Embeddings | SDK `client.models.embed_content()`; SDK ที่ติดตั้งใช้ `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents` สำหรับ non-Vertex; [Embedding API](https://ai.google.dev/api/embeddings) | สร้างเวกเตอร์สำหรับค้นข้อมูล: [embedding.py](app/rag/embedding.py). ตรวจโค้ด/SDK และมีบันทึกการเรียกในรอบก่อน |
| Google Gen AI vision / PDF | SDK `client.models.generate_content()`; `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` สำหรับ non-Vertex; [Generate Content API](https://ai.google.dev/api/generate-content) | ทางเลือกสำหรับอ่านข้อความจากภาพ/PDF: [vision_extractor.py](app/ingestion/vision_extractor.py), [direct_pdf.py](app/rag/direct_pdf.py). เป็นเส้นทางทางเลือก ไม่ยืนยันว่าใช้ในทุกคำถาม |
| Bangchak fuel data | `GET https://oil-price.bangchak.co.th/BcpOilPrice1/th`; `GET https://oil-price.bangchak.co.th/apioilprice2/th` | แหล่งราคาน้ำมันเฉพาะกรณี: [official_fuel.py](app/rag/official_fuel.py). ตรวจโค้ดแล้ว ไม่ได้เรียกใหม่ในการทำเอกสารนี้ |

`{model}` และ `{richMenuId}` เป็นตัวแปรใน URL ไม่ใช่ค่าจริงสำหรับคัดลอกไปยิงตรง ส่วน API ภายนอกข้างต้นไม่ใช่ API ที่กลุ่มพัฒนาขึ้นเอง และไม่ได้หมายความว่าทุก endpoint ถูกเรียกทุกครั้งที่ผู้ใช้ถาม

### ตรวจสอบและข้อจำกัดก่อนส่ง

- ตรวจ URL ปัจจุบันใน `ngrok` และใน LINE Developers Console ให้ตรงกัน แล้วกด Verify; หากต้องการหลักฐาน end-to-end ให้ส่ง “เมนู” ผ่านบัญชี LINE ทดสอบและเก็บภาพโดยซ่อนข้อมูลส่วนตัว
- ชุดทดสอบ webhook/inbox แบบ offline เคยผ่าน **47 tests และ 8 subtests** โดยใช้ mock; ตัวเลขนี้ไม่ใช่อัตราคำตอบ AI ที่ถูกต้อง
- ณ วันที่ตรวจ ไฟล์ webhook ใน Docker ตรงกับ repository แต่ไฟล์ backend บางส่วนใน container ต่างจาก source ปัจจุบัน ต้องแยกผลรันจริงจากการตรวจโค้ด และพิจารณาคิวค้างก่อน rebuild/restart
- `.env`, `chroma_db/` และ `cache/` ถูก ignore; clone repository อย่างเดียวจะไม่ได้คีย์ ฐานเวกเตอร์ หรือผล audit ใน cache. ห้าม commit credentials

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
