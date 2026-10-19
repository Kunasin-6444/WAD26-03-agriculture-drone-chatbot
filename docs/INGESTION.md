# การเตรียมข้อมูล PDF

Text pipeline ปัจจุบันใช้ `scripts.ingest`: layout/native text/tables + selective Vision → structured records/chunks → cached/batched embeddings → publish index
โค้ดหลักอยู่ที่ `app/ingestion/` ข้อมูล legacy บางส่วนในคลังอาจใช้รูปแบบก่อนหน้า
ขนาด chunk และวิธี extraction เป็นทางเลือกทางเทคนิค ไม่ล็อกเป็นกฎ 800 ตัวอักษร/overlap 120

## หลักที่ต้องรักษา

- ใช้ source policy ใน [requirements](PROJECT_REQUIREMENTS.md) รวมข้อยกเว้น CAAT
- เก็บ filename, document ID, หน้า/ช่วงหน้า, source type และ provenance ให้ย้อนตรวจได้
- เก็บหัวตาราง แถว คอลัมน์ หน่วย และเงื่อนไขร่วมกัน ไม่แปลภาพหรือ normalize จนความหมายเปลี่ยน
- แยก complete, incomplete/degraded และ failure ไม่ถือว่า native text สำเร็จแล้วภาพครบด้วย
- เมื่อ debug ให้ดู record/page ที่เกี่ยวข้อง ใช้ cache และ retry เฉพาะที่จำเป็น ไม่เริ่ม ingest ทั้งคลังใหม่
- รักษา index เดิมจนข้อมูลใหม่พร้อม publish และมีทางคืนกลับ ไม่ล้างฐานข้อมูลเพื่อแก้ปัญหาเฉพาะหน้า

## คำสั่งอ้างอิง

ถ้าต้องการดูรายการงานก่อน โดยไม่เรียก embedding/Vision:

```powershell
.venv/Scripts/python.exe -B -m scripts.ingest --dry-run
```

Ingestion จริงและการตรวจเนื้อหาผ่าน provider มีค่า API ต้องอยู่ในขอบเขตที่ผู้ใช้อนุญาต
ใช้ `scripts.ingest --help` ดู options จากโค้ดปัจจุบันก่อนเลือกไฟล์/ช่วงหน้า ไม่คัดลอกคำสั่ง batch เก่ามารันเอง
การแก้ Markdown ไม่เป็นเหตุให้รัน dry-run หรือ ingestion อัตโนมัติ

## ช่องว่างที่ทราบ

รายงานรอบก่อนมี 11 PDF / 343 หน้า / 997 chunks แต่ `ฟีเจอร์การลงทุน.pdf` หน้า 38 ยัง incomplete หลัง Vision timeout
ต้องตรวจภาพและค่ากับต้นฉบับเมื่อแก้หน้านั้น จำนวน chunks และ native integrity ไม่ยืนยัน semantic completeness
การแก้หน้าที่ขาดทำเมื่อมีขอบเขตงานและ API ที่อนุญาต ไม่เป็นเงื่อนไขก่อนให้เจ้าของทดลองถามจากข้อมูลที่มี
ดู [สถานะ](CURRENT_STATE.md) และ [แนวทางตรวจ](TEST_PLAN.md)
