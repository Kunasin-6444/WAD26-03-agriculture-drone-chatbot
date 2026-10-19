"""Offline by default: fake credentials, isolated Chroma, and no network."""
import atexit
import os
import shutil
import socket
import tempfile
from unittest.mock import patch

LIVE = os.getenv("RUN_LIVE_TESTS") == "1"
if not LIVE:
    os.environ["PDF_RETRIEVAL_MODE"] = "text"
    for name in ["LINE_CHANNEL_SECRET", "LINE_CHANNEL_ACCESS_TOKEN", "API_KEY", "GOOGLE_API_KEY", "TAVILY_API_KEY", "LLM_API_KEY", "LLM_SECONDARY_API_KEY"]:
        os.environ[name] = "offline-test-credential"
    os.environ["LLM_SECONDARY_BASE_URL"] = ""
    os.environ["LLM_SECONDARY_MODELS"] = ""
    os.environ["LLM_SECONDARY_STRUCTURED_OUTPUT"] = "false"
    _test_db = tempfile.mkdtemp(prefix="drone-tests-")
    os.environ["CHROMA_PATH"] = _test_db
    atexit.register(shutil.rmtree, _test_db, ignore_errors=True)
    # Windows asyncio builds its internal socket pair on loopback.
    _original_connect = socket.socket.connect
    def _guard_connect(sock, address):
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return _original_connect(sock, address)
        raise AssertionError("Offline tests must not access external networks")
    _network_guard = patch.object(socket.socket, "connect", _guard_connect)
    _network_guard.start()
