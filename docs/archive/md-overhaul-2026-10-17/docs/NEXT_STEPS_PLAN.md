> Historical snapshot before the 2026-10-17 MD overhaul. Not current instructions or status. Relative Markdown links rebased for this location.

# แผนงานถัดไป — 2026-10-17

สถานะ: ดำเนินการแล้วทั้ง gold/evaluator, retrieval, grounding, partial KB+web, ingestion และแพ็กเกจ deploy ดู [ผลและงานที่ยังเหลือ](../../../RELEASE_READINESS_2026-10-17.md) เนื้อหาขั้นตอนด้านล่างเก็บไว้เป็นแผนเดิม ไม่ใช่สถานะงานปัจจุบัน

เป้าหมายคือให้บอตตอบภาษาไทยจากเอกสารก่อน ค้นเว็บเมื่อหลักฐานไม่พอ รักษาข้อมูลที่เอกสารตอบได้ และอ้างอิงแหล่งที่รองรับคำตอบจริง คำตอบต้องตรงคำถาม ครบประเด็น กระชับ และเร็ว โดยไม่ตัดหน่วย เงื่อนไข หรือข้อจำกัดที่จำเป็น

ยึด [PROJECT_REQUIREMENTS.md](../../../PROJECT_REQUIREMENTS.md) เป็นข้อกำหนดหลัก และใช้ [RELEASE_READINESS_2026-10-17.md](../../../RELEASE_READINESS_2026-10-17.md) เป็นสถานะล่าสุด ส่วน COLLAB_FIXES เป็นหลักฐานรอบก่อน

## งานที่เหลือหลังรอบเตรียม deploy

1. ปิดเกณฑ์คุณภาพจาก live/source evaluation: ลดการตกหล่นเงื่อนไขและ quote ที่ไม่ตรงต้นฉบับ ตรวจ semantic coverage ของเอกสารใหม่ และวัด latency ซ้ำเมื่อ provider มี capacity เพียงพอ
2. อ่านภาพในเอกสารการลงทุน หน้า 38 ที่ยัง timeout และตรวจเซลล์/หน่วยกับต้นฉบับก่อนนับ ingestion ว่าครบ
3. เมื่อมี host จึงตรวจ persistent volumes/restore/HTTPS และ LINE end-to-end จริง ดูขั้นตอนใน DEPLOYMENT.md

## แผนเดิมที่ใช้เริ่มงาน (เก็บเป็นประวัติ)

## สิ่งที่ทำแล้วและข้อจำกัดปัจจุบัน

- แก้กรณีสลับแถว/คอลัมน์/หน่วยในตารางที่ตรวจพบ เพิ่ม durable LINE inbox และแก้การหมดอายุของ answer cache ตามฐานความรู้
- ผล offline ล่าสุดผ่าน 236 tests และ 55 subtests; probe เดิมของ R3/R7 ผ่าน แต่ยังไม่รับรองความถูกต้องของทุกคำตอบ
- Live sample 3 คำถามผ่านการตรวจคำตอบ/อ้างอิงอัตโนมัติ 3/3 และเป้าหมายเวลา 2/3; ยังใช้สรุปคุณภาพทั้งระบบหรือ production p95 ไม่ได้
- ค่าเริ่มต้น retrieval ยังเป็น `global/none` ซึ่งต้องจัดการให้สอดคล้องกับ R2 ที่กำหนด reranking
- Direct PDF ยังเป็นการทดลองหนึ่งหน้า และยังไม่มี BM25 ตาม R2; ค่าเริ่มต้นคงเป็น `PDF_RETRIEVAL_MODE=text`

## ลำดับดำเนินงาน

### 1. สร้างชุดอ้างอิงจากต้นฉบับ และจัดระเบียบการทดสอบ

**งาน**

- ตรวจบัญชี PDF ที่อนุญาตและข้อยกเว้น CAAT ให้ตรง source policy; บันทึกความต่างระหว่างรายการไฟล์จริงกับข้อกำหนดก่อนปรับ ingestion
- อ่าน PDF ต้นฉบับเพื่อทำ gold annotation: คำถาม ข้อเท็จจริงที่ต้องตอบ ไฟล์ เลขหน้า PDF/เลขหน้าที่พิมพ์ แถว คอลัมน์ ค่า หน่วย และเงื่อนไขที่ห้ามตกหล่น
- เพิ่มกรณีข้อความ ตาราง native ตารางภาพ แผนภาพ คำถามหลายประเด็น ภาษาไทยพิมพ์ผิด และคำถามที่เอกสารตอบได้เพียงบางส่วนหรือไม่มีคำตอบ
- แยก dev/holdout และตรึงเวอร์ชันก่อนปรับ retrieval; ห้ามใช้ holdout ปรับคะแนนหรือ prompt
- ทำตารางโยง R1–R7 กับ test cases และผลลัพธ์ที่คาดหวัง ตรวจ tests เก่า แล้วเขียนชุดทดสอบทดแทนกรณีที่ล้าสมัย/ผูก implementation; ลบชุดเก่าเมื่อชุดใหม่ครอบคลุมพฤติกรรมนั้นแล้ว
- เก็บ regression ของข้อผิดพลาดที่พิสูจน์แล้วไว้ในชุดใหม่ ไม่ทิ้งการตรวจ table grounding, cache invalidation และ LINE recovery

**สิ่งส่งมอบ:** gold ที่ตรวจจากต้นฉบับ, test coverage matrix และรายการ tests ที่แทนที่/ลบพร้อมเหตุผล

**เกณฑ์ผ่าน:** ทุกกรณีมีหลักฐานตรวจย้อนกลับได้ ไม่มี gold ที่ยอมรับหน้ากว้างจาก regex โดยไม่ตรวจความหมาย และมีกรณีเชิงลบที่ต้องปฏิเสธการตอบด้วย

### 2. ปิดช่องว่าง retrieval และคุณภาพ ingestion

**งาน**

- ขยาย evaluator ให้รองรับ gold ที่ระบุเอกสาร/หน้าจริง ปัจจุบัน `scripts.eval_retrieval` ยังอาศัย regex-derived gold
- เทียบ `global/none`, `global/crop`, `global/legacy` ด้วย corpus, คำถาม, top-k และงบ context เดียวกัน
- รายงาน hit@3/5/8, MRR, การได้หลักฐานครบทุกประเด็น และความถูกต้องของคำตอบปลายทาง แยก dev/holdout
- ถ้า reranker ที่มีทำให้คุณภาพแย่ลง ให้แก้ reranking แบบใช้หลักทั่วไปและวัดใหม่; ห้ามเพิ่มคะแนนเฉพาะคำถามหรือหน้าเพื่อให้ผ่านชุดประเมิน
- ตรวจว่าตารางยังมีข้อความ/ภาพร่วมหน้าที่อธิบายหน่วยและข้อควรระวัง และเก็บ filename/page/source type ถูกต้อง
- เมื่อพบ extraction ผิด ให้แก้และทดสอบเฉพาะหน้าก่อน จากนั้นจึง re-ingest ชุดที่ได้รับผลกระทบแบบควบคุม พร้อมรายงาน provenance และ integrity

**สิ่งส่งมอบ:** รายงานเปรียบเทียบ, config ที่เลือกพร้อมเหตุผล และ index revision ที่ตรวจสอบได้

**เกณฑ์ผ่าน:** มี reranking ที่ตรง R2 และผล holdout ไม่ถดถอยจาก baseline ที่ตรึงไว้ หากยังทำไม่ได้ให้บันทึกเป็น release blocker; ห้ามเปลี่ยน requirement เงียบ ๆ หรือเปิด heuristic ที่แย่กว่าเพียงให้ครบรายการ

### 3. ยืนยัน document → web fallback → คำตอบพร้อมอ้างอิง

**งาน**

- เอกสารเพียงพอ: ตอบจากเอกสารและไม่ค้นเว็บโดยไม่จำเป็น
- เอกสารตอบบางส่วน: เก็บส่วนที่ยืนยันแล้ว ค้นเว็บเติมส่วนที่ขาด และผูกแต่ละข้อกับแหล่งที่รองรับจริง
- ไม่พบหลักฐาน/เว็บล้มเหลว: ระบุสิ่งที่ยังยืนยันไม่ได้ โดยไม่เดาตัวเลข หน่วย ขั้นตอน หรือข้อกฎหมาย
- หัวข้อที่กำหนดให้ใช้ CAAT: ตรวจ routing และการอ้างอิงแหล่งทางการตาม source policy
- Web citation ต้องแสดงชื่อหน้า/แหล่งข้อมูลและ URL เต็มที่ไปยังบทความหรือเอกสารที่ใช้รองรับข้อความนั้นจริง รวม path และ query/fragment ที่จำเป็น; ห้ามตัดเหลือเพียงโดเมนหรือเปลี่ยนเป็นหน้าแรก/หน้าผลการค้นหาแทนต้นทาง และห้ามสร้าง URL ขึ้นเอง
- ตรวจลิงก์ในข้อความ LINE ว่าเปิดไปยังหน้าเนื้อหาที่อ้างได้; หน้าแรกใช้ได้เฉพาะเมื่อข้อมูลที่นำมาตอบอยู่บนหน้าแรกจริง
- เพิ่มกรณีทดสอบสองบทความจากโดเมนเดียวกัน, URL เอกสาร PDF, query/fragment ที่จำเป็น และคำตอบผสม KB+web เพื่อยืนยันว่า citation ไม่ถูกรวมจนลิงก์ผิดหน้า
- ทดสอบ citation ผิดหน้า/ผิดไฟล์, URL ที่ไม่รองรับข้ออ้าง, หลักฐานขัดกัน, เนื้อหาเอกสารหรือเว็บที่พยายามสั่งโมเดล และ provider timeout/quota
- ตรวจความกระชับด้วย rubric: ตอบคำถามหลักก่อน ตามด้วยข้อมูลจำเป็นและอ้างอิง; ความยาวขึ้นกับจำนวนประเด็น ไม่บังคับตัดจนข้อมูลสำคัญหาย

**สิ่งส่งมอบ:** ชุด end-to-end cases พร้อมตรวจคำตอบเทียบต้นฉบับ และรายงานข้อผิดพลาดแยก routing/retrieval/extraction/generation/citation/provider

**เกณฑ์ผ่าน:** เคสวิกฤตที่ตรึงไว้ไม่มีข้ออ้างไร้หลักฐานหรืออ้างอิงผิด และเคส partial/fallback/abstain ทำงานตาม R3–R6; ผลอัตโนมัติต้องมีการตรวจความหมายจากต้นฉบับประกอบ

### 4. วัดและลด latency โดยรักษาคุณภาพ

**งาน**

- รัน live acceptance ให้ครบ 28 กรณีเมื่อ provider/quota พร้อม แบ่ง batch เล็กได้แต่ต้องรวมผลครบและไม่ทิ้งกรณีที่ล้มเหลว
- แยก cold start, warm process, transcript-cache hit และ answer-cache hit; เก็บเวลา normalization, embedding, retrieval, PDF reading, web, generation และ validation
- เพิ่ม harness สำหรับรันซ้ำและวัดภายใต้จำนวนผู้ใช้พร้อมกันที่ระบุ รายงานจำนวนตัวอย่าง p50/p95 จำนวน model/API calls และต้นทุนต่อคำถาม
- ใช้เป้าหมายรายกรณีเดิมเป็น baseline: document 8 วินาที และ web 15 วินาที; หากจะกำหนด production p95 ให้ตรึง workload/ขอบเขตเวลาและเกณฑ์ก่อนทดลอง ห้ามตีความ sample 3 คำถามเป็น p95 ของระบบ
- แก้ขั้นตอนที่วัดแล้วว่าช้า เช่น งานซ้ำ cache miss หรือคำขออิสระที่ทำพร้อมกันได้ พร้อมทดสอบ timeout และ cache invalidation
- ทุกทางเลือกต้องวัด correctness/completeness/citations ควบคู่เวลา ไม่ลด context หรือเปลี่ยน provider/model โดยไม่มีผลเปรียบเทียบ

**สิ่งส่งมอบ:** baseline และผลหลังปรับภายใต้เงื่อนไขเดียวกัน พร้อมแยก provider outage ออกจากความผิดของระบบ

**เกณฑ์ผ่าน:** ผ่านเป้าหมาย acceptance ที่กำหนด คุณภาพไม่ถดถอยบน gold และไม่มีการซ่อน cold/cache-miss latency ไว้ในค่าเฉลี่ยรวม

### 5. ทดลอง Direct PDF แบบเทียบกันได้

งานนี้ทำหลังมี gold และ text baseline ที่เชื่อถือได้ และไม่ต้องขวางการส่งมอบระบบ text หาก direct ยังไม่พร้อม

- ใช้เอกสารที่อนุญาตชุดเดียวกับ text index ตรวจ coverage ให้ครบ; สถานะอ้างอิงปัจจุบันคือ 7 PDF / 219 หน้า ต้องตรวจจำนวนจริงอีกครั้งก่อนทดลอง
- แยก collection/cache และ index revision; เทียบคำถามเดียวกันพร้อมตรวจความถูกต้องของการอ่านเซลล์ หน่วย เงื่อนไข และ citation จาก PDF ต้นฉบับ
- วัด cold PDF reading และ warm transcript cache แยกกัน รวมต้นทุนและกรณี reader timeout/ข้อความถูกตัด
- แก้ช่องว่าง BM25/reranking ของ direct ก่อนนับว่าผ่าน R2
- เก็บหน่วยตามต้นฉบับ เช่น `ml/หัวฉีด` ห้ามเปลี่ยนเป็น `ml/min` ถ้าไม่มีข้อมูลเวลา

**สิ่งส่งมอบ:** รายงาน text/direct บน corpus เดียวกัน และข้อเสนอว่าจะคง text หรือเปลี่ยนค่าเริ่มต้น

**เกณฑ์ผ่านก่อนเปลี่ยน default:** ตรง requirements คุณภาพไม่ด้อยกว่า baseline และประโยชน์ด้านคุณภาพ/เวลา/ต้นทุนมีหลักฐานชัดเจน; ผลหนึ่งหน้าไม่พอใช้ตัดสินใจ

### 6. ตรวจ deployment และเตรียมส่งมอบ

- ตรวจ persistent volume สำหรับ Chroma, PDF snapshots/cache และ SQLite inbox พร้อมทดลอง backup/restore จริง
- ทดสอบบน deployment เป้าหมาย: webhook ซ้ำ/พร้อมกัน, worker restart, lease recovery, backlog, provider outage และผลการส่ง LINE ที่ไม่ทราบแน่ชัด
- แยก liveness/readiness ตรวจ warmup, quota/rate limit และ concurrency ให้เหมาะกับ single-host architecture ปัจจุบัน
- ตรวจ clean install จาก dependencies ที่ตรึงไว้ และรัน integrity, offline suite, contract probes และ live acceptance สำหรับ release candidate เดียวกัน
- LINE end-to-end ที่ส่งจริงใช้บัญชีทดสอบที่ได้รับอนุญาตเท่านั้น; รายงานข้อจำกัด unknown delivery outcome โดยไม่อ้างว่า exactly-once
- อัปเดต requirement matrix R1–R7 เป็น pass/fail พร้อมลิงก์หลักฐาน และบันทึก UAT/ข้อจำกัดที่ยังเหลือ

**เกณฑ์ผ่าน:** ไม่มีประเด็นวิกฤตค้างในขอบเขตที่ทดสอบ กู้ข้อมูลและงานค้างได้ตามที่ออกแบบ และผลคุณภาพ/latency ตรวจซ้ำได้ การผ่าน tests ไม่ใช่คำรับรองว่าไม่มี hallucination ในทุกคำถาม

## การแบ่งงานเมื่อเริ่มลงมือ

- **Codex:** gold/evaluator, retrieval และ grounding, รวมงานและตรวจผลกับ requirements
- **Claude:** ชุดทดสอบ LINE recovery/deployment และเอกสารปฏิบัติการ ตามขอบเขตไฟล์ที่ตกลงก่อนเริ่ม
- แบ่งไฟล์ไม่ให้แก้ทับกัน ให้แต่ละงานส่ง diff และผลตรวจจริง แล้ว review รวมก่อนนับว่าเสร็จ แผนนี้ยังไม่ได้สั่ง Claude รอบใหม่

## เริ่มงานรอบถัดไป

1. ทำ coverage matrix และตรวจต้นฉบับของกรณีตาราง/หน่วย/หลายประเด็นก่อน
2. สร้าง gold dev/holdout ที่ตรึงไว้ และปรับ evaluator ให้อ่าน gold นี้
3. รัน baseline และตัดสินใจแก้ reranking จากผลวัด ก่อนปรับ latency หรือเปลี่ยนโหมด PDF

## คำสั่งที่มีอยู่แล้ว

รันจาก repository root; คำสั่งประเมิน retrieval/live ใช้ API และอาจมีค่าใช้จ่าย ส่วน annotation schema และ repeated-load harness เป็นงานที่จะเพิ่มตามแผน

```powershell
.venv/Scripts/python.exe -B -m pytest -q tests -p no:cacheprovider
.venv/Scripts/python.exe -B -m scripts.audit_contract_gaps --output docs/NEXT_CONTRACT_GAPS.json
.venv/Scripts/python.exe -B -m scripts.eval_retrieval --config global/none --output docs/NEXT_RETRIEVAL_BASELINE.json
.venv/Scripts/python.exe -B -m scripts.eval_retrieval --config global/crop --output docs/NEXT_RETRIEVAL_CROP.json
.venv/Scripts/python.exe -B -m scripts.eval_retrieval --config global/legacy --output docs/NEXT_RETRIEVAL_LEGACY.json
.venv/Scripts/python.exe -B -m scripts.evaluate_acceptance --output docs/NEXT_LIVE_ACCEPTANCE.json
.venv/Scripts/python.exe -B -m scripts.verify_ingestion
```

รายงาน retrieval จาก evaluator ปัจจุบันยังเป็น baseline ของ gold เดิม ต้องประเมินใหม่หลังขั้นที่ 1–2 ก่อนใช้ตัดสิน release
