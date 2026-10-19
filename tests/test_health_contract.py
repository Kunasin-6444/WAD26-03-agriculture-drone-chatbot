import tempfile
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api.health import local_checks
from app.main import app
from app.services.line_inbox import InboxStore


class HealthContractTests(unittest.TestCase):
    def test_empty_index_and_dead_worker_are_not_ready(self):
        inbox = MagicMock(is_running=False)
        with patch("app.api.health.knowledge_count", return_value=0):
            self.assertEqual(local_checks(inbox), {"knowledge_index": False, "inbox": True, "worker": False})

    def test_database_failure_is_not_masked_by_healthy_index(self):
        inbox = MagicMock(is_running=True)
        inbox.store.health_snapshot.side_effect = OSError("private path must not escape")
        with patch("app.api.health.knowledge_count", return_value=774):
            self.assertEqual(local_checks(inbox), {"knowledge_index": True, "inbox": False, "worker": True})

    def test_no_lifespan_is_alive_but_not_ready(self):
        with patch("app.api.health.knowledge_count", side_effect=RuntimeError("secret")):
            client = TestClient(app)
            self.assertEqual(client.get("/health/live").status_code, 200)
            result = client.get("/health/ready")
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("secret", result.text)
        self.assertEqual(result.json()["external_providers"], "not_probed")

    def test_healthy_local_dependencies_are_ready_without_external_calls(self):
        inbox = MagicMock(is_running=True)
        with patch("app.api.health.knowledge_count", return_value=774):
            self.assertTrue(all(local_checks(inbox).values()))

    def test_inbox_health_only_returns_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            store = InboxStore(Path(folder) / "inbox.sqlite3")
            store.add_events([{"event_id": "e1", "reply_token": "private-token", "text": "private-text"}])
            self.assertEqual(store.health_snapshot(), {"pending": 1})

    def test_read_only_inbox_is_not_mistaken_for_healthy_persistence(self):
        with tempfile.TemporaryDirectory() as folder:
            store = InboxStore(Path(folder) / "inbox.sqlite3")
            readonly = sqlite3.connect(store.path.as_uri() + "?mode=ro", uri=True)
            with patch("app.services.line_inbox.sqlite3.connect", return_value=readonly):
                with self.assertRaises(sqlite3.OperationalError):
                    store.health_snapshot()
