# งานถัดไป

อัปเดต 2026-10-19 (Claude) — เขียนให้ agent ที่มาทำต่อ (เช่น Codex) ทำตามได้ทันที กติกาทั่วไปอยู่ที่ [AGENTS.md](../AGENTS.md) สถานะอยู่ที่ [CURRENT_STATE](CURRENT_STATE.md)
กำหนดส่ง: **ทดสอบใช้จริง 26 ต.ค. 2026** / **ส่งอาจารย์ 2 พ.ย. 2026**
เจ้าของต้องการ: คำตอบแบบผู้ช่วย AI ทั่วไป ตรงประเด็น ไม่ยาว แต่รายการต้องครบ มีอ้างอิง เน้นสนับสนุนนักบินโดรน ตอบเร็ว และ**ห้ามมีค่าใช้จ่าย** (ใช้ KKU Gen AI ซึ่งฟรีทุกโมเดล)

## เริ่มตรงนี้

**สภาพโค้ด:** ทำงานบน branch `wip/ingest-v2-eval-2026-10-19` (`main` = 2496ed3 ห้าม merge/push ถ้าเจ้าของไม่สั่ง) เทสต์ offline ทั้งชุดผ่าน (2026-10-19)
**หลักการ (สรุปจากการวิเคราะห์ 2026-10-19):** ปัญหาหลักคือไม่เคยวัดคุณภาพคำตอบ จึงแก้ทีละอาการและเปลี่ยนแบบไปมา
(2 ต.ค. ตอบอิสระเร็ว 3–7 วิ → 15 ต.ค. JSON + quote ตรงตัว) — **ห้ามเปลี่ยนค่าเริ่มต้นหรือรื้อขั้นตอบโดยไม่มีตัวเลขจากชุดวัด**

### ก่อนใช้ quota ต้องได้คำตอบจากเจ้าของ (ยังไม่ได้ ณ 2026-10-19)
1. อนุมัติการวัดผลตามขั้น 2–5 ด้านล่าง (ฟรี แต่ใช้ quota รายวันของ KKU)
2. วันที่ 26 ผู้ทดสอบใช้ช่องทางไหน (LINE ต้องมี HTTPS ที่เข้าจากภายนอกได้ เช่น tunnel / หรือหน้า playground) และประมาณกี่คนกี่คำถาม (ใช้คำนวณ quota)
3. เกณฑ์ผ่านที่เสนอ: ผ่านจากผู้ตรวจ (ถูก+ครบ) ≥ 80% บน dev, คำตอบอันตราย = 0, ปฏิเสธทั้งที่เอกสารมีคำตอบ ≤ 10%, อ้างหน้าถูก ≥ 90%, เวลา p50 ≤ 10 วิ / p95 ≤ 25 วิ

### ผลตรวจและงานแก้ 2026-10-19 (Codex)

เจ้าของขอ review ขณะโควตาหมด รายละเอียดอยู่ที่ [PROBLEM_LOG](PROBLEM_LOG.md#ตรวจความพร้อมใช้งานจริง-2026-10-19-codex); focused offline 88 tests + 22 subtests และ `pip check` ผ่าน ไม่ใช่ผลวัดคำตอบจริง

- **ขอบเขตล่าสุดจากเจ้าของ:** ใช้เอง ถามไม่เยอะ ใช้บริการมหาวิทยาลัยไปก่อน ไม่ต้องทำเรื่อง billing ตอนนี้ ให้เลื่อน **A04**, **A08** และงานรองรับผู้ใช้จำนวนมาก/production host; ไม่ใช้เป็นเงื่อนไขก่อนใช้ส่วนตัว
- เน้นความเสี่ยง **A01–A02** (intro/claim ที่ไม่มีความหมายรองรับยังผ่าน) และวัดคุณภาพ **A03** ตามลำดับงานเดิมเมื่ออนุมัติและโควตาพร้อม
- **ทำแล้วหลังเจ้าของอนุมัติ:** **A05** แยก provider outage จากข้อมูลไม่พอและแจ้งเหตุที่ยืนยันได้; **A06** หยุดก่อน retrieval/web เมื่อไม่มีโมเดลที่เรียกต่อได้ตาม cooldown ที่ทราบ โดยคง cache, bot usage, fallback ที่ยังพร้อม และคำตอบบางส่วนที่มีหลักฐาน ตรวจชุดหลัก offline 106 tests ผ่าน และตรวจหลังปรับพร้อม LINE integration 53 tests ผ่าน (ชุดทับซ้อนกัน) ดูรายละเอียดที่ CURRENT_STATE
- พิจารณา **A07**, **A09** เรื่อง freshness และ lexical fallback เมื่อ embedding ล่มตามปัญหาที่พบจริง; **A08** เรื่องคิว/งบต่อผู้ใช้ค่อยพิจารณาเมื่อขยายการใช้งาน
- งานคงเหลือเป็นข้อเสนอจาก review ไม่ใช่คำสั่งให้เปลี่ยน prompt/model หรือรัน live เอง การเปลี่ยน prompt/รูปแบบคำตอบปกติยังต้องวัดก่อนและหลังตาม AGENTS; งานแก้ A05–A06 เปลี่ยนเฉพาะการแจ้ง/จัดการข้อขัดข้องตามที่อนุมัติ ไม่ใช้ quota หรือเปลี่ยนค่าเริ่มต้นโมเดล

### ล่าสุด 2026-10-21
ตัวหลัก gpt-5.6-luna ผ่าน 16/17 คัดกรอง (ดู CURRENT_STATE) — `.env` ที่เสนอ: `RAG_MODEL=gpt-5.6-luna`,
`LLM_FALLBACK_MODELS=claude-sonnet-5.5,gemini-3.7-flash,deepseek-v4-pro`, `LLM_ATTEMPT_TIMEOUT_SECONDS=35`, `RAG_REQUEST_TIMEOUT_SECONDS=50`
งานค้าง: เจ้าของสุ่มตรวจ CSV `cache/eval/screen_luna_natural_20261021.csv`; holdout ครั้งเดียว (ต้องใช้ quota luna ทั้งวัน — ทำวันที่ไม่ใช้ทดลอง);
dis04 / inv07 การค้นยังพลาด (ดู CURRENT_STATE)

### ล่าสุด 2026-10-20 (เย็น)
โหมด `natural` ชนะ (ผ่าน 69%, อ้างหน้าถูก 100%; grounded ทำไม่ทันเวลา) — ดูตารางใน CURRENT_STATE ลำดับต่อไป:
1. เจ้าของตั้ง `.env`: `ANSWER_MODE=natural`, `RAG_MODEL=gemini-3.8-flash`, `LLM_FALLBACK_MODELS=gpt-5.6-luna,deepseek-v4-pro`,
   `LLM_ATTEMPT_TIMEOUT_SECONDS=35`, `RAG_REQUEST_TIMEOUT_SECONDS=50` แล้ว restart และลองเองใน playground
2. ~~เจ้าของตัดสิน gold u07 / a01~~ ตัดสินแล้ว 2026-10-20 และแก้ gold ตามนั้น (u07 รับรายการ UAV08, a01 ใช้ถ้อยคำ CAAT)
3. วัด natural บน gemini-3.8-flash (17 ข้อคัดกรอง) เมื่อ quota Gemini รีเซ็ต — ยังไม่เคยวัด
4. holdout ครั้งเดียว (ขั้น 8) ด้วยค่าสุดท้าย

### ลำดับงาน
**ความคืบหน้า 2026-10-20:** ขั้น 1 เสร็จ; ขั้น 2 รันแล้วเฉพาะ `--prompt full` ก่อนแก้ระบบ (ผลและสิ่งที่แก้ดู [CURRENT_STATE](CURRENT_STATE.md) หัวข้อวัดผลสด 2026-10-20)
→ วันถัดไป: รันขั้น 2 ใหม่ทั้ง `full` และ `concise` ด้วยตัวเลือกด้านล่าง (ผลก่อนแก้ใช้เทียบไม่ได้), ระวัง quota 3.8 ≈ 350K/วัน (2 รอบ × 17 ข้อเกือบเต็ม)
ค้างที่ต้องดู: u02 รายการ 10 สารหมดเวลา 25 วิ (คำตอบยาว + quote ยาว) และ `run_crag_pipeline` ไม่มีเพดานเวลารวมเมื่อการเชื่อมต่อค้าง (เคยใช้ 219 วิ)
1. **เช็ค quota (ไม่เสีย token):** `client.models.list()` ผ่าน `app.config` (LLM_BASE_URL/LLM_API_KEY) แล้วส่ง prompt "ok" ด้วย `max_tokens=400` ไปที่ `gemini-3.8-flash` (โมเดลที่คิดก่อนตอบคืนค่าว่างถ้าให้แค่ 20) — ผลตอบกลับมี `model_quota.daily_remaining_tokens`
   `401 {'error': 'This model reached daily limit.'}` = quota ของโมเดลนั้นหมดวันนี้ (ไม่ใช่คีย์เสีย) — รอวันถัดไป อย่าวนลอง
2. **คัดกรอง prompt บน gemini-3.8-flash** (17 ข้อ dev จาก `tests/data/screening_ids.txt`, ผู้ตรวจค่าเริ่มต้น `gpt-5.6-terra`) รันในโปรเซสใหม่ทีละคำสั่ง:
   ```
   .venv/Scripts/python.exe -m scripts.evaluate_answers --model gemini-3.8-flash --prompt full --ids "$(cat tests/data/screening_ids.txt)" --reasoning-effort low --max-output-tokens 6000 --attempt-timeout 25 --kb-budget 25 --request-timeout 40
   .venv/Scripts/python.exe -m scripts.evaluate_answers --model gemini-3.8-flash --prompt concise --ids "$(cat tests/data/screening_ids.txt)" --reasoning-effort low --max-output-tokens 6000 --attempt-timeout 25 --kb-budget 25 --request-timeout 40
   ```
   (PowerShell: `--ids (Get-Content tests/data/screening_ids.txt)`) สคริปต์ปิด fallback เอง และไม่ยอมรันถ้าปิดไม่ได้; หยุดเองเมื่อโมเดลไม่พร้อม 2 ข้อติด — ห้ามรันซ้ำวนเมื่อหยุด
3. **ให้เจ้าของสุ่มตรวจ ~10 แถว** ใน CSV ที่ `cache/eval/` (คอลัมน์ "คนตรวจเห็นด้วย") ถ้าเห็นต่างเกิน 2 แถว ให้ปรับ `JUDGE_PROMPT` ใน `scripts/evaluate_answers.py` ก่อนเชื่อคะแนน
4. **วัดการค้นหา:** `.venv/Scripts/python.exe -m scripts.eval_retrieval --gold tests/data/source_gold_2026-10-18.json --split dev` (embedding ฟรีของ Google ~45 ครั้ง)
5. **เลือก prompt จากตัวเลข** แล้ววัด dev เต็ม (45 + answer-only 5) บน 3.8-flash แบ่ง 2 วัน (`--ids` ครึ่งละ 25) และวัด baseline เดิม `--model gemini-3.5-flash-lite --prompt full` บนชุดเดียวกัน (quota แยกโมเดล) เพื่อใช้เทียบในรายงาน
6. **Error analysis:** อ่านทุกแถวที่ไม่ผ่าน จดอาการ จัดหมวดตามตารางด้านล่าง นับ แล้วแก้หมวดที่มากสุด 1–2 หมวด วัดซ้ำเฉพาะข้อที่เกี่ยว (`--ids`)
7. **เสนอค่า `.env` ให้เจ้าของแก้เอง:** `RAG_MODEL`, `RAG_PROMPT`, `LLM_ATTEMPT_TIMEOUT_SECONDS`, `KB_GENERATION_BUDGET_SECONDS`, `RAG_REQUEST_TIMEOUT_SECONDS` (ตอนนี้เจ้าของตั้ง terra + 25/25/40 ไว้ทดลอง)
8. **Holdout 17 ข้อ ครั้งเดียว** ด้วยค่าสุดท้าย (`--split holdout --no-answer-only`) — ห้ามปรับระบบต่อจากผล holdout
9. รูปแบบข้อความบน LINE (LINE ไม่แสดง markdown; ตรวจกับ `app/services/line_service.py`), เตรียมช่องทางตามคำตอบข้อ 2, freeze 25 ต.ค. และรันเทสต์ทั้งชุดครั้งเดียว

### งบ quota
คำถามละ ~8–10K token, ~350K token/วัน/โมเดล (ตัวเลขของ lite; 3.8 ยังไม่รู้) → ~35 คำถาม/วัน/โมเดล
ขั้น 2 ≈ 34 คำถามบน 3.8 (เกือบเต็มวัน) + 34 การตรวจบน terra (prompt สั้น); dev เต็ม ≈ 50 คำถาม → ต้องแบ่ง 2 วัน; เผื่อ quota วันที่ 26 ไว้ด้วย

### ห้าม
- แก้ `.env` เอง (เจ้าของแก้; ระบบสิทธิ์ปฏิเสธการแก้จาก agent แล้วครั้งหนึ่ง) — ให้บรรทัดที่ต้องแก้แทน
- ใส่เนื้อหาจาก gold set (คำถาม/ชื่อสาร/ตัวเลข) ลงใน prompt หรือปรับระบบจากผล holdout (`tests/test_prompt_variants_contract.py` กันไว้บางส่วน)
- แก้ทีละอาการจากคำถามข้อเดียวแล้วเพิ่มกฎใน prompt — รวบรวมเป็นหมวดจากผลวัดก่อน
- รัน ingestion / Vision / batch นอกขั้นที่อนุมัติ, ลบ backup ใน `cache/`, ลด/ปิดตัวตรวจคำตอบเพื่อให้คะแนนขึ้น

## หมวดข้อผิดและแนวทาง (ใช้กับขั้น 6)

| หมวด (Barnett et al. 2024) | ที่เคยเจอ | แนวทาง (เลือกตามตัวเลข) |
|---|---|---|
| ไม่ครบ / รูปแบบไม่ตรง | ลิสต์ยาคุมไม่ครบ, ไม่อธิบาย 120-160+12 | โมเดล/ prompt ก่อน; ถ้ายังต่ำกว่าเกณฑ์ ให้ระบบกรองแถวตารางเองสำหรับคำถามรายการ แล้วให้ LLM เขียนแค่ประโยคเกริ่น |
| มีหลักฐานแต่ดึงไม่ออก | quote ผิดจนถูกตัด (ไกลโฟเซต) | นับเหตุผลจาก `grade_reason`/`diagnostics` ในผลวัด แก้ตัวตรวจทีละหมวดพร้อมเทสต์; บั๊กที่รู้: รายการแบบ "A, B และ C ใช้อัตรา x, y, z ตามลำดับ" |
| ความเฉพาะเจาะจงผิด | แบต 25.0 V ของโดรนสำรวจ, เบี้ยประกันเป็นวงเงิน | มีกฎใน prompt แล้ว วัดก่อนเพิ่ม |
| ไม่มีข้อมูล | วงเงินประกัน (เว็บ CAAT ไม่มี), ภาพหน้า 38 | ตอบว่ายืนยันไม่ได้เป็นพฤติกรรมที่ถูก; เก็บคำถามจากวันที่ 26 ไว้ให้เจ้าของตัดสินใจเพิ่มเอกสาร |
| ค้นไม่เจอ / หลุดจาก context | เคยเกิดจากขยะ (แก้แล้ว) | ดูผลขั้น 4 ถ้า hit@5 < 90% ค่อยลอง reranker ที่รันในเครื่อง (ฟรี) |
| ช้า | terra 16–33 วิ แล้วถูกพัก 60 วิ (`TRANSIENT_COOLDOWN_SECONDS`) จนตกไป fallback | ตั้งเวลาตามผลวัดของโมเดลที่เลือก; รอบซ่อม (repair) ทำให้เวลาเพิ่มเท่าตัว |

## รอเจ้าของตัดสินใจ (ทำความสะอาด 2026-10-19 — ส่วนที่ปลอดภัยทำแล้วและ commit แล้ว)
1. ลบ backup ที่ซ้ำ ~160 MB: `cache/backup_chroma_before_junk_cleanup_20261019`, `cache/backup_chroma_before_vision_model_retry_20261019`, `cache/deployment-verification-20261017`
   (เก็บ `backup_chroma_before_uav06_reingest_20261018` = legacy ต้นฉบับ และ `backup_chroma_before_plain_fallback_20261019` = จุดย้อนล่าสุด)
2. ถอด ingest รุ่นเก่า (`scripts/ingest_pdf.py`, `scripts/ingest_all_data.py`, `app/ingestion/knowledge_builder.py`, `scripts/clean_kb.py`, `scripts/repair_kb.py`, `scripts/analyze_pdf.py`) พร้อมปรับเทสต์ที่ import (แนะนำหลัง 26 ต.ค.)
   ระหว่างนี้ **ห้ามรัน `scripts.ingest_all_data`** กับ index ปัจจุบัน (จะ ingest ด้วย pipeline เก่า) ใช้ `scripts.ingest` เท่านั้น
3. สคริปต์ที่ไม่มีใครเรียก: `scripts/audit_contract_gaps.py`, `scripts/smoke_direct_pdf.py`, `scripts/inspect_evidence.py`; ไฟล์ `tests/data/hybrid_acceptance.json`
4. `.agents/` (ทางเข้าของ Gemini/Antigravity), `docs/Test.txt` (โน้ต git ของเจ้าของ), Direct PDF (โหมดเสริมที่ต่อกับ runtime — ไม่แตะก่อน 26 ต.ค.)
5. merge branch เข้า `main` และ push เมื่อเจ้าของสั่ง

## ข้อมูลและ ingestion (เมื่อมีเหตุจากผลวัด)
- ไม่ re-ingest ทั้งคลังอัตโนมัติ ย้าย UAV07–12 ไป pipeline ใหม่ทีละไฟล์เฉพาะที่ error analysis ชี้ (ตารางถูกตัด/ข้อความเพี้ยน) สำรอง index ก่อนทุกครั้ง แล้ววัดซ้ำ
- หน้า 38 ของ `ฟีเจอร์การลงทุน.pdf` เป็นช่องว่างที่ยอมรับแล้ว (ภาพหน้าจอตัวอย่าง ไม่ควรตอบเป็นคำแนะนำจริง)
- gold set: a05 ยังไม่ได้ให้เจ้าของตรวจ; 18 ข้อติดป้ายอัตราสารเคมีและ 3 ข้อที่เอกสารขัดกันเอง (inv03, inv18, mix13) ให้ผู้เชี่ยวชาญดูถ้ามีโอกาส

## หลัง 26 ต.ค.
- นำคำถามที่พลาดจากการทดสอบจริงเข้า gold set (ให้เจ้าของรับรองคำตอบก่อน) แล้ววัดซ้ำ
- รายงานอาจารย์: สถาปัตยกรรม, ผลวัดก่อน/หลัง (baseline lite vs ค่าที่เลือก), ข้อจำกัด, บทเรียนเรื่องกระบวนการ
- เมื่อมี host: HTTPS, volumes/restore และ LINE end-to-end ตาม [DEPLOYMENT](DEPLOYMENT.md)

## ยังไม่ทำ
ไม่แข่ง Direct PDF vs RAG, ไม่ re-ingest ทั้งคลังอัตโนมัติ, ไม่ทำความจำบทสนทนาจนกว่าเจ้าของสั่ง, ไม่ใช้บริการเสียเงิน,
แบบ "ตอบธรรมชาติ + ตรวจตัวเลขทีละประโยค" พักไว้ ทำเฉพาะถ้าผลวัดชี้ว่ารูปแบบ JSON + quote เป็นคอขวด, ไม่สร้างแผนหรือรายงานสถานะคู่ขนาน
