"""Reproduce known R3/R7 gaps offline. Exit 1 while a critical gap remains.

No external calls, LINE deliveries, or production index writes. These probes are
not a substitute for live answer evaluation or a complete security audit.
"""
import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import time
from unittest.mock import patch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="cache/eval/CONTRACT_GAP_REPORT.json")
    args = parser.parse_args()
    from app.rag.evidence import Evidence, parse_grounded_result

    findings = []
    table = "หัวฉีด | รอบ (rpm) | ปริมาณ (ml/หัวฉีด)\nพัดส้ม | 1600 | 500\nพัดแดง | 1600 | 1150"
    claim = "หัวฉีดพัดส้มมีปริมาณ 1150 ml ต่อหัวฉีด ที่ 1600 rpm"
    raw = json.dumps({"status": "sufficient", "claims": [{"text": claim,
        "evidence": [{"source_id": "D1", "quote": table}]}], "missing_aspects": [], "is_caat_topic": False})
    result = parse_grounded_result(raw, [Evidence("D1", table, "synthetic-table.pdf", "1")])
    if result.claims:
        findings.append({"id": "R3_TABLE_ROW", "severity": "high", "requirement": "R3",
                         "problem": "A real multi-row quote can support a claim using another row's value.",
                         "synthetic_evidence": table, "incorrect_accepted_claim": claim})

    # Configure isolated development dependencies before importing the web app.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder, patch.dict(os.environ, {
        "LINE_CHANNEL_SECRET": "offline-audit-secret", "LINE_CHANNEL_ACCESS_TOKEN": "offline-audit-token",
        "API_KEY": "offline-audit-key", "GOOGLE_API_KEY": "offline-audit-key", "TAVILY_API_KEY": "",
        "CHROMA_PATH": folder, "WARMUP_ON_STARTUP": "false", "PDF_RETRIEVAL_MODE": "text",
        "LINE_INBOX_DB_PATH": str(Path(folder) / "inbox.sqlite3"),
    }):
        from fastapi.testclient import TestClient
        from app.config import LINE_CHANNEL_SECRET
        from app.main import app
        from app.services.line_service import DELIVERED, SendResult
        payload = {"destination": "Uoffline", "events": [{"type": "message",
            "message": {"type": "text", "id": "1", "text": "คำถามทดสอบ", "quoteToken": "q"},
            "timestamp": 1727150000000, "source": {"type": "user", "userId": "Uoffline"},
            "replyToken": "offline-reply-token", "webhookEventId": "audit-same-event",
            "deliveryContext": {"isRedelivery": False}, "mode": "active"}]}
        body = json.dumps(payload, ensure_ascii=False).encode()
        signature = base64.b64encode(hmac.new(LINE_CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()).decode()
        with patch("app.services.line_inbox.ask_ai", return_value="offline audit answer") as ask, \
             patch("app.services.line_inbox.send_reply", return_value=SendResult(DELIVERED)) as reply, \
             patch("app.services.line_inbox.send_push") as push, patch("app.services.line_inbox.show_loading_animation"):
            with TestClient(app) as client:
                statuses = [client.post("/webhook", content=body, headers={"x-line-signature": signature}).status_code for _ in range(2)]
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    state = app.state.line_inbox.store.get("audit-same-event")
                    if state and state["state"] == "done":
                        break
                    time.sleep(0.01)
                stored_events = app.state.line_inbox.store.count()
        if statuses != [200, 200] or ask.call_count != 1 or reply.call_count != 1 or push.call_count or stored_events != 1:
            findings.append({"id": "R7_DUPLICATE_EVENT", "severity": "high", "requirement": "R7/operational reliability",
                             "problem": "Duplicate event contract or durable worker execution failed.",
                             "http_statuses": statuses, "pipeline_calls": ask.call_count, "reply_calls": reply.call_count,
                             "push_calls": push.call_count, "stored_events": stored_events})
    report = {"generated_at": datetime.now(timezone(timedelta(hours=7))).isoformat(), "mode": "offline",
              "findings": findings, "critical_gap_count": len(findings),
              "note": "Synthetic failure probes. They measure reproducible gaps, not the rate of wrong live answers."}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"critical_gap_count": len(findings), "report": str(output)}))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
