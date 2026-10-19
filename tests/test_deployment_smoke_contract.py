import os
import unittest
from unittest.mock import patch

from scripts.smoke_deployment import check_deployment


class DeploymentSmokeTests(unittest.TestCase):
    def test_smoke_uses_new_inbox_and_never_processes_live_jobs(self):
        with patch.dict(os.environ, {"LINE_INBOX_DB_PATH": "production.sqlite3"}), \
             patch("app.api.health.knowledge_count", return_value=774), \
             patch("app.services.line_inbox.ask_ai") as ask, \
             patch("app.services.line_inbox.send_reply") as reply, \
             patch("app.services.line_inbox.send_push") as push:
            report = check_deployment()
            self.assertTrue(report["passed"])
            self.assertEqual(os.environ["LINE_INBOX_DB_PATH"], "production.sqlite3")
        ask.assert_not_called()
        reply.assert_not_called()
        push.assert_not_called()

    def test_empty_index_fails_deployment_smoke(self):
        with patch("app.api.health.knowledge_count", return_value=0):
            report = check_deployment()
        self.assertFalse(report["passed"])
        self.assertEqual(report["ready_status"], 503)
