> Historical snapshot before the 2026-10-17 MD overhaul. Not current instructions or status. Relative Markdown links rebased for this location.

# ผลการเตรียมส่งมอบ — 2026-10-17

ขอบเขตคือเตรียมระบบและแพ็กเกจให้ deploy บน Linux host เครื่องเดียว ยังไม่มี host และยังไม่ได้ส่ง LINE จริงตามข้อตกลงกับผู้ใช้ **การ build/test ผ่านไม่ใช่การรับรองว่าคำตอบจริงและ latency ผ่านครบ** ให้ดูผลแต่ละชุดแยกกันด้านล่าง

**สถานะส่งมอบ:** โค้ดและแพ็กเกจ deploy ผ่านการตรวจด้าน runtime แล้ว แต่ **ยังไม่ผ่าน quality gate สำหรับเปิด production** ผลตอบครบ/quote และ latency ในชุดเต็มยังไม่สม่ำเสมอ รวมทั้งภาพ investment หน้า 38 ที่ยังอ่านไม่ครบ งานรอบนี้จึงไม่ใช่ production approval

มี [ผลรวมในรูป JSON](../../../DELIVERY_VERIFICATION_2026-10-17.json) ที่ตรวจว่า hash ของโค้ดในเครื่อง, targeted live และ Linux runtime ตรงกัน พร้อมเก็บคะแนนเต็มก่อนแก้ transient failover แยกไว้

## พฤติกรรมที่แก้แล้ว

- ใช้ KB ก่อน; เมื่อได้คำตอบบางส่วน เก็บข้อที่ตรวจสอบแล้วและค้นเว็บเติมส่วนที่ขาด รองรับ KB + เว็บและ KB + CAAT ในคำตอบเดียว
- แยกแหล่งข้อมูลจริงออกจากข้อความในเอกสาร/เว็บ ป้องกันข้อความปลอม filename/page/URL และ prompt injection มาเปลี่ยน citation
- อ้างอิงท้ายข้อด้วย `[n]`; PDF ระบุชื่อไฟล์และหน้าหรือช่วงหน้าของตารางต่อเนื่อง เว็บระบุชื่อหน้าและ URL เต็มที่ได้จากผลค้นจริง เก็บ path/query/fragment ไม่ยุบลิงก์เป็นโดเมน
- ตรวจ quote, ตัวเลข, หน่วย, แถว/คอลัมน์และตัวหารในตาราง เช่น `ml/หัวฉีด` ไม่กลายเป็น `ml/min` เพียงเพราะแถวนั้นมี RPM ปฏิเสธข้อที่ไม่ผ่านและเก็บข้ออื่นที่รองรับได้
- คำถามระบุ UAVnn จะค้นเฉพาะเอกสารนั้น; คำถามหลายหัวข้อไม่ย้ายชื่อรุ่น/เงื่อนไขข้ามประเด็น และไม่อ้าง PDF เป็นข้อมูลราคาวันนี้
- ส่งข้อความ KB ที่ตรวจผ่านแล้วให้รอบรวมคำตอบคง text เดิม เพื่อรวมข้อซ้ำได้โดยไม่ใช้ heuristic ที่อาจลบข้อเท็จจริงคนละข้อจาก quote เดียวกัน ชื่อพ้องที่ระบบ normalize แล้วถูกส่งอย่างชัดเจนให้โมเดล
- เพิ่ม guard แยกประธาน/เวลา เช่น `ก่อนวัชพืชงอก` ไม่ถูกอ้างเป็น `ก่อนอ้อยงอก` การตรวจต้นฉบับรอบนี้พบว่าข้อ 10 ใน acceptance เดิมใช้คำถามคนละเงื่อนไขกับตาราง UAV06 หน้า 18 จึงแก้ fixture ให้ถามก่อนวัชพืชงอกในไร่อ้อย ตรวจชื่อสารจริงแทน keyword “สาร” และเก็บ `original_query` ในรายงาน พร้อม negative regression ของคำถาม/claim เดิม
- ใช้ dense + BM25 + การจัดอันดับแบบ `global/diverse` เก็บบริบทในหน้าเดียวกันและหลักฐานของคำถามคนละหัวข้อ โดยไม่ใช้ตัวคูณเฉพาะข้อสอบ/หน้า
- แก้ลำดับ failover เมื่อ provider หลักปฏิเสธ quota/auth ให้ลอง provider สำรองที่ตั้งค่าไว้ก่อนเสียเวลากับโมเดลอื่นใน gateway เดิม และเพิ่ม cooldown เมื่อ timeout/connection/5xx เพื่อไม่ใช้โมเดลที่เพิ่งค้างซ้ำในขั้นถัดไป Timeouts ยังนับใน attempt/deadline budget ไม่เปลี่ยน provider/model/key ของผู้ใช้
- warmup ตอนเริ่มบริการ, reuse connection ตาม thread, cache เฉพาะคำตอบ KB ที่เพียงพอ และรวมคำขอ static ที่ซ้ำพร้อมกัน cache เปลี่ยนตาม index/WAL/mode/config
- LINE ใช้ durable SQLite inbox, ACK หลังบันทึกงาน, dedup, lease recovery และแยกกรณีส่งไม่สำเร็จออกจากกรณีไม่ทราบว่าส่งแล้วหรือยัง ไม่อ้างว่า exactly-once

## การทดสอบและข้อจำกัด

ผลที่ตรวจจริง แยกชุดเต็มก่อนแก้ transient failover ครั้งสุดท้ายออกจาก targeted recheck หลังแก้ ไม่ตัดผลที่ล้มเหลวและไม่ใช้รอบที่ดีที่สุดแทนทุกครั้ง:

| การตรวจ | ผล | หลักฐาน |
| --- | --- | --- |
| Offline รุ่นสุดท้าย Windows | 372 passed + 67 subtests, 72.78s | `python -m pytest -q tests -p no:cacheprovider` |
| Clean Linux test image | 371 passed + 67 subtests, 1 skipped, 52.39s | `docker build --target test -t agriculture-drone-chatbot:test .` |
| คำตอบจริง 28 ข้อ ก่อน transient fix | contract 26/28, latency 24/28; p50 5.579s, p95 14.579s | [ผล 28 ข้อ](../../../DELIVERY_ACCEPTANCE_2026-10-17.json) |
| Frozen source gold 12 ข้อ ก่อน transient fix | strict contract 9/12, latency 11/12; p50 2.609s, p95 11.422s | [ผล source gold](../../../DELIVERY_SOURCE_2026-10-17.json) |
| KB + เว็บ / เว็บล้วน / KB + CAAT ก่อน transient fix | contract และ latency 2/3; มี primary timeout 1 คำขอ | [ผลผสมก่อนแก้](../../../DELIVERY_HYBRID_2026-10-17.json) |
| Targeted recheck หลัง transient fix | contract และ latency 3/3; 10.594s / 3.859s / 8.031s | [ผลตรวจซ้ำเฉพาะส่วน](../../../DELIVERY_FAILOVER_RECHECK_2026-10-17.json) |
| Retrieval baseline/ค่าเริ่มต้นบน corpus เดียวกัน | holdout ไม่ถดถอย; รายละเอียดด้านล่าง | `RETRIEVAL_CURRENT_BASELINE_2026-10-17.json`, `RETRIEVAL_VERIFIED_2026-10-17.json` |
| Source gold retrieval | ครบทุกประเด็น@8: dev 8/8, holdout 4/4 | `SOURCE_RETRIEVAL_VERIFIED_2026-10-17.json` |
| ช่องโหว่ table/LINE เดิม | critical gaps 0 | `RELEASE_CONTRACT_GAPS_2026-10-17.json` |
| Windows / Linux runtime startup | liveness/readiness 200; ไม่เรียก provider | `DEPLOYMENT_WINDOWS_SMOKE_2026-10-17.json`, `DEPLOYMENT_LINUX_SMOKE_2026-10-17.json` |
| Uvicorn ตาม CMD จริงใน runtime image | HTTP live/ready ผ่าน, UID 10001, network none, inbox ใหม่; ปิด test container แล้ว | [ผล HTTP ใน container](../../../DEPLOYMENT_LINUX_HTTP_2026-10-17.json) |
| ย้าย KB Windows → Linux | corpus hash และ retrieval scores ตรงกัน ใช้ cached query vectors และปิดเครือข่าย | `DEPLOYMENT_LINUX_RETRIEVAL_2026-10-17.json` |

Linux ข้ามเฉพาะ synthetic Thai-font test ที่ต้องใช้ Windows Tahoma; ข้อนี้ผ่านบน Windows มี Starlette/AnyIO deprecation warning 1 รายการทั้งสองระบบ `pip check` ผ่านทั้ง Windows และ Linux และ `docker compose config --quiet` ผ่าน

ผล 43 คำถามเต็มใช้ runtime SHA `c2fd70580ed5c94aea90274f7bf66ebf4bb5259e4e63156678df646b95f3b078` และไม่มีการแก้โค้ดระหว่างรัน หลังแก้เฉพาะ timeout/5xx failover ใช้ SHA `436b5b03fd2c6686d3eb0cc33dc3319040d1d89dfdd19129aca56e25eb5285e4` ซึ่งตรงกันระหว่าง targeted live recheck และ Linux runtime image **ยังไม่ได้รันชุด 43 ข้อเต็มอีกครั้งบน SHA หลังสุด** targeted 3/3 ไม่ล้างผลล้มเหลวเดิม

อ่าน [การตรวจความหมายจากคำตอบจริง](../../../DELIVERY_SEMANTIC_REVIEW_2026-10-17.md): ชุดเต็มมีคำตอบตกเงื่อนไข RPM, quote ที่โมเดลคัดไม่ตรงจนต้องตอบบางส่วน/abstain และ strict gold ที่ยังไม่รวมหน้าทางเลือกหนึ่งหน้า จึงไม่ควรแปลคะแนนอัตโนมัติเป็น “ความถูกต้องเชิงความหมายทุกข้อ”

Evaluator ใหม่ตรวจ source/aspect, แยก correctness กับ latency, มี exit code เมื่อไม่ผ่าน, รวม request ที่ provider ล้มเหลวในตัวหาร และตรวจว่าโค้ดเปลี่ยนระหว่างรันหรือไม่ ชุด benchmark เก่าที่ตัดสินด้วย keyword และคืน exit 0 เสมอถูกแทนด้วย entrypoint ไปยัง evaluator นี้ เก็บคำถามเก่าเป็น archive ที่ไม่ถือเป็น gold

`provider_error_requests` นับจาก diagnostics ที่คืนมากับคำตอบ ไม่ใช่จำนวน upstream error ทุกครั้งที่ระบบกู้สำเร็จ ระหว่างทดสอบยังพบ 401/429/timeout ใน service logs แม้บาง batch มีตัวนับเป็น 0 ทุก request รวมอยู่ในผล latency แล้ว Primary เคยติด auth/quota และ timeout; การมี secondary ไม่รับรอง capacity หรือ SLO สำหรับโหลดจริง

Source gold ตรึงไว้ 12 ข้อจาก PDF ต้นฉบับ 4 ไฟล์ แยก dev/holdout และตรวจ SHA ของต้นฉบับ **ยังไม่ใช่ semantic certification ครบทุกหน้า/ทุกเอกสาร** ตัวตรวจ quote/ตัวเลข/ตารางช่วยป้องกันความผิดพลาดที่รู้จัก แต่ไม่พิสูจน์ entailment ของทุกประโยคจาก LLM

การแก้ fixture ไม่ได้เปลี่ยน frozen source gold หรือ latency target: ข้อ 13 อนุญาต hybrid ตาม R4 เมื่อ generation ของ KB ถูกปฏิเสธ แต่คงเป้าเวลา 8 วินาทีเพื่อให้เห็นผลของ fallback ที่ไม่จำเป็น ชุด `DEPLOY_CANDIDATE_*` เป็นผลก่อนการซ่อมรอบสุดท้าย (26/28 contract, 25/28 latency; source 12/12; hybrid 3/3) เก็บไว้เป็นประวัติ ไม่ใช้แทนผล `DELIVERY_*`

## สถานะ KB และ ingestion

ปัจจุบันมี 997 chunks จาก PDF ที่อนุมัติ 11 ไฟล์ / 343 หน้า (รวมหน้าว่าง) จากเดิม 7 ไฟล์ / 219 หน้า ไฟล์ขั้นตอนขออนุญาตยังถูกยกเว้นตาม source policy และใช้ CAAT แทน [Native integrity](../../../INGESTION_INTEGRITY_2026-10-17.txt) ผ่าน ไม่มีหน้าที่มีเนื้อหาแต่ไม่มี coverage, ไม่มี duplicate chunks และไม่มี native number ที่หายจาก 2,129 ค่าที่ตรวจต่อหน้า

Retrieval ทั้ง 4 รายงานใช้ corpus SHA-256 เดียวกัน `43a784a02decce1e71ac0a5f020b24a3959f2bc5bed0613367cf222c926b5353`:

| ชุด / split | global/none | global/diverse |
| --- | --- | --- |
| Legacy dev 17 | hit@8 17/17, MRR .9055 | hit@8 17/17, MRR .9055 |
| Legacy holdout 8 | hit@8 8/8, MRR .8167 | hit@8 8/8, MRR .8167 |
| Source dev 8 | ครบทุกประเด็น@8 7/8, MRR .7470 | ครบทุกประเด็น@8 8/8, MRR .7708 |
| Source holdout 4 | ครบทุกประเด็น@8 4/4, MRR .7813 | ครบทุกประเด็น@8 4/4, MRR .7857 |

เก็บ default `global/diverse` ได้โดย holdout ไม่ถดถอย รายงานที่ชื่อ `MAXPAGE` และ `RETRIEVAL_RELEASE` ก่อนหน้านี้เป็น candidate ที่เลิกใช้ ไม่ใช่ค่ารันปัจจุบัน

- กู้เลขปี 2525 ใน UAV08 หน้า 4 และ 6 ซึ่งเคยหายจากการตัด native text ที่ทับกรอบตาราง
- เอกสารใหม่ใช้ `scripts.ingest` และ ingestion v2 (`text_v4`): อ่าน layout, ต่อหัวตาราง/แถวข้ามหน้า, chunk ตามแถว, embed เป็น batch และใช้ cache ไม่เปลี่ยน legacy UAV06–UAV12 ทั้งชุดโดยพลการ
- แก้เส้นขอบตารางจาก Word/Docs ที่ถูกนับซ้ำเป็น diagram จนเรียก Vision โดยไม่จำเป็น
- ปฏิเสธผล Vision ที่วนคำซ้ำหรือจบเพราะ token limit ทั้งจาก API และ cache ไม่เผยแพร่เป็นหลักฐาน
- Vision ล้มเหลวไม่ทับหน้าที่มีข้อมูลเดิม สำหรับหน้าที่ไม่เคยมีข้อมูล เก็บ native text ที่อ่านได้พร้อม `extraction_complete=false` และให้ทั้งไฟล์ยังเป็น incomplete เพื่อ retry ภาพในรอบถัดไป
- การอ่านหน้าหนึ่งไม่สำเร็จ/ได้ข้อมูลว่างไม่ลบหน้าที่เคย publish สำเร็จ ตารางที่มีเฉพาะหัวในหน้าหนึ่งและข้อมูลไปต่ออีกหน้าต้องนับ coverage จาก `page_from/page_end`

การซ่อมข้อมูลจริงมีสำรองก่อนแก้ที่ `cache/ingestion/new_documents_before_quality_repair.json` และรายงาน [การซ่อมเอกสารใหม่](../../../NEW_DOCUMENTS_REPAIR_2026-10-17.json), [native final](../../../NEW_DOCUMENTS_NATIVE_FINAL_2026-10-17.json)

**ยังไม่ครบ:** ภาพตัวอย่างรายงานใน `ฟีเจอร์การลงทุน.pdf` หน้า 38 อ่านด้วย Vision ไม่สำเร็จหลัง 3 attempts (504/read timeout; 219.422s) เก็บ native text ได้แล้ว แต่เนื้อหาใน screenshot ยังไม่ผ่านการตรวจ ห้ามนับว่าการดึงข้อมูลภาพครบทุกหน้า การตรวจ `verify_ingestion` ตรวจ native coverage/ตัวเลข/metadata/duplicates และหัวตาราง ไม่ตรวจตัวเลขที่อยู่เฉพาะในภาพ

## แพ็กเกจ deploy

มี Dockerfile แยก test/runtime, pin Python base digest และ dependency constraints รวม Linux uvloop, runtime UID/GID 10001, persistent volumes สำหรับ Chroma และ inbox/cache, 1 Uvicorn worker, graceful shutdown และ log rotation

Image ที่ build แล้ว: `agriculture-drone-chatbot:release`, ID `sha256:43c0634b30f26a9dc96c046c2e7b056de7a4e358fdaf34b7f301c68616d5b134` Test image: `agriculture-drone-chatbot:test`, ID `sha256:bf93b8a10fe2b99551112adf216c5524d514d97b4b9f7db8f6caf48c96d16317` ไม่มี `.env`/credential/index จริงฝังใน image

`/health/live` ตรวจ process; `/health/ready` ตรวจ index/inbox ที่เขียนได้/worker โดยไม่เรียก provider และไม่แสดงข้อความผู้ใช้ Readiness จึงไม่ใช่การยืนยัน quota

เครื่องมือ snapshot/restore ตรวจ checksum/path และไม่ทับปลายทางเดิม ต้องหยุด app และ ingestion ก่อน backup จริง การทดสอบ boot ใช้ inbox ชั่วคราวและสำเนา KB ไม่ดึงงานค้างของผู้ใช้มาส่ง

ดูขั้นตอน [DEPLOYMENT.md](../../../DEPLOYMENT.md) การทดสอบในเครื่องไม่แทนการทดสอบ HTTPS, persistent volume และ LINE บน host จริง

## Requirement matrix

| Requirement | ผลและขอบเขต |
| --- | --- |
| R1 KB/source policy | implementation และ native integrity ตรวจได้; ภาพ investment หน้า 38 ยัง incomplete และ semantic review ยังเป็น sample |
| R2 hybrid retrieval/reranking | เปิด `global/diverse`; ต้องอ่าน dev/holdout รุ่นปัจจุบันในรายงานที่อ้างด้านบน |
| R3 grounded concise answer | มี guards และ tests; ไม่รับรองทุกคำตอบของ LLM ดู source/live failures จริง |
| R4 partial KB + web | contract tests ครอบคลุม; targeted live ล่าสุด 3/3 แต่ full batch ก่อนแก้มี provider failure 1 ข้อ |
| R5 exact source-page web citation | เก็บ URL ที่ fetch จริง ตรวจ trust ทาง server และผูก citation ต่อข้อ ข้อมูลค้นไม่พบต้อง abstain |
| R6 abstain | แยกหลักฐานไม่พอจาก provider ใช้งานไม่ได้ และไม่แสดงลิงก์ทั่วไปเป็นหลักฐานที่ยืนยันข้ออ้าง |
| R7 LINE | offline integration/restart/duplicate/delivery contracts; ยังไม่มี LINE end-to-end จริงในรอบนี้ |

## งานก่อนเปิดให้ผู้ใช้จริง

1. แก้/ยืนยันผล source/live ที่ยังไม่ผ่าน และวัดซ้ำเมื่อ provider มี quota/capacity เพียงพอ ห้ามตัด request ล้มเหลวออกจากค่า latency
2. อ่านภาพ investment หน้า 38 ใหม่และตรวจตัวเลข/เซลล์จากต้นฉบับ ขยาย semantic gold ให้ครอบคลุมเอกสารใหม่และกรณีเสี่ยงก่อนกล่าวอ้างคุณภาพทั่วทั้ง KB
3. เมื่อมี host: restore/ingest KB, ตรวจสิทธิ์ volumes และการกู้ข้อมูล, ตั้ง HTTPS, ตรวจ provider quota แล้วทดสอบ LINE ด้วยบัญชีที่ได้รับอนุญาต

Direct PDF ยังเป็นโหมดทดลอง ไม่ใช่ค่าเริ่มต้น การเปรียบเทียบครบ corpus/BM25/ต้นทุนการอ่านภาพยังไม่เสร็จ จึงคง text retrieval สำหรับแพ็กเกจนี้
