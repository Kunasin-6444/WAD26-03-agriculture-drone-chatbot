"""The Space downloads the private index only when it is missing, and refuses to start without one."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import fetch_index


class FetchIndex(unittest.TestCase):
    def setUp(self):
        self.target = Path(tempfile.mkdtemp(prefix="hf-index-")) / "chroma_db"

    def test_an_index_already_present_is_not_downloaded(self):
        self.target.mkdir(parents=True)
        (self.target / "chroma.sqlite3").write_text("db", encoding="utf-8")
        with patch("huggingface_hub.snapshot_download") as download:
            fetch_index.fetch(self.target, "owner/index", "token")
        download.assert_not_called()

    def test_a_missing_index_is_downloaded_from_the_private_dataset(self):
        def download(**kwargs):
            Path(kwargs["local_dir"]).mkdir(parents=True, exist_ok=True)
            (Path(kwargs["local_dir"]) / "chroma.sqlite3").write_text("db", encoding="utf-8")
        with patch("huggingface_hub.snapshot_download", side_effect=download) as mocked:
            fetch_index.fetch(self.target, "owner/index", "token")
        self.assertEqual(mocked.call_args.kwargs, {"repo_id": "owner/index", "repo_type": "dataset",
                                                   "local_dir": str(self.target), "token": "token"})

    def test_no_index_and_no_dataset_stops_the_start(self):
        with self.assertRaises(SystemExit):
            fetch_index.fetch(self.target, None, None)

    def test_a_dataset_without_the_index_file_stops_the_start(self):
        with patch("huggingface_hub.snapshot_download"), self.assertRaises(SystemExit):
            fetch_index.fetch(self.target, "owner/index", "token")
