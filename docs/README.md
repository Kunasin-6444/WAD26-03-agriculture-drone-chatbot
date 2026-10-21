# เอกสารโปรเจกต์

อัปเดต 2026-10-17: รวมข้อกำหนด สถานะ และแผนให้มีเจ้าของข้อมูลเพียงไฟล์เดียวต่อเรื่อง
อัปเดต 2026-10-21: ส่งต่อจาก Claude Code ให้ Codex — เริ่มที่ NEXT_STEPS_PLAN หัวข้อ "เริ่มตรงนี้" และ CURRENT_STATE หัวข้อ "สรุปสถานะ"

| ต้องการดูอะไร | เอกสารหลัก |
| --- | --- |
| วิธีทำงานของผู้ช่วยและการใช้ API/tests | [AGENTS](../AGENTS.md) |
| ผลลัพธ์ที่ระบบต้องทำได้ | [PROJECT_REQUIREMENTS](PROJECT_REQUIREMENTS.md) |
| สิ่งที่ทำแล้วและข้อจำกัดที่ยังเปิด | [CURRENT_STATE](CURRENT_STATE.md) |
| สิ่งที่จะลงมือต่อ | [NEXT_STEPS_PLAN](NEXT_STEPS_PLAN.md) |
| เลือกการตรวจให้เหมาะกับงาน | [TEST_PLAN](TEST_PLAN.md) |
| โครงสร้างโค้ดที่มีอยู่ | [ARCHITECTURE](ARCHITECTURE.md) (ของ 2026-10-17 — ฉบับล่าสุดดูแผนผังใน CURRENT_STATE) |
| จัดเตรียมข้อมูล PDF | [INGESTION](INGESTION.md) |
| เตรียม host, volumes และ backup | [DEPLOYMENT](DEPLOYMENT.md) |
| การทดลองเสริมที่ยังไม่จำเป็น | [DIRECT_PDF](DIRECT_PDF.md) |

## เอกสารอ้างอิงอื่น

[PROJECT_CODE_GUIDE](PROJECT_CODE_GUIDE.md), [LEARNING_LOG](LEARNING_LOG.md),
[DAILY_LEARNING_CHECKLIST](DAILY_LEARNING_CHECKLIST.md), [ORAL_QA](ORAL_QA.md) และ [PROBLEM_LOG](PROBLEM_LOG.md)
ใช้เพื่อเรียนรู้และดูประวัติ ไม่ใช่ gate ของการพัฒนาหรือสถานะล่าสุด

รายงาน audit, handoff และสถานะเก่าถูกเก็บใน [archive](archive/md-overhaul-2026-10-17/README.md)
ผลรันเก่า (JSON 59 ไฟล์ วันที่ 16–17 ต.ค.) ย้ายไป [archive/reports-2026-10-17](archive/reports-2026-10-17/) เมื่อ 2026-10-19 เพื่อเก็บเป็นหลักฐานประวัติ
เป็นผลตรวจแบบ contract ของรุ่นก่อน ไม่ใช่คะแนนคุณภาพคำตอบของรุ่นปัจจุบัน ผลวัดใหม่อยู่ใน `cache/eval/` (สร้างด้วย `scripts.evaluate_answers`)
