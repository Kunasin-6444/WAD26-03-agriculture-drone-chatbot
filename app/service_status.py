"""Safe service failure codes/messages, independent of RAG, credentials and providers."""
from __future__ import annotations

ERROR_MESSAGES = {
    "quota_exhausted": "โควตาของบริการ AI ที่ใช้ตอบคำถามหมดแล้ว จึงยังตอบคำถามนี้ไม่ได้ครบ กรุณารอให้โควตากลับมาครับ",
    "rate_limited": "บริการที่ใช้ตอบคำถามกำลังจำกัดการเรียกใช้งาน กรุณารอสักครู่แล้วลองใหม่ครับ",
    "timeout": "หมดเวลารอคำตอบจากบริการ จึงยังตอบคำถามนี้ไม่ได้ครบ กรุณาลองใหม่ภายหลังครับ",
    "provider_auth": "บริการที่ใช้ตอบคำถามปฏิเสธสิทธิ์การเข้าถึง กรุณาตรวจการตั้งค่าบัญชีและสิทธิ์ใช้งานครับ",
    "configuration": "ยังไม่ได้ตั้งค่าบริการที่จำเป็นสำหรับคำถามนี้ จึงยังตอบได้ไม่ครบครับ",
    "invalid_response": "บริการ AI ส่งคำตอบกลับมาไม่สมบูรณ์ จึงยังยืนยันคำตอบนี้ไม่ได้ กรุณาลองใหม่ภายหลังครับ",
    "provider_unavailable": "บริการที่ใช้ตอบคำถามขัดข้องชั่วคราว จึงยังตอบคำถามนี้ไม่ได้ครบ ไม่ได้หมายความว่าเอกสารไม่มีข้อมูลครับ",
}


def service_error_code(answer: str) -> str:
    """Recognise only server-owned full failure messages; partial answers stay answers."""
    return next((code for code, message in ERROR_MESSAGES.items() if answer.strip() == message), "")


def common_error(codes: list[str]) -> str:
    """Do not label a mixed pool failure as every model having exhausted its quota."""
    distinct = set(codes)
    return next(iter(distinct)) if len(distinct) == 1 else "provider_unavailable"


def classify_service_error(exc: Exception) -> str:
    """Inspect wrapped failures without exposing their messages, URLs, or keys."""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = getattr(current, "error_code", "")
        if code in ERROR_MESSAGES:
            return code
        detail = str(getattr(current, "body", None) or getattr(current, "message", "") or current).lower()
        if "daily limit" in detail:
            return "quota_exhausted"
        status = getattr(current, "status_code", None) or getattr(current, "code", None)
        if status in {401, 403}:
            return "provider_auth"
        if status == 429:
            return "rate_limited"
        if status in {408, 504}:
            return "timeout"
        if isinstance(current, TimeoutError) or "timeout" in type(current).__name__.lower():
            return "timeout"
        current = current.__cause__ or current.__context__
    return "provider_unavailable"
