"""Boot the configured app and probe health without sending LINE/API messages.

A fresh temporary inbox is always used, so this cannot consume production jobs.
The configured knowledge index is read; no ingestion or model call is performed.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path


def check_deployment() -> dict:
    previous = os.environ.get("LINE_INBOX_DB_PATH")
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="deployment-inbox-") as folder:
            os.environ["LINE_INBOX_DB_PATH"] = str(Path(folder) / "inbox.sqlite3")
            from fastapi.testclient import TestClient
            from app.main import app
            with TestClient(app) as client:
                live = client.get("/health/live")
                ready = client.get("/health/ready")
                result = {"passed": live.status_code == ready.status_code == 200,
                          "live_status": live.status_code, "ready_status": ready.status_code,
                          "readiness": ready.json(), "isolated_inbox": True,
                          "external_calls": False, "seconds": round(time.monotonic() - started, 3)}
            return result
    finally:
        if previous is None:
            os.environ.pop("LINE_INBOX_DB_PATH", None)
        else:
            os.environ["LINE_INBOX_DB_PATH"] = previous


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = check_deployment()
    content = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    print(content)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
