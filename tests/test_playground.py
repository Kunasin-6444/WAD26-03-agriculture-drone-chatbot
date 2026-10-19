"""Bounded offline checks for the local manual playground; no real providers."""
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.playground import app, live_response

ORIGIN = "http://127.0.0.1:8080"


def client():
    return TestClient(app, base_url=ORIGIN, headers={"origin": ORIGIN})


def test_fresh_startup_and_all_demo_scenarios_do_not_load_rag_or_line():
    # A fresh interpreter catches import-time side effects masked by other tests.
    code = '''
import sys
from fastapi.testclient import TestClient
from app.playground import app
with TestClient(app, base_url="http://127.0.0.1:8080", headers={"origin": "http://127.0.0.1:8080"}) as client:
    assert client.get("/").status_code == 200
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/assets/style.css").status_code == 200
    assert client.get("/health/live").json()["line_worker"] is False
    for scenario in ["mixed", "kb", "unverified", "quota"]:
        data = client.post("/api/ask", json={"question": "example", "scenario": scenario}).json()
        assert data["mode"] == "demo" and data["notice"] and data["elapsed_ms"] >= 0
assert not any(name.startswith(("app.rag", "app.services", "app.config", "chromadb", "openai", "tavily")) for name in sys.modules)
'''
    checked = subprocess.run([sys.executable, "-X", "utf8", "-c", code], capture_output=True, text=True, timeout=20)
    assert checked.returncode == 0, checked.stderr


def test_demo_keeps_exact_url_and_marks_sources_as_simulated():
    with client() as browser, patch("app.playground.ask_live", side_effect=AssertionError("No live calls")):
        data = browser.post("/api/ask", json={"question": "คำถาม"}).json()
    assert data["mode"] == "demo"
    assert "เอกสารจำลอง.pdf, หน้า 12" in data["answer"]
    assert "https://example.org/articles/drone-guide?lang=th#safety" in data["answer"]
    assert "ไม่ได้เรียก AI" in data["notice"]


def test_live_forwards_one_question_and_preserves_the_complete_answer():
    answer = "คำตอบ [1]\n\nแหล่งอ้างอิง:\n[1] https://example.org/articles/a?lang=th#limits"
    with client() as browser, patch("app.playground.ask_live", return_value=(answer, False)) as live:
        response = browser.post("/api/ask", json={"question": "  คำถามจริง  ", "mode": "live"})
    assert response.status_code == 200
    assert response.json()["answer"] == answer
    assert response.json()["mode"] == "live"
    assert response.json()["notice"] == ""
    live.assert_called_once_with("คำถามจริง")


def test_invalid_or_cross_origin_requests_never_reach_a_provider():
    with client() as browser, patch("app.playground.ask_live") as live:
        for question in ["", "   ", "x" * 2001]:
            assert browser.post("/api/ask", json={"question": question, "mode": "live"}).status_code == 422
        assert browser.post("/api/ask", json={"question": "q", "mode": "automatic"}).status_code == 422
        for origin in ["https://untrusted.example", "null", ""]:
            assert browser.post("/api/ask", headers={"origin": origin}, json={"question": "q", "mode": "live"}).status_code == 403
        assert browser.post("/api/ask", headers={"sec-fetch-site": "cross-site"}, json={"question": "q"}).status_code == 403
        assert browser.post("/api/ask", content="question=q", headers={"content-type": "text/plain"}).status_code == 415
        assert browser.get("/", headers={"host": "untrusted.example"}).status_code == 400
        live.assert_not_called()


def test_provider_errors_are_actionable_do_not_leak_secrets_and_do_not_retry():
    class QuotaError(Exception):
        status_code = 429

    class AuthError(Exception):
        status_code = 401

    cases = [
        (QuotaError("private-api-key"), "quota_exhausted"),
        (AuthError("private-api-key"), "provider_auth"),
        (TimeoutError("private-api-key"), "timeout"),
        (RuntimeError("LLM_API_KEY is not set."), "configuration"),
        (ValueError("private-api-key"), "request_failed"),
    ]
    with client() as browser:
        for error, expected in cases:
            with patch("app.playground.ask_live", side_effect=error) as live:
                response = browser.post("/api/ask", json={"question": "q", "mode": "live"})
            assert response.status_code == 503
            assert response.json()["error_code"] == expected
            assert "private-api-key" not in response.text
            live.assert_called_once()


def test_degraded_pipeline_answer_is_service_failure_not_missing_evidence():
    with client() as browser, patch("app.playground.ask_live", return_value=("degraded", True)):
        response = browser.post("/api/ask", json={"question": "q", "mode": "live"})
    assert response.status_code == 503
    assert response.json()["error_code"] == "provider_unavailable"
    assert "ไม่ได้หมายความว่าเอกสารไม่มีข้อมูล" in response.json()["answer"]


def test_parallel_live_question_is_rejected_without_an_extra_provider_call():
    from time import perf_counter

    entered = threading.Event()
    release = threading.Event()

    def blocked(_):
        entered.set()
        assert release.wait(5)
        return "answer", False

    with patch("app.playground.ask_live", side_effect=blocked) as live, ThreadPoolExecutor(max_workers=1) as workers:
        first = workers.submit(live_response, "first", perf_counter())
        try:
            assert entered.wait(5)
            assert live_response("second", perf_counter()).status_code == 409
        finally:
            release.set()
        assert first.result(timeout=5).status_code == 200
        live.assert_called_once_with("first")
