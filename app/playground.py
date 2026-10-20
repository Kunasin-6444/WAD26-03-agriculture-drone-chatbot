"""Local manual playground. Demo/startup never imports the RAG or LINE runtime."""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware
from app.service_status import ERROR_MESSAGES, classify_service_error, service_error_code

logger = logging.getLogger(__name__)
ASSETS = Path(__file__).with_name("playground_assets")
_live_lock = threading.Lock()
DEMO_NOTICE = "ข้อมูลจำลองสำหรับลองหน้าจอ ไม่ใช่คำแนะนำหรือหลักฐานจาก KB/web จริง และไม่ได้เรียก AI"
DEMO_ANSWERS = {
    "mixed": (
        "• ส่วนนี้สาธิตคำตอบที่มีหลักฐานจากเอกสาร [1]\n"
        "• ส่วนนี้สาธิตข้อมูลที่ค้นเว็บมาเติมให้ครบคำถาม [2]\n\n"
        "แหล่งอ้างอิง:\n[1] เอกสารจำลอง.pdf, หน้า 12\n"
        "[2] หน้าเว็บตัวอย่าง (ลิงก์สาธิต ไม่ใช่หลักฐานจริง)\n"
        "https://example.org/articles/drone-guide?lang=th#safety"
    ),
    "kb": (
        "• นี่คือตัวอย่างคำตอบจาก KB พร้อมเงื่อนไขที่จำเป็นและเลขอ้างอิง [1]\n\n"
        "แหล่งอ้างอิง:\n[1] เอกสารจำลอง.pdf, หน้า 12–13"
    ),
    "unverified": "ยังไม่พบหลักฐานเพียงพอที่จะยืนยันคำตอบ ส่วนที่ไม่ทราบจะไม่ถูกเติมขึ้นเองครับ",
    "quota": "โควตาของบริการ AI หมดหรือถูกจำกัดการใช้งาน กรุณาตรวจสอบบัญชีผู้ให้บริการ โหมดจำลองยังใช้งานได้ครับ",
}


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    mode: Literal["demo", "live"] = "demo"
    scenario: Literal["mixed", "kb", "unverified", "quota"] = "mixed"

    @field_validator("question")
    @classmethod
    def nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Please enter a question")
        return value


def ask_live(question: str) -> tuple[str, bool]:
    # Lazy import is deliberate: loading a page or trying a demo must not load
    # credentials, open Chroma, start LINE workers or instantiate providers.
    from app.services.ai_service import ask_ai
    answer = ask_ai(question)
    return answer, bool(service_error_code(answer))


def result(answer: str, started: float, mode: str, status: str = "ok", code: str | None = None) -> dict:
    return {
        "answer": answer,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        "mode": mode,
        "status": status,
        "error_code": code,
        "notice": DEMO_NOTICE if mode == "demo" else "",
    }


def live_response(question: str, started: float) -> JSONResponse:
    # Held inside the worker thread until the provider actually finishes, even
    # when a browser disconnects. No queued or automatic follow-up questions.
    if not _live_lock.acquire(blocking=False):
        return JSONResponse(result("มีคำถามจริงกำลังประมวลผลอยู่ กรุณารอให้จบก่อนส่งใหม่ครับ",
                                   started, "live", "error", "busy"), status_code=409)
    try:
        answer, unavailable = ask_live(question)
        if unavailable:
            code = service_error_code(answer) or "provider_unavailable"
            return JSONResponse(result(
                ERROR_MESSAGES[code], started, "live", "unavailable", code), status_code=503)
        return JSONResponse(result(answer, started, "live"))
    except Exception as exc:
        # Never return raw provider messages: they can include credentials,
        # request content or internal URLs. Log only the exception type.
        logger.warning("Playground request failed (%s)", type(exc).__name__)
        code = classify_service_error(exc)
        if isinstance(exc, (ImportError, RuntimeError)) and (
            isinstance(exc, ImportError) or "is not set" in str(exc)
        ):
            code, message = "configuration", "การตั้งค่าระบบยังไม่ครบ กรุณาตรวจ dependencies และ .env ตาม README ครับ"
        elif code != "provider_unavailable":
            message = ERROR_MESSAGES[code]
        else:
            code, message = "request_failed", "ตอบคำถามไม่สำเร็จ กรุณาตรวจ log ของบริการ หรือใช้โหมดจำลองต่อได้ครับ"
        return JSONResponse(result(message, started, "live", "unavailable", code), status_code=503)
    finally:
        _live_lock.release()


app = FastAPI(title="Drone Chatbot · Local Playground", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])


@app.middleware("http")
async def local_browser_only(request: Request, call_next):
    if request.method not in {"GET", "HEAD"}:
        expected_origin = f"{request.url.scheme}://{request.headers.get('host', '')}"
        if (request.headers.get("origin") != expected_origin
                or request.headers.get("sec-fetch-site") == "cross-site"):
            response = JSONResponse({"detail": "Only same-origin local requests are allowed"}, status_code=403)
        elif request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
            response = JSONResponse({"detail": "Use application/json"}, status_code=415)
        else:
            response = await call_next(request)
    else:
        response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "img-src 'self' data:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )
    return response


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(ASSETS / "index.html")


@app.get("/health/live")
def health():
    return {"status": "alive", "application": "playground", "line_worker": False, "provider_probed": False}


@app.post("/api/ask")
async def ask(payload: Question):
    started = time.perf_counter()
    if payload.mode == "demo":
        status = {"quota": "unavailable", "unverified": "unverified"}.get(payload.scenario, "ok")
        return result(DEMO_ANSWERS[payload.scenario], started, "demo", status,
                      "quota_exhausted" if payload.scenario == "quota" else None)
    return await run_in_threadpool(live_response, payload.question, started)


app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")
