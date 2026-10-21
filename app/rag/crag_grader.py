"""CAAT air-law/airspace topic routing.

The online pipeline evaluates sufficiency and generates claims in one call
(see rag_service.evaluate_evidence); this module only decides whether a
query must be routed to the designated CAAT source instead of the PDF KB.
"""
from __future__ import annotations

CAAT_KEYWORDS = [
    "กฎหมาย",
    "พ.ร.บ.",
    "พระราชบัญญัติ",
    "ขึ้นทะเบียน",
    "ลงทะเบียนโดรน",
    "กสทช",
    "caat",
    "กพท",
    "น่านฟ้า",
    "เขตห้ามบิน",
    "air space",
    "air law",
    "ใบอนุญาตนักบิน",
    "ใบอนุญาตบิน",
    "ขออนุญาต",
    "ขออนุญาตบิน",
    "ระยะห่างสนามบิน",
    "ห้ามบินสูงเกิน",
    "ยื่นขออนุญาต",
    "ขออนุญาตปฏิบัติการบิน",
    "uas portal",
    "โทษของการบินโดรน",
    "ปรับกี่บาท",
    "ผิดกฎหมายการบิน",
]


def is_caat_air_law_or_airspace_topic(query: str) -> bool:
    return any(keyword in query.lower() for keyword in CAAT_KEYWORDS)
