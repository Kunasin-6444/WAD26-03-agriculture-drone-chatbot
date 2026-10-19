> Historical snapshot before the 2026-10-17 MD overhaul. Not current instructions or status. Relative Markdown links rebased for this location.

# ตรวจโครงการเทียบ requirements และแนวทางใช้งานจริง — 2026-10-16

> Follow-up 2026-10-17: the original R3 row-swap and R7 duplicate-event probes now pass.
> See [COLLAB_FIXES_2026-10-17.md](../../../COLLAB_FIXES_2026-10-17.md) for scope, tests and remaining
> limitations. This audit preserves the findings as they existed on 2026-10-16.

## ข้อสรุป

โปรเจกต์ตอบโจทย์ได้บางส่วน แต่ยังไม่ผ่าน requirements ทั้งหมดและยังไม่ควรเรียกว่า production-ready
การนับจำนวน tests ที่ผ่าน หรือการมีแหล่งอ้างอิงท้ายคำตอบ ไม่ได้พิสูจน์ว่าคำตอบถูกต้องตามแถวตาราง

การ extract → normalize → chunk → embed → index เป็นแนวทาง RAG ปกติ
ปัญหาของ ingestion เดิมอยู่ที่การตรวจความครบถ้วน แคช การแทนที่ข้อมูล และการทดสอบผล
ไม่ใช่จำนวนขั้นตอนเพียงอย่างเดียว แนวทางออกแบบควรเลือก parser, chunking และ retrieval จากผลประเมินจริง
ตาม [Microsoft RAG design/evaluation guide](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/rag/rag-solution-design-and-evaluation-guide)

โหมด PDF โดยตรงที่เพิ่มในการสนทนานี้เป็นการทดลอง ไม่ใช่การอัปเกรดที่พิสูจน์ว่าดีกว่า
และยังไม่สอดคล้อง R2 ที่กำหนด BM25/hybrid จึงไม่ใช้เป็นค่าเริ่มต้น

## ขอบเขตและหลักฐาน

- อ่าน `PROJECT_REQUIREMENTS.md` เทียบกับ ingestion, retrieval, generation/verification, CRAG, Tavily, LINE และการติดตั้ง
- ตรวจฐานจริง `drone_knowledge`: 774 chunks, 7 PDFs, 219 หน้า; integrity check ผ่าน
- ทดสอบการเสียข้อมูลเมื่อ upsert ล้มเหลว, cache invalidation, การนำเข้าหน้าขัดข้อง และการสร้างอ้างอิงปลอมจากข้อความเอกสาร
- ทำ failure probes แบบ offline สำหรับการจับคู่ตัวเลขผิดแถวและ LINE event ซ้ำ
- ไม่ส่งข้อความ LINE จริง และไม่แก้ข้อกำหนดเพื่อทำให้ implementation ดูเหมือนผ่าน
- ไม่มีการ re-ingest ฐานจริงทั้งชุดใน audit นี้ ข้อมูลเดิมจึงยังไม่ได้รับ provenance ใหม่ย้อนหลัง
- การตรวจนี้ไม่ใช่ penetration test, dependency vulnerability scan หรือการรับรองความถูกต้องทางเกษตร/กฎหมาย

## เทียบ requirements

| ข้อกำหนด | สิ่งที่พบ | สถานะ |
|---|---|---|
| R1 แหล่งข้อมูล/metadata/ภาพ/ตาราง | มี native text/table และ selective Vision; ครบทุกหน้าใน integrity check แต่ยังไม่มี ground truth สำหรับเนื้อหาในภาพทุกหน้า | ผ่านบางส่วน |
| R2 hybrid + domain/crop/topic reranking | โหมดหลักมี dense + corpus BM25 + RRF และรวมหลักฐานรายหน้า; `RETRIEVER_RERANK=none` จึงไม่เปิด domain/topic reranking ตามข้อความ R2 | ไม่ตรงข้อกำหนดทุกข้อ |
| R3 ตอบจากหลักฐานและอ้างอิง | ตรวจ ID/quote/ตัวเลขและ label บางประเภทได้ แต่ quote หลายแถวยังยอมให้หยิบค่าของอีกแถว | ยังมีช่องว่างระดับสูง |
| R4 CRAG | มี sufficient/partial/insufficient, ค้นเว็บเมื่อข้อมูลไม่ครบ และคงคำตอบบางส่วนที่ตรวจแล้ว | มี implementation และ offline contracts; ยังต้องประเมิน live |
| R5 Tavily + URL | ค้น/อ่านข้อมูลจริง จำกัดแหล่งตามนโยบาย และสร้าง URL ฝั่ง server | มี implementation; freshness/coverage ยังต้องตรวจจริง |
| R6 abstain | ไม่มีหลักฐานจะไม่เดา; แยกกรณี LLM ล่มออกจากหลักฐานไม่พอในบางเส้นทาง | มี implementation; R3 ยังทำให้คำตอบผิดบางแบบผ่านได้ |
| R7 LINE | ตรวจ signature และเรียก Reply API ได้; รอ RAG ก่อนคืน HTTP 200 และไม่มี event deduplication | ฟังก์ชันหลักมี แต่ operational reliability ไม่ครบ |
| Quality/reproducible ingestion | เดิมแคช/การรายงาน/การ publish มีช่องโหว่; แก้หลายจุดใน audit นี้ | ดีขึ้น แต่ยังไม่ใช่ transactional KB versioning |

อีกความไม่ตรงกัน: source policy ยังยกเว้นไฟล์ `ขั้นตอนการยื่นขออนุญาต...pdf` ด้วย
ขณะที่รายการชื่อไฟล์ยกเว้นใน R1 ระบุสองชื่อ การใช้ CAAT สำหรับเนื้อหากฎหมายเป็นทิศทางเดียวกัน
แต่ควรระบุขอบเขตนี้ใน requirements ให้ชัด ไม่ควรแก้โดยนำข้อมูลกฎหมายจาก PDF มาเป็นแหล่งหลักทันที

## ช่องว่างที่ยังต้องแก้ก่อนใช้งานจริง

### สูง: ตัวเลขอยู่ในหลักฐานจริง แต่ผูกกับแถวผิดได้

ตำแหน่ง: `app/rag/evidence.py::parse_grounded_result`, `app/rag/claim_consistency.py::claim_inconsistency`

กรณีจำลองที่ทำซ้ำได้:

```text
หัวฉีด | รอบ (rpm) | ปริมาณ (ml/หัวฉีด)
พัดส้ม | 1600 | 500
พัดแดง | 1600 | 1150
```

หากโมเดล quote ทั้งตาราง แล้วตอบว่าพัดส้มมีปริมาณ 1150 ml ระบบยังยอมรับเป็น `sufficient`
เพราะชื่อและตัวเลขทุกตัวปรากฏในหลักฐาน แม้ความสัมพันธ์จะผิด
นี่เป็นการพิสูจน์ช่องโหว่ด้วยข้อมูลจำลอง ไม่ใช่อัตราคำตอบผิดของโมเดลจริง

ควรเปลี่ยนไปใช้หลักฐานตารางที่รักษา row/column/header/cell identity และผูก claim กับรายการนั้น
พร้อมชุดทดสอบสลับค่า/หน่วย/ชื่อระหว่างแถว การเพิ่ม keyword เฉพาะคำถามหรือทำ prompt ให้ยาวขึ้นไม่ปิดช่องว่างนี้
การตรวจ quote ยังจำเป็น แต่ไม่เพียงพอสำหรับ semantic entailment

### สูง: LINE event เดิมประมวลผลและตอบซ้ำ

ตำแหน่ง: `app/api/webhook.py::webhook`

ทดสอบ signed webhook เดียวกันสองครั้ง ด้วย `webhookEventId` เดิมและ mock การส่ง LINE:
ได้ HTTP 200 ทั้งคู่ แต่เรียก pipeline สองครั้งและ reply สองครั้ง
การ offload ไป thread pool ช่วยไม่ให้ event loop ค้าง แต่ endpoint ยังรอคำตอบก่อน ACK
และการ push เมื่อ reply ล้มเหลวทุกชนิดอาจทำให้ส่งซ้ำในกรณี timeout ที่ไม่ทราบผลการส่ง

ควรรับ event เข้าคิวที่บันทึกสำเร็จก่อน ACK และกันซ้ำด้วย `webhookEventId`
ให้ worker จัดการตอบ พร้อมสถานะ delivery และนโยบาย retry ที่แยก permanent/temporary/unknown outcome
สำหรับ MVP เครื่องเดียว สามารถประเมิน SQLite inbox + worker ได้ ไม่จำเป็นต้องเพิ่ม Redis/PostgreSQL
หากใช้เพียง BackgroundTasks ต้องประกาศชัดว่ามีโอกาสงานหายเมื่อ process ตาย
แนวทาง async และ event ID อิง [LINE webhook guidance](https://developers.line.biz/en/docs/messaging-api/receiving-messages/)

### กลาง: คะแนน retrieval ดูดีกว่าความเข้มของชุดทดสอบ

`tests/data/retrieval_gold.json` มี 25 คำถาม โดย gold pages มาจาก regex ในข้อความที่ ingest แล้ว
บางกรณีกว้างมาก เช่น d17 จับได้ 68 หน้า จาก 219 หน้า จึงอาจนับ hit ทั้งที่หน้านั้นตอบคำถามไม่ได้ครบ
เนื้อหาที่ OCR ตกหล่นจะไม่ปรากฏใน gold ซึ่งทำให้ประเมินปัญหา ingestion ไม่ครบด้วย

ควร annotate file/page และข้อเท็จจริงที่ต้องตอบจาก PDF ต้นฉบับโดยตรง
แยก dev/holdout ที่ไม่ปรับตามผลตัวค้นหา และวัด answer correctness/coverage/abstention เพิ่ม
ผลเดิม hit@8 17/17 และ 8/8 เป็นหลักฐานชุดเล็ก ไม่ใช่การรับรองคุณภาพ

### กลาง: requirement บังคับวิธี rerank แต่หลักฐานเดิมเลือกปิดวิธีนั้น

โค้ดบันทึกผล global/none ดีกว่า heuristic legacy ในชุดทดสอบเดิม
จึงไม่ควรเปิด heuristic เพียงให้ตรงข้อความ requirement โดยไม่ตรวจผล
ต้องตัดสินจากเป้าหมาย relevance/coverage ที่วัดได้ แล้วทำให้ข้อกำหนดและค่าที่ deploy ตรงกัน
ยังไม่ได้เปลี่ยน R2 เพื่อซ่อนความไม่ตรงกันนี้

### กลาง: ความพร้อมด้าน quota, cache และ deployment

- live report เดิม 2026-10-15 ได้ 22/28 contract-pass; เป็น automatic checks ไม่ใช่คะแนนความจริงทั้งหมด
- provider เคยคืน quota/auth errors; ต้องวัด capacity ของ credential/tier ที่จะใช้งานจริง
- answer cache ผูกกับข้อความคำถามและ TTL ยังไม่ผูกกับ KB revision/mode; การอัปเดตฐานหรือเปลี่ยนโหมดควร invalidate cache
- root health endpoint ไม่ได้ตรวจว่า KB พร้อมตอบ; ต้องแยก liveness/readiness ให้เหมาะกับ host
- ยังไม่ยืนยัน backup/restore, process restart, webhook redelivery, หรือ load test บน hosting จริง

## สิ่งที่แก้แล้วใน audit นี้

1. Vision cache ผูกกับ SHA-256 ของ PDF, model และ cache/prompt version แทนชื่อไฟล์อย่างเดียว
2. ตัด `sleep(2.5)` ทุกหน้า ซึ่งเดิมเพิ่มเวลารอคงที่ 547.5 วินาทีสำหรับ 219 หน้า แม้ cache hit/native-only
3. จำกัด Vision timeout/retries และไม่ sleep หลัง rate-limit failure ครั้งสุดท้ายที่ไม่มีการลองต่อ
4. cache text embeddings ตามเนื้อหา/model/dimensions; query embedding ยังใช้ budget เดิม
5. upsert ชุดใหม่ก่อนลบ stale IDs ทำให้ upsert ถูกปฏิเสธแล้วไม่ลบชุดเดิมก่อน
6. จับ exception รายหน้า ประมวลผลหน้าอื่นต่อ รายงาน failed/degraded/empty และให้ CLI/batch คืน nonzero เมื่อไม่ครบ
7. เก็บ JSON report และ canonical Knowledge Units/chunks ใน `.records.json` เพื่อ debug โดยไม่ต้องอ่าน PDF ใหม่ทุกครั้ง
8. ส่ง source SHA/extraction provenance ผ่าน chunk metadata; ป้องกัน canonical filename/page ถูก metadata เสริมทับ
9. BM25 cache ตรวจเนื้อหาจริง จึงไม่ค้างกับข้อมูลเก่าเมื่อ upsert แล้วจำนวน chunks เท่าเดิม
10. ส่ง `Evidence` จาก metadata แบบมีโครงสร้างเข้า CRAG ทั้ง text/direct mode แทน parse ชื่อไฟล์/หน้าจากข้อความ PDF
    มี regression ที่ก่อนแก้เอกสารสามารถแทรกหัวข้ออ้างอิงแล้วทำให้ตอบอ้าง `forged.pdf, หน้า 999`
11. pin dependency constraints จาก environment ที่ `pip check` ผ่าน และระบุ Python 3.12.10
12. acceptance CLI คืน nonzero เมื่อ contract หรือ latency ไม่ผ่าน และไม่อนุญาต evaluation ว่าง
    เดิมคำสั่งคืน exit code 0 แม้ผลรายงานล้มเหลวทั้งหมด ทำให้ automation เข้าใจผิดได้

ข้อจำกัดของข้อ 5: upsert และ cleanup ยังเป็นคนละ operation ไม่ใช่ transaction ครอบทั้ง collection
หาก cleanup ล้มเหลวอาจมี stale chunks; หากต้องการ atomic publish จริงควรใช้ KB generations + active version switch
ข้อ 9 วัดกับ 774 chunks: build ประมาณ 445 ms, warm freshness check median ประมาณ 47.5 ms (10 รอบ, local เท่านั้น)
ต้องเปลี่ยนเป็น revision/inverted index ที่เหมาะสมเมื่อ corpus โตขึ้น
dependency constraints เป็น snapshot ของ Windows environment ที่ทดสอบ ไม่ใช่ผล clean-install/cross-platform หรือ CVE scan

## ทางเลือกสถาปัตยกรรมที่ควรประเมิน

| ทางเลือก | เหมาะเมื่อ | สิ่งที่ต้องพิสูจน์กับข้อมูลเรา |
|---|---|---|
| Classic RAG: layout-aware extraction + structured tables + hybrid index | ต้องการ exact terms, หน่วย, ตาราง และคำอ้างอิงที่ตรวจได้ | ความถูกต้องของแถว/คอลัมน์/OCR และเวลา ingest จริง |
| Direct page embeddings + PDF reading ตอนตอบ | ภาพ/แผนผังสำคัญ และยอมรับค่าอ่าน PDF ตอนถามครั้งแรกได้ | retrieval coverage, cold latency, การตอบตัวเลข/หน่วย และ R2 ที่ขาด BM25 |
| Parser เช่น Docling | ต้องการ layout/table structure ที่ชัดกว่า custom heuristics | Thai OCR/table accuracy, model downloads, CPU/RAM และ throughput |
| Managed retrieval เช่น Gemini File Search | ต้องการลดงานดูแล chunk/embed/index เอง | การครอบคลุมภาพ/ตารางภาษาไทย, page citations, source policy, latency/cost และข้อกำหนด Chroma/BM25 ที่ต้องเปลี่ยน |

[Docling](https://docling-project.github.io/docling/_generated/examples/full_page_ocr/) รองรับ OCR/table structure เป็นทางเลือกทางเทคนิค
แต่ยังไม่ได้ติดตั้งหรือ benchmark กับชุด PDF นี้
[Gemini File Search](https://ai.google.dev/gemini-api/docs/file-search) จัดการงาน retrieval หลายส่วนให้
แต่ยังไม่ได้พิสูจน์ว่าแทน requirements ของเราได้ครบ การเป็น managed service ไม่ได้รับประกันตารางไทยถูกต้อง

ข้อเสนอสำหรับข้อมูลชุดนี้คือทำ extraction ที่รักษาโครงสร้างและสร้างหลักฐานตรวจสอบได้ไว้ก่อนตอบ
แล้วประเมิน hybrid retrieval เป็น baseline เพราะโจทย์มีชื่อหัวฉีด ตัวเลข และหน่วย
เลือกเปลี่ยน parser/service เมื่อชนะบนชุดเอกสารจริง ไม่ใช่เลือกจากชื่อ library หรือจำนวนขั้นตอน

## วิธีตรวจซ้ำและเกณฑ์ก่อนเปลี่ยนระบบหลัก

```powershell
.venv/Scripts/python.exe -m pytest -q tests -p no:cacheprovider
.venv/Scripts/python.exe -m scripts.verify_ingestion
.venv/Scripts/python.exe -m scripts.audit_contract_gaps
.venv/Scripts/python.exe -m pip check
```

`audit_contract_gaps` ตั้งใจคืน exit code 1 ขณะยังมี R3/R7 gaps; ดู `CONTRACT_GAP_REPORT.json`
อย่านับ pytest ที่ผ่านเป็นการปิดช่องว่างเหล่านี้

ผลหลังแก้ล่าสุด: **180 tests และ 41 subtests ผ่าน** มี Starlette deprecation warning เดิมหนึ่งรายการ
`scripts.verify_ingestion` ผ่านกับ 774 chunks และ `pip check` ไม่พบ dependency conflicts
failure probes ยังพบสองช่องว่างระดับสูงตามข้างต้น

Live smoke หลังแก้ citation boundary (`AUDIT_LIVE_ACCEPTANCE_SMOKE.json`):
automatic contract checks ผ่าน **3/3** แต่ latency ผ่าน **0/3** เทียบเป้าหมาย 8 วินาที
ใช้เวลา 11.047, 21.579 และ 12.437 วินาที (mean 15.021, sample p95 21.579)
พบ primary-provider authentication error และ web timeout ระหว่างรัน
ผลนี้ยืนยันเส้นทางตัวอย่างหลังแก้ ไม่พิสูจน์คุณภาพทั้ง corpus และไม่ใช่การเปรียบเทียบก่อน/หลังที่ควบคุม provider load
การแก้ exit code ของ harness หลังรันนี้ทำให้การรันที่มีผลแบบเดียวกันจะคืน nonzero อย่างถูกต้อง

ก่อนเปลี่ยน default: ใช้ corpus/คำถาม/ข้อเท็จจริงต้นฉบับชุดเดียวกัน วัด ingestion completeness,
table cell correctness, retrieval recall/rank, answer correctness, abstention, cold/warm p50/p95 และ API cost
ต้องรวม unsupported questions, แถวสลับค่า, หน่วยผิด, API outage, event ซ้ำ และ process restart
เกณฑ์ release ที่ควรยึดคือไม่มี false acceptance ใน negative contract fixtures และไม่มีการตอบ LINE ซ้ำใน delivery tests
พร้อมผล live evaluation ที่ผ่านเกณฑ์ที่ตกลงไว้ ไม่อ้างว่าได้ zero hallucination สำหรับทุกคำถาม
