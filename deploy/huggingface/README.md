---
title: Agriculture Drone Chatbot
emoji: 🚁
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# ผู้ช่วยนักบินโดรนเกษตร (LINE chatbot)

Space นี้รัน backend ของ LINE chatbot (FastAPI) จาก repo หลัก ไม่มีหน้าเว็บสำหรับผู้ใช้
LINE Webhook URL: `https://<owner>-<space>.hf.space/webhook` — สุขภาพระบบ: `/health/live`, `/health/ready`

สร้างโฟลเดอร์นี้ด้วย `python -m scripts.build_hf_space` ใน repo หลัก (ห้ามแก้ไฟล์ในนี้ตรงๆ)
ค่าที่ต้องตั้งใน Settings → Variables and secrets ดู `docs/DEPLOYMENT.md` หัวข้อ Hugging Face ใน repo หลัก
