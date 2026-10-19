import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool

from app.api.webhook import router as webhook_router
from app.api.health import router as health_router
from app.rag.rag_service import warm_up_retrieval
from app.services.line_inbox import build_inbox_from_env

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Without this the first LINE message after a deploy pays ~4.5s of lazy imports.
    # The server only accepts traffic once startup finishes, so users never see that cost.
    if os.getenv("WARMUP_ON_STARTUP", "true").strip().lower() not in {"0", "false", "no", "off"}:
        try:
            await run_in_threadpool(warm_up_retrieval)
        except Exception as exc:  # warming is an optimisation, never a reason not to start
            logger.warning("Startup warm-up failed (%s)", type(exc).__name__)
    inbox = build_inbox_from_env()
    await inbox.start()
    app.state.line_inbox = inbox
    try:
        yield
    finally:
        await inbox.stop()
        app.state.line_inbox = None


app = FastAPI(lifespan=lifespan)


@app.get("/")
def root():
    return {
        "message": "Agriculture Drone Chatbot API is running!"
    }


# Support both /webhook and /api/webhook for LINE Developers console
app.include_router(webhook_router)
app.include_router(webhook_router, prefix="/api")
app.include_router(health_router)
