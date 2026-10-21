"""The public Space holds only the app, the private index folder only the index, and neither holds a secret."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build_hf_space


class HuggingFaceSpaceBundle(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hf-bundle-"))
        self.repo = self.tmp / "repo"
        for name, text in {
            "deploy/huggingface/Dockerfile": "FROM python\n", "deploy/huggingface/README.md": "---\nsdk: docker\n---\n",
            "requirements.txt": "fastapi\n", "constraints.txt": "", "app/main.py": "app = 1\n", "app/.env": "SECRET=1\n",
            "app/rag/__pycache__/x.pyc": "", "data/rich_menu_answers/1.txt": "คู่มือ\n", "data/UAV06.pdf": "pdf",
            "chroma_db/chroma.sqlite3": "db", "chroma_db/embedding_cache/a.json": "{}", "tests/test_x.py": "",
            ".env": "SECRET=1\n", "docs/README.md": "", "scripts/fetch_index.py": "", "scripts/ingest_all_data.py": "",
        }.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        patcher = patch.object(build_hf_space, "ROOT", self.repo)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_only_runtime_files_go_in(self):
        out = self.tmp / "space"
        files = {path.relative_to(out).as_posix() for path in build_hf_space.build(out)}
        self.assertEqual(files, {"Dockerfile", "README.md", "requirements.txt", "constraints.txt", "app/main.py",
                                 "data/rich_menu_answers/1.txt", "scripts/fetch_index.py"})

    def test_the_index_folder_holds_only_the_index(self):
        out = self.tmp / "index"
        files = {path.relative_to(out).as_posix() for path in build_hf_space.build(out, build_hf_space.INDEX)}
        self.assertEqual(files, {"chroma.sqlite3"})

    def test_the_folder_must_be_outside_the_repository(self):
        with self.assertRaises(SystemExit):
            build_hf_space.build(self.repo / "space")

    def test_the_real_space_settings_match_what_spaces_need(self):
        root = Path(build_hf_space.__file__).resolve().parents[1] / "deploy" / "huggingface"
        readme, dockerfile = (root / "README.md").read_text(encoding="utf-8"), (root / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("sdk: docker", readme)
        self.assertIn("app_port: 7860", readme)
        self.assertIn("--uid 1000", dockerfile)
        self.assertIn("--port 7860", dockerfile)
        self.assertIn("python -m scripts.fetch_index &&", dockerfile)
        self.assertNotIn("COPY --chown=user:user chroma_db", dockerfile)
