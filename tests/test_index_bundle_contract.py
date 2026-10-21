"""The folder uploaded to the private index dataset holds the index only and never a secret."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build_index_bundle


class IndexBundle(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="index-bundle-"))
        self.repo = self.tmp / "repo"
        for name, text in {
            "chroma_db/chroma.sqlite3": "db", "chroma_db/segment/data_level0.bin": "vectors",
            "chroma_db/embedding_cache/a.json": "{}", "chroma_db/__pycache__/x.pyc": "", "data/UAV06.pdf": "pdf",
            ".env": "SECRET=1\n",
        }.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        patcher = patch.object(build_index_bundle, "ROOT", self.repo)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_only_the_index_goes_in(self):
        out = self.tmp / "index"
        files = {path.relative_to(out).as_posix() for path in build_index_bundle.build(out)}
        self.assertEqual(files, {"chroma.sqlite3", "segment/data_level0.bin"})

    def test_a_secret_file_in_the_index_stops_the_build(self):
        (self.repo / "chroma_db" / ".env.local").write_text("SECRET=1\n", encoding="utf-8")
        with patch.object(build_index_bundle, "NEVER", ()), self.assertRaises(SystemExit):
            build_index_bundle.build(self.tmp / "index")
        self.assertFalse((self.tmp / "index").exists())

    def test_the_folder_must_be_outside_the_repository(self):
        with self.assertRaises(SystemExit):
            build_index_bundle.build(self.repo / "index")
