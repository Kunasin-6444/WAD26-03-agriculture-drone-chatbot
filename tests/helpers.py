import json
from types import SimpleNamespace
from unittest.mock import MagicMock

DOCUMENT_CONTEXT = "[แหล่งข้อมูล 1]\nไฟล์: UAV07.pdf\nหน้า: 12\nประเภท: table\nเนื้อหา:\nหัวฉีดพัดส้ม อัตราการไหล 500 ml/หัวฉีด ที่รอบ 1600 rpm\nความสูง 1.0 m หน้ากว้างพ่น 2.8 m ต่อหัวฉีด"


def result_json(status="sufficient", claims=None, missing=None, caat=False):
    if claims is None:
        claims = [("หัวฉีดพัดส้มมีอัตราการไหล 500 ml/หัวฉีด ที่ 1600 rpm", "D1", "หัวฉีดพัดส้ม อัตราการไหล 500 ml/หัวฉีด ที่รอบ 1600 rpm")]
    return json.dumps({"status": status, "claims": [{"text": text, "evidence": [{"source_id": id, "quote": quote}]} for text, id, quote in claims],
                       "missing_aspects": missing or [], "is_caat_topic": caat, "reason": "ทดสอบตามหลักฐาน"}, ensure_ascii=False)


def llm_client(*contents):
    client = MagicMock()
    client.chat.completions.create.side_effect = [SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=content, reasoning=None), finish_reason="stop")]) for content in contents]
    return client
