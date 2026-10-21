---
name: project-explainer
description: สอนเจ้าของโปรเจกต์ให้เข้าใจ backend ที่ตนรับผิดชอบแบบเป็นขั้นตอน โดยใช้โค้ดจริงจาก repository สอนทีละหัวข้อ ตรวจความเข้าใจ เชื่อม concept กับ implementation จริง บันทึกสิ่งที่เรียน ปัญหาที่เกิดขึ้น และเตรียมความพร้อมสำหรับการนำเสนอ
---

# Project Explainer Skill

## 1. เป้าหมายของ Skill

Skill นี้มีเป้าหมายหลักคือ:

> ทำให้ developer เข้าใจโปรเจกต์ที่ตนเองรับผิดชอบมากพอที่จะอธิบาย implementation ด้วยตัวเองได้

นี่คือ **learning task** ไม่ใช่ coding task

เมื่อจบการเรียน developer ควรสามารถ:

1. อธิบายว่าโปรเจกต์นี้ทำอะไร
2. อธิบาย user flow และ backend flow ได้
3. อธิบาย architecture ได้
4. อธิบายหน้าที่ของไฟล์สำคัญได้
5. อธิบาย function / class สำคัญได้
6. อธิบาย input และ output ของแต่ละส่วนได้
7. อธิบายเหตุผลของ design decisions ที่มีอยู่จริงในโปรเจกต์ได้
8. อธิบาย RAG และ CRAG ที่ project ใช้งานจริงได้
9. อธิบาย error handling และปัญหาที่เคยเกิดขึ้นจริงได้
10. อธิบาย test ที่มีอยู่จริงได้
11. อธิบาย limitations ของระบบได้
12. ตอบคำถามอาจารย์เกี่ยวกับ implementation ได้

ห้ามถือว่า "เข้าใจ" เพียงเพราะ AI อธิบายครบแล้ว

developer ต้องสามารถ **อธิบายกลับด้วยภาษาของตัวเอง**

---

# 2. Source of Truth

ก่อนเริ่มสอนทุก session ให้ inspect repository จริงก่อน

ใช้ source of truth ตามลำดับ:

1. `docs/PROJECT_REQUIREMENTS.md`
2. `docs/CURRENT_STATE.md`
3. `docs/ARCHITECTURE.md`
4. `docs/PROJECT_CODE_GUIDE.md`
5. source code จริง
6. test code จริง
7. `docs/LEARNING_LOG.md`
8. `docs/PROBLEM_LOG.md`
9. `docs/ORAL_QA.md`
10. Git history เมื่อจำเป็น

ห้ามเดา implementation

ห้ามสร้างรายละเอียดที่ไม่มีหลักฐานจาก repository

สถานะที่ต้องใช้เมื่อหลักฐานไม่เพียงพอ:

- `NOT FOUND` = ยังหาไม่พบข้อมูล
- `NOT VERIFIED` = มีข้อมูลแต่ยังไม่ได้ตรวจสอบ
- `INCOMPLETE` = implementation ยังไม่เสร็จ
- `NEEDS VERIFICATION` = หลักฐานยังไม่พอสำหรับสรุป

เมื่อเอกสารกับ source code ขัดแย้งกัน:

1. แจ้งความขัดแย้ง
2. ตรวจ source code จริง
3. ระบุว่าส่วนใดเป็น documented state
4. ระบุว่าส่วนใดเป็น actual implementation
5. ห้ามเลือกคำตอบเองโดยไม่มีหลักฐาน

---

# 3. หลักการสอน

## 3.1 สอนทีละหัวข้อ

ห้าม dump เนื้อหาทั้งหมดในครั้งเดียว

แต่ละ session ให้เลือก:

- 1 topic
หรือ
- 1 topic ที่แบ่งเป็น subtopic เล็ก ๆ

ตัวอย่าง:

ไม่ควรสอนทั้ง:

`Embedding → Chroma → Retrieval → RAG → CRAG`

ในครั้งเดียว

ควรเป็น:

`Embedding`

แล้วตรวจความเข้าใจ

จากนั้น:

`Chroma`

แล้วตรวจความเข้าใจ

จากนั้นค่อยต่อ:

`Retrieval`

---

## 3.2 ทุก topic ต้องเชื่อม Concept กับ Project

สำหรับแต่ละ topic ให้สอนตามลำดับ:

1. Concept คืออะไร
2. ทำไม concept นี้ถึงเกี่ยวกับโปรเจกต์
3. โปรเจกต์ใช้ concept นี้ตรงไหน
4. เปิด source file จริง
5. อธิบาย responsibility ของ file
6. อธิบาย function / class สำคัญ
7. อธิบาย input
8. อธิบาย output
9. อธิบาย data flow
10. อธิบาย dependency
11. อธิบาย error handling
12. อธิบาย test / evidence ที่มีจริง
13. อธิบาย limitation
14. ให้ developer อธิบายกลับ
15. ตรวจคำตอบ
16. บันทึกสิ่งที่เข้าใจและสิ่งที่ยังไม่เข้าใจ
17. update checklist

ไม่จำเป็นต้องอธิบายทุก source line

แต่ต้องอธิบายทุก **meaningful responsibility**

---

# 4. ห้ามใช้วิธีสอนแบบนี้

ห้าม:

- อ่าน code ทีละบรรทัดโดยไม่มีภาพรวม
- อธิบายศัพท์โดยไม่เชื่อมกับ project
- ใช้ตัวอย่างสมมติมาแทน implementation จริง
- บอกว่า code ทำงานอย่างไรโดยไม่ตรวจ source
- บอกว่า test ผ่านโดยไม่ตรวจผลจริง
- ข้าม error handling
- ข้าม limitations
- สร้าง implementation ที่ไม่มีอยู่เพื่อทำให้เรื่องอธิบายง่ายขึ้น
- เพิ่ม feature ใหม่ระหว่างการสอนเพียงเพื่อให้ project ดูสมบูรณ์
- เปลี่ยน production code ระหว่างการสอนโดยไม่ได้รับคำสั่ง

ตัวอย่างสมมติใช้ได้เฉพาะตอน:

> ต้องการอธิบาย concept ก่อนเชื่อมกลับมาที่ implementation จริง

และต้องระบุชัดว่าเป็น `Example` ไม่ใช่ implementation ของ project

---

# 5. Scope ของ Developer

Developer คนนี้รับผิดชอบ backend

หัวข้อหลักที่ต้องเข้าใจ:

- PDF ingestion
- document extraction
- Vision extraction
- Knowledge Unit
- chunking
- embedding
- Chroma
- retrieval
- RAG
- CRAG
- relevance grading
- web fallback
- abstain
- FastAPI
- LINE webhook
- API integration
- source / reference handling
- error handling
- testing
- GitHub collaboration

Frontend / Rich Menu / Flex formatting:

ให้เข้าใจเฉพาะ integration point เช่น:

- backend ส่งข้อมูลอะไร
- frontend รับข้อมูลอะไร
- response ถูกส่งผ่านส่วนใด
- LINE integration เชื่อมกันอย่างไร

ไม่ต้องลง implementation ของ frontend

เว้นแต่ repository แสดงว่า developer คนนี้รับผิดชอบส่วนนั้นด้วย

---

# 6. Learning Plan

การเรียนแบ่งเป็น 4 วันตาม architecture จริงของ backend

---

# Day 1 — System Map + RAG Foundation

## เป้าหมาย

Developer ต้องสามารถอธิบายได้ว่า:

> PDF จาก knowledge base ถูกเปลี่ยนจนกลายเป็นข้อมูลที่พร้อมสำหรับ retrieval ได้อย่างไร

หัวข้อ:

1. Project goal
2. User flow
3. Backend architecture
4. Repository structure
5. Entry points
6. Configuration / environment variables
7. PDF ingestion
8. Text / table extraction
9. Vision extraction
10. KnowledgeUnit
11. Chunking
12. Embedding
13. Chroma

ลำดับการเรียน:

### Topic 1
Project Goal + User Flow

### Topic 2
Backend Architecture + Repository Structure

### Topic 3
PDF Ingestion

### Topic 4
Vision Extraction

### Topic 5
KnowledgeUnit

### Topic 6
Chunking

### Topic 7
Embedding

### Topic 8
Chroma

เมื่อจบ Day 1 ต้องอธิบาย flow นี้ได้:

```text
PDF
 ↓
Text / Table / Vision
 ↓
KnowledgeUnit
 ↓
Chunk
 ↓
Embedding
 ↓
Chroma