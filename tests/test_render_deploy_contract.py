"""The Render deployment stays free, keeps secrets out of the repository and ships no slides."""
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SECRETS = {"HF_TOKEN", "LINE_CHANNEL_SECRET", "LINE_CHANNEL_ACCESS_TOKEN", "API_KEY", "GOOGLE_API_KEY",
           "TAVILY_API_KEY", "LLM_SECONDARY_BASE_URL", "LLM_SECONDARY_API_KEY"}


class RenderDeployment(unittest.TestCase):
    def setUp(self):
        self.service = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))["services"][0]
        self.dockerfile = (ROOT / self.service["dockerfilePath"]).read_text(encoding="utf-8")

    def test_the_service_is_a_free_docker_web_service_near_thailand(self):
        self.assertEqual((self.service["type"], self.service["runtime"], self.service["plan"]), ("web", "docker", "free"))
        self.assertEqual(self.service["region"], "singapore")
        self.assertEqual(self.service["healthCheckPath"], "/health/ready")

    def test_deploys_wait_for_the_button(self):
        self.assertEqual(self.service["autoDeployTrigger"], "off")   # a bare off would be YAML false

    def test_secrets_are_asked_for_and_never_written(self):
        variables = {item["key"]: item for item in self.service["envVars"]}
        self.assertTrue(SECRETS <= set(variables))
        for key in SECRETS:
            self.assertEqual(variables[key], {"key": key, "sync": False})
        for key, item in variables.items():
            if key not in SECRETS:
                self.assertIsInstance(item["value"], str, key)

    def test_the_image_has_no_slides_and_listens_on_render_port(self):
        copies = [line for line in self.dockerfile.splitlines() if line.startswith("COPY")]
        self.assertFalse([line for line in copies if " data " in line + " " or "chroma_db" in line or "tests" in line])
        self.assertIn("data/rich_menu_answers", self.dockerfile)
        self.assertIn("python -m scripts.fetch_index &&", self.dockerfile)
        self.assertIn("--port ${PORT:-10000}", self.dockerfile)
        self.assertIn("--uid 1000", self.dockerfile)
