"""
Intent Router
=============
Fast, rule-based intent router that categorizes user queries:
- BOT_USAGE: User asking how to use the bot, how to formulate questions, or requesting example prompts.
- DOCUMENT_QA: Domain queries about agricultural drones, chemicals, spraying, nozzles, regulations, etc.
- GENERAL_CHAT: Greetings and casual queries.
Zero API latency, zero cost.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

IntentType = Literal["bot_usage", "document_qa", "general_chat"]

BOT_USAGE_KEYWORDS = [
    "วิธีพิมพ์คำถาม",
    "วิธีถามคำถาม",
    "พิมพ์คำถามยังไง",
    "ถามยังไง",
    "ถามอะไรได้บ้าง",
    "ตัวอย่างคำถาม",
    "แนะนำการถาม",
    "วิธีใช้งานบอท",
    "วิธีใช้บอท",
    "ฟังก์ชันการทำงาน",
    "บอททำอะไรได้บ้าง",
    "สอบถามอะไรได้บ้าง",
    # Generic phrasing (without the word "บอท") seen in real LINE chat logs
    "ใช้งานยังไง",
    "ใช้งานอย่างไร",
]

BOT_USAGE_RESPONSE = (
    "ยินดีต้อนรับสู่ผู้ช่วย AI โดรนการเกษตรครับ! 🌾🚁\n\n"
    "ท่านสามารถพิมพ์สอบถามข้อมูลเกี่ยวกับโดรนเกษตรได้หลากหลายหัวข้อ โดยพิมพ์ระบุประเด็นที่ต้องการให้ชัดเจน เช่น:\n\n"
    "1. การเลือกใช้หัวฉีดและการพ่นละออง:\n"
    "- หัวฉีดพัดส้มกับพัดฟ้าต่างกันอย่างไร\n"
    "- ฉีดพ่นคลุมดินควรใช้หัวฉีดแบบไหน\n"
    "- แนะนำการเลือกใช้หัวฉีดโดรนเกษตรและอัตราการไหล\n\n"
    "2. การใช้สารเคมีและกำจัดวัชพืช:\n"
    "- ฉีดพ่นยาคุมก่อนอ้อยงอกต้องใช้สารอะไร สำหรับวัชพืชใบแคบ\n"
    "- ข้อควรระวังในการผสมสารกำจัดวัชพืชมากกว่า 1 ชนิด\n"
    "- ช่วงอายุอ้อยต่างๆ ควรพ่นสารอะไร\n\n"
    "3. กฎหมายและการขออนุญาตบิน (CAAT):\n"
    "- ขั้นตอนการยื่นขออนุญาตปฏิบัติการบินโดรนเกษตรเพื่อตนเอง\n"
    "- บินโดรนในสนามบินต้องทำอย่างไร\n\n"
    "4. การตั้งค่าโดรนสำรวจแปลง:\n"
    "- หลักการตั้งค่าโดรนสำรวจแปลงและถ่ายภาพทางอากาศ\n"
    "- การตั้งเงื่อนไขการบินเพื่อให้ภาพถ่ายมีคุณภาพและค่า GSD ที่ดี\n\n"
    "พิมพ์คำถามที่ท่านต้องการทราบเข้ามาได้เลยครับ!"
)


@dataclass
class IntentResult:
    intent: IntentType
    handled_response: str | None = None


def route_intent(query: str) -> IntentResult:
    q = query.strip().lower()
    
    # Check for bot usage intent
    for kw in BOT_USAGE_KEYWORDS:
        if kw in q:
            return IntentResult(
                intent="bot_usage",
                handled_response=BOT_USAGE_RESPONSE,
            )
            
    return IntentResult(
        intent="document_qa",
        handled_response=None,
    )
