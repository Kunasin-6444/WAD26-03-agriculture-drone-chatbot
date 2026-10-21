# งานถัดไป (ส่งต่อให้ Codex)

อัปเดต 2026-10-21 (Claude Code, วันสุดท้ายที่เจ้าของใช้ Claude) — ไฟล์นี้คือแผนงานชุดเดียวของโปรเจกต์
กติกาการทำงานอยู่ที่ [AGENTS.md](../AGENTS.md) สถานะล่าสุดอยู่ที่ [CURRENT_STATE](CURRENT_STATE.md) หัวข้อ "สรุปสถานะ"
กำหนดส่ง: **ทดสอบใช้จริง 26 ต.ค. 2026** / **ส่งอาจารย์ 2 พ.ย. 2026** เจ้าของเป็นผู้ตรวจคนเดียว
เจ้าของต้องการ: ผู้ช่วยนักบินโดรนเกษตรภาษาไทย ตอบตรงประเด็นแบบ ChatGPT/Claude แต่รายการต้องครบ มีอ้างอิงเลขหน้า/ลิงก์จริง
ตอบเร็ว ยอมรับตรงๆ เมื่อไม่รู้ และ**ห้ามมีค่าใช้จ่าย** (ใช้ KKU Gen AI ซึ่งฟรี + Tavily/Google แบบฟรี)

## เริ่มตรงนี้

1. **สภาพ repo:** branch `wip/ingest-v2-eval-2026-10-19` นำหน้า GitHub หลาย commit (**ยังไม่ push** — ดู `git status -sb`)
   `origin/main` = `3129eed` (ยังไม่มีงานตั้งแต่ 16 ต.ค.) — push / merge / เปิด PR เมื่อเจ้าของสั่งเท่านั้น
2. **ตรวจว่าเครื่องพร้อม (offline ไม่เสีย quota):** `.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider tests` → 498 passed (2026-10-21)
3. **ลองระบบ:**
   - หน้าเว็บในเครื่อง: `.venv/Scripts/python.exe -m scripts.playground` → http://127.0.0.1:8080 (จำคำถามก่อนหน้าแบบเดียวกับ LINE)
   - LINE จริง: `.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1` + `ngrok http 8000`
     แล้วเจ้าของใส่ `https://<ngrok>/webhook` ใน LINE Developers Console; ติดตั้ง rich menu ด้วย `.venv/Scripts/python.exe -m scripts.setup_rich_menu`
     (สคริปต์นี้ตั้งเมนูหลักของบัญชี LINE จริง — รันเมื่อเจ้าของบอกเท่านั้น)
   - แก้โค้ดหรือ `.env` แล้วต้องปิด-เปิดบริการใหม่ทุกครั้ง
   - terminal ของเจ้าของเป็น Git Bash: ใช้ `/` ในพาธเสมอ (`.venv/Scripts/python.exe`) — `\` ใช้ได้เฉพาะ PowerShell (เคยทำให้เจ้าของรันไม่ได้)
   - การ์ดเมนู: พิมพ์ "เมนู" ใน LINE (มือถือ/PC) → Flex การ์ด 6 ปุ่ม; บน playground เห็นเป็นรายการข้อความ
4. **สิ่งที่เจ้าของต้องทำเอง (agent แก้ `.env` ไม่ได้ ให้เสนอบรรทัดแทน):**
   - `LLM_SECONDARY_ORDER=last` ใส่แล้ว (2026-10-21) — ถ้าย้ายเครื่อง/host ต้องใส่ด้วย ไม่อย่างนั้น Google flash-lite (อ่อนสุด) จะตอบก่อน sonnet
   - ค่าที่ใช้อยู่ตอนนี้ดูใน CURRENT_STATE หัวข้อ "ค่าตั้ง"
5. **ตรวจ quota ก่อนรันอะไรที่ใช้โมเดล:** ส่ง "ok" `max_tokens=400` ไปที่โมเดลผ่าน `app.config` (LLM_BASE_URL/LLM_API_KEY) ดู `model_quota.daily_remaining_tokens`
   quota แยกตาม**ตระกูล** (Gemini ทุกรุ่นก้อนเดียว 350K, gpt-5.6-luna/terra ก้อนเดียว 200K, claude-sonnet-5.5 200K, deepseek 1M) รีเซ็ตราวเที่ยงคืน
   `401 {'error': 'This model reached daily limit.'}` = quota หมด ไม่ใช่คีย์เสีย — อย่าวนลอง

## ลำดับงานก่อนวันทดสอบ 26 ต.ค.

| # | งาน | ต้องขอเจ้าของ? | หมายเหตุ |
|---|---|---|---|
| 1 | ทำให้ `ANSWER_MODE` ค่าเริ่มต้นในโค้ดเป็น `natural` (ตอนนี้ค่าเริ่มต้น = `grounded` ซึ่งช้าและวัดแล้วแพ้) | ใช่ | ถ้า host ใหม่ไม่มี `.env` ครบจะตกไปโหมดเก่า; แก้ `crag_service.answer_mode` + เทสต์ที่ตรึงค่า (`tests/__init__.py` ตั้ง `grounded` ให้เทสต์โหมดเก่า) |
| 2 | เล่นบทสนทนาจริงของเจ้าของซ้ำบน **luna** (quota กลับมาแล้ว) เพื่อยืนยันคำถามต่อเนื่อง/ถามกลับบนโมเดลที่ใช้จริง | อนุญาตแล้วในขอบเขตลองถาม | ชุดข้อความอยู่ใน CURRENT_STATE หัวข้อ "ทดลอง LINE ต่อ"; ผล deepseek ยังแกว่ง |
| 3 | เจ้าของสุ่มตรวจ CSV `cache/eval/screen_luna_natural_20261021.csv` (~10 แถว) | เจ้าของทำ | ผู้ตรวจรอบนี้เป็น claude-sonnet-5.5 (terra ใช้ quota ก้อนเดียวกับ luna) |
| 4 | Holdout 17 ข้อ **ครั้งเดียว** ด้วยค่าสุดท้าย บน luna ในวันที่ไม่ใช้ทดลอง (เช่น 24–25 ต.ค.) | ใช่ | `--model gpt-5.6-luna --judge-model claude-sonnet-5.5 --answer-mode natural --split holdout --no-answer-only` + ค่าเวลาเดียวกับคัดกรอง; ห้ามปรับระบบจากผล holdout |
| 5 | อัปเดต `.env.example` ให้มีค่าใหม่ทุกตัว | ไม่ (ไม่ใช่ `.env` จริง) | `ANSWER_MODE`, `LLM_FALLBACK_MODELS`, `LLM_SECONDARY_ORDER`, `LLM_REASONING_EFFORT`, `LLM_MAX_OUTPUT_TOKENS`, `RETRIEVER_TABLE_CONTINUATION`, `RETRIEVER_PHRASE_WEIGHT`, `CAAT_DESIGNATED_URLS`, `CONVERSATION_TTL_SECONDS`, `FOLLOW_UP_MAX_CHARS` |
| 6 | host บน **Render ฟรี** (เจ้าของเลือก 2026-10-21 หลัง HF Docker ต้องจ่าย) — ไฟล์พร้อม: `render.yaml`, `deploy/render/Dockerfile`, `scripts/fetch_index.py`, `scripts/build_index_bundle.py`; index อัปเข้า dataset private `Kunasin/agri-drone-index` แล้ว; ขั้นตอนใน [DEPLOYMENT](DEPLOYMENT.md) | ใช่ (สมัคร Render, token อ่าน index, secret, cron-job.org, webhook) | CPU 0.1 ทำให้ช้ากว่าเครื่องเจ้าของ ~15–20 วิต่อคำตอบ — วัดจริงหลัง deploy; ต้องเช็กว่า Render เรียก KKU Gen AI ได้; ต้องมีตัวปลุกทุก 10 นาที; วันที่ 26 ถ้า HF ยังไม่พร้อมใช้เครื่องเจ้าของ + ngrok โดเมนถาวรฟรี |
| 7 | การ์ดเมนู Flex สำหรับ LINE PC **ทำแล้ว 2026-10-21** (`rich_menu_service.menu_card`, พิมพ์ "เมนู"/แอดเพื่อน) — **ยังไม่ได้ลองบน LINE จริง** รอเจ้าของส่งภาพ | ลองเอง | ถ้าเพื่อน (Surawit) push งานแบบเดียวกันมา ให้เลือกแบบเดียว ไม่ใช้สองระบบซ้อน; quick reply ไม่ขึ้นบน PC; ตอน merge ต้องคงระบบคิว (กับดักข้อ 6) |
| 8 | เปลี่ยน GitHub repo เป็น **private** (เจ้าของตัดสิน 2026-10-21 เพื่อซ่อนสไลด์) แล้วเพิ่มเพื่อน/อาจารย์เป็น collaborator | เจ้าของทำ | สไลด์ PDF 12 ไฟล์ใน `data/` อยู่ใน git ทุก branch ตั้งแต่ commit แรก 2026-09-23 ขณะ repo เป็น public; ถ้ามี fork แบบ public อยู่ fork นั้นไม่ถูกซ่อนตาม; ห้ามทำ repo/Space/dataset ที่มีสไลด์หรือ index ให้เป็น public |
| 9 | freeze 25 ต.ค.: รันเทสต์ทั้งชุดครั้งเดียว แล้วไม่เปลี่ยนโค้ดจนจบวันทดสอบ | – | |

## หลังวันทดสอบ (26 ต.ค. – 2 พ.ย.)

1. **เก็บคำถามที่ตอบผิดจากบันทึก LINE** → ให้เจ้าของรับรองคำตอบ → เพิ่มเข้า gold (`tests/data/source_gold_2026-10-18.json`) → วัดซ้ำ
   นี่คือวิธีปรับปรุงหลักที่แนะนำ (แบบเดียวกับที่องค์กรทำ) แทนการเพิ่มกฎใน prompt ทีละข้อ
2. **ฐานข้อมูลตาราง (แนะนำระยะยาว ใช้ 2–3 วัน):** แปลงตารางสำคัญ (อัตราสารตามพืช/วัชพืช/ศัตรูพืช, สเปกหัวฉีด, ราคาและต้นทุนโดรน,
   ปัจจัยอากาศกับโรค) เป็นตารางมีโครงสร้าง + หน้าอ้างอิงต่อแถว แล้วให้คำถามแบบรายการ/กรอง/เปรียบเทียบค้นจากตารางตรง
   แก้ได้หลายปัญหาพร้อมกัน: รายการยาวไม่ครบ, inv07 "รุ่นไหนถูกที่สุด", ตารางที่ถูกตัดข้ามหน้า, ความเร็ว/quota — เจ้าของต้องตรวจข้อมูลที่แปลง
3. **การค้นที่ยังพลาด (dev 43/45 ครบ):** dis04 (ชื่อโรคกับชื่อพืชอยู่คนละที่ในชิ้นตาราง → ใส่ชื่อหมวดพืชลงชิ้นตารางตอน ingest), inv07 (ต้องได้ทั้งตาราง)
4. รายงานอาจารย์: สถาปัตยกรรม, ผลวัดก่อน/หลัง, ข้อจำกัด, บทเรียน (ตัวเลขอยู่ใน CURRENT_STATE และ `cache/eval/`)
5. อัปเดต [ARCHITECTURE](ARCHITECTURE.md) ซึ่งยังเป็นของ 2026-10-17 (ไม่มีโหมด natural, rich menu, ความจำบทสนทนา) — ใช้แผนผังใน CURRENT_STATE เป็นต้นทาง

## กับดักและบทเรียน (อ่านก่อนแก้อะไร)

1. **ห้ามแก้ปัญหาด้วยการเพิ่มกฎ prompt ทีละอาการ** ตรวจก่อนว่าปัญหาอยู่ชั้นไหน: การค้น (หน้าที่ถูกไม่ถึงโมเดล), ตัวตรวจ (ตัดบรรทัดที่ถูก),
   ข้อมูล (ตารางถูกตัด/ไทยเสีย) หรือโมเดล — ส่วนใหญ่ที่ผ่านมาเป็น 3 ชั้นแรก ดูวิธีไล่ใน CURRENT_STATE (เช่น พัดฟ้า, ตารางข้ามหน้า, วลีหายาก)
2. **วัดก่อนเปลี่ยน** ด้วย `scripts.evaluate_answers` (ล็อกโมเดลเดียว ปิด fallback) บนชุดเดียวกันก่อน/หลัง; การค้นวัดผ่านโค้ดจริงบน dev 45 ข้อ
   ด้วย `scripts.eval_retrieval` หรือสคริปต์ที่สลับค่าคงที่ (เช่น `page_reranker.PHRASE_WEIGHT`) ในโปรเซสเดียว ฝัง embedding ครั้งเดียวต่อคำถาม
3. **ห้ามใส่เนื้อหา gold ลง prompt** ตัวอย่างใน prompt ต้องสมมติ; แก้ gold ได้เฉพาะเมื่อเจ้าของตัดสินและบันทึกใน `review` ของข้อนั้น (เช่น u07, a01)
4. **ห้ามคลายตัวตรวจให้ผ่าน** ทุกการแก้ตัวตรวจต้องมีเทสต์ที่ "ปิดแล้วล้ม" (mutation check) และยังจับกรณีผิดจริงได้
5. **โมเดล:** gemini-3.8-flash ใช้ตอบรายการยาวไม่ได้ (คิดจนเต็มงบแล้วถูกตัด คุมด้วย reasoning ไม่ได้); deepseek ช้า 30–110 วิและบางครั้งตอบไม่สมบูรณ์;
   ใช้ terra เป็นผู้ตรวจไม่ได้ในวันที่ใช้ luna (quota ก้อนเดียวกัน) → ใช้ claude-sonnet-5.5
6. **LINE webhook ต้องเก็บงานลงคิว (`line_inbox`) ก่อนตอบเสมอ** (R7: กันตอบซ้ำ/งานหายตอน restart) — งาน frontend ของเพื่อนเคยเขียนแบบตอบทันที
   ตอน merge ให้ต่อเข้าคิว (ดู commit `635f287`)
7. **คำตอบสำเร็จรูป rich menu** (`data/rich_menu_answers/*.txt`) ส่งออกโดยไม่ผ่านตัวตรวจ ทุกข้อเท็จจริงต้องมี [n] + แหล่ง (หน้า KB หรือ URL ที่ดึงได้จริง)
   ตรวจด้วย `natural_answer.render` โดยสร้าง `Evidence` จากหน้าที่อ้าง (KB: เนื้อหาจาก Chroma ตามไฟล์/หน้า; เว็บ: เนื้อหาที่ดึงผ่าน Tavily extract) ต้องไม่มีบรรทัดถูกตัด
   ข้อความที่หาหลักฐานไม่เจอให้อยู่ใต้ "ข้อแนะนำทั่วไป (ไม่ได้มาจากเอกสารอ้างอิงข้างล่าง)" ห้ามใช้ `**ตัวหนา**` (ระบบล้างให้แล้วแต่ไม่ควรพึ่ง)
8. **เรื่องกฎการบินอิงเว็บ CAAT เท่านั้น** (นโยบายเจ้าของ "อิงตามเว็บ") ข่าว CAAT บางชิ้นเป็นเงื่อนไขเฉพาะช่วง ระบบเติมหมายเหตุเอง
9. **ห้าม:** แก้ `.env`; ใช้บริการเสียเงิน; รัน `scripts.ingest_all_data` (pipeline เก่า) — ใช้ `scripts.ingest` เท่านั้น; re-ingest ทั้งคลังเอง; ลบ backup ใน `cache/`;
   รัน `scripts.setup_rich_menu` หรือเปลี่ยน webhook ของ LINE โดยเจ้าของไม่สั่ง; รันเทสต์ทั้งชุดหลังแก้เล็กๆ ทุกครั้ง; batch ที่ไม่มีจุดหยุด
10. **เทสต์ต้องไม่อ่าน `.env` ของเครื่อง:** `tests/__init__.py` ตรึง `ANSWER_MODE=grounded` และคีย์ปลอม; เทสต์ที่ต้องการโหมดอื่นให้ `patch.dict` เอง

## รอเจ้าของตัดสินใจ

1. ช่องทาง/host วันที่ 26 และจำนวนผู้ทดสอบ (ใช้คำนวณ quota: ตัวเร็ว luna+sonnet ≈ 40 คำถาม/วัน รวมทุกตัว ≈ 175)
2. push + เปิด PR เข้า `main` (ให้เพื่อนตรวจคำตอบสำเร็จรูปที่ปรับถ้อยคำแล้ว) หรือ merge ตรง
3. ข้อ 1 และ 4 ในตาราง "ลำดับงานก่อนวันทดสอบ"
4. ทำความสะอาด (ทำหลัง 26 ต.ค.): ลบ backup ซ้ำ ~160 MB (`cache/backup_chroma_before_junk_cleanup_20261019`,
   `cache/backup_chroma_before_vision_model_retry_20261019`, `cache/deployment-verification-20261017`; เก็บ `backup_chroma_before_uav06_reingest_20261018`
   และ `backup_chroma_before_plain_fallback_20261019`), ถอด ingest รุ่นเก่า (`scripts/ingest_pdf.py`, `scripts/ingest_all_data.py`,
   `app/ingestion/knowledge_builder.py`, `scripts/clean_kb.py`, `scripts/repair_kb.py`, `scripts/analyze_pdf.py`) พร้อมเทสต์ที่ import,
   สคริปต์ที่ไม่มีใครเรียก (`scripts/audit_contract_gaps.py`, `scripts/smoke_direct_pdf.py`, `scripts/inspect_evidence.py`), `.agents/`, `docs/Test.txt`
5. gold: a05 ยังไม่ได้ตรวจ; 18 ข้อติดป้ายอัตราสารเคมีและ 3 ข้อที่เอกสารขัดกันเอง (inv03, inv18, mix13) ควรให้ผู้เชี่ยวชาญดูถ้ามีโอกาส

## ยังไม่ทำ (ตั้งใจ)
Direct PDF vs RAG, re-ingest ทั้งคลังอัตโนมัติ, ภาพหน้า 38 ของ `ฟีเจอร์การลงทุน.pdf` (ยอมรับแล้ว), billing/คิวหลายผู้ใช้, reranker แบบเสียเงิน,
ความจำบทสนทนาเกิน 1 คำถาม (ตอนนี้จำคำถามเต็มล่าสุดต่อผู้ใช้ 10 นาที)
