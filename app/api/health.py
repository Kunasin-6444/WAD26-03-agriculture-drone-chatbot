"""Local readiness is separate from liveness and never spends provider quota."""
from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/health", tags=["health"])


def knowledge_count() -> int:
    from app.rag.direct_pdf import enabled, get_collection
    if enabled():
        return get_collection().count()
    from app.rag.vector_store import collection
    return collection.count()


def local_checks(inbox) -> dict[str, bool]:
    checks = {"knowledge_index": False, "inbox": False, "worker": bool(inbox and inbox.is_running)}
    try:
        checks["knowledge_index"] = knowledge_count() > 0
    except Exception:
        pass
    if inbox:
        try:
            inbox.store.health_snapshot()
            checks["inbox"] = True
        except Exception:
            pass
    return checks


@router.get("/live")
def live():
    return {"status": "alive"}


@router.get("/ready")
async def ready(request: Request):
    checks = await run_in_threadpool(local_checks, getattr(request.app.state, "line_inbox", None))
    healthy = all(checks.values())
    return JSONResponse({"status": "ready" if healthy else "not_ready", "checks": checks,
                         "external_providers": "not_probed"}, status_code=200 if healthy else 503)
