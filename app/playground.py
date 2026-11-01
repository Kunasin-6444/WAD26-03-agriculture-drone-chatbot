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
    "web": (
        "• นี่คือตัวอย่างคำตอบจากเว็บ พร้อมลิงก์หน้าที่ใช้ [1]\n\n"
        "แหล่งอ้างอิง:\n[1] หน้าเว็บตัวอย่าง (ข้อมูลจำลอง)\n"
        "https://example.org/articles/drone-guide?lang=th#safety"
    ),
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
    scenario: Literal["mixed", "kb", "web", "unverified", "quota"] = "mixed"
    source: Literal["auto", "kb", "web"] = "auto"

    @field_validator("question")
    @classmethod
    def nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Please enter a question")
        return value


def ask_live(question: str, source: str = "auto") -> tuple[str, bool]:
    # Lazy import is deliberate: loading a page or trying a demo must not load
    # credentials, open Chroma, start LINE workers or instantiate providers.
    if app.state.pipeline == "support":
        from app.rag.support_pipeline import run_support_pipeline
        options = {"json_mode": True} if getattr(app.state, "support_json_mode", False) else {}
        response = run_support_pipeline(question, source=source, **options)
        if response.error_code:
            return ERROR_MESSAGES.get(response.error_code, ERROR_MESSAGES["provider_unavailable"]), True
        return response.answer, False
    from app.services.ai_service import ask_ai
    # The baseline currently processes each question independently, as on LINE.
    answer = ask_ai(question, user_id="playground")
    from app.services.rich_menu_service import MENU_ANSWER, menu_as_text
    if answer == MENU_ANSWER:
        answer = menu_as_text()
    return answer, bool(service_error_code(answer))


def result(answer: str, started: float, mode: str, status: str = "ok", code: str | None = None) -> dict:
    return {
        "answer": answer,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        "mode": mode,
        "pipeline": app.state.pipeline,
        "status": status,
        "error_code": code,
        "notice": DEMO_NOTICE if mode == "demo" else (
            "โหมดทดลอง · ใช้เอกสารหรือเว็บแยกกัน · ยังไม่ได้ยืนยันคุณภาพคำตอบจริง"
            if app.state.pipeline == "support" else
            "ระบบค้นรุ่นทดลอง · ยังไม่ได้ยืนยันคุณภาพคำตอบจริง"
            if getattr(app.state, "retriever_experimental", False) else ""),
    }


def live_response(question: str, started: float, source: str = "auto") -> JSONResponse:
    # Held inside the worker thread until the provider actually finishes, even
    # when a browser disconnects. No queued or automatic follow-up questions.
    if not _live_lock.acquire(blocking=False):
        return JSONResponse(result("มีคำถามจริงกำลังประมวลผลอยู่ กรุณารอให้จบก่อนส่งใหม่ครับ",
                                   started, "live", "error", "busy"), status_code=409)
    try:
        answer, unavailable = (ask_live(question, source=source) if app.state.pipeline == "support"
                               else ask_live(question))
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
app.state.pipeline = "baseline"
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
    return {"status": "alive", "application": "playground", "line_worker": False,
            "provider_probed": False, "pipeline": app.state.pipeline}


@app.post("/api/ask")
async def ask(payload: Question):
    started = time.perf_counter()
    if payload.mode == "demo":
        status = {"quota": "unavailable", "unverified": "unverified"}.get(payload.scenario, "ok")
        scenario = payload.scenario
        if app.state.pipeline == "support" and scenario == "mixed":
            scenario = "web" if payload.source == "web" else "kb"
        return result(DEMO_ANSWERS[scenario], started, "demo", status,
                      "quota_exhausted" if payload.scenario == "quota" else None)
    return await run_in_threadpool(live_response, payload.question, started, payload.source)


app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")
