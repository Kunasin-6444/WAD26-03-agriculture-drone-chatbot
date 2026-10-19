import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from scripts.storage_snapshot import backup, restore


class StorageSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.chroma, self.inbox = self.root / "chroma", self.root / "inbox.sqlite3"
        self.chroma.mkdir()
        for path in (self.chroma / "chroma.sqlite3", self.inbox):
            with closing(sqlite3.connect(path)) as conn:
                conn.execute("CREATE TABLE fixture(value TEXT)")
                conn.execute("INSERT INTO fixture VALUES ('preserved')")
                conn.commit()
        (self.chroma / "vector.bin").write_bytes(b"vector-segment")
        self.direct = self.root / "direct"
        self.direct.mkdir()
        (self.direct / "page.pdf").write_bytes(b"%PDF-fixture")
        self.snapshot = self.root / "snapshot"

    def save(self):
        return backup(self.chroma, self.inbox, self.direct, self.snapshot, quiesced=True)

    def test_restore_checks_files_and_preserves_database_records(self):
        manifest = self.save()
        restored = self.root / "restored"
        self.assertEqual(restore(self.snapshot, restored), len(manifest["files"]))
        for path in (restored / "chroma_db/chroma.sqlite3", restored / "cache/line_inbox.sqlite3"):
            with closing(sqlite3.connect(path)) as conn:
                self.assertEqual(conn.execute("SELECT value FROM fixture").fetchone()[0], "preserved")
        self.assertEqual((restored / "cache/direct_pdf/page.pdf").read_bytes(), b"%PDF-fixture")

    def test_backup_requires_quiescence_and_does_not_overwrite(self):
        with self.assertRaises(ValueError):
            backup(self.chroma, self.inbox, self.direct, self.snapshot, quiesced=False)
        self.save()
        with self.assertRaises(FileExistsError):
            self.save()
        with self.assertRaises(FileExistsError):
            restore(self.snapshot, self.chroma)

    def test_tampering_fails_before_publishing_restore(self):
        self.save()
        (self.snapshot / "chroma_db/vector.bin").write_bytes(b"tampered")
        destination = self.root / "restored"
        with self.assertRaises(ValueError):
            restore(self.snapshot, destination)
        self.assertFalse(destination.exists())

    def test_manifest_cannot_escape_restore_destination(self):
        self.save()
        manifest_path = self.snapshot / "manifest.json"
        for invalid in ["../escape", "C:/escape", "a\\..\\escape", "/escape"]:
            manifest_path.write_text(json.dumps({"version": 1, "files": {invalid: "fake"}}), encoding="utf-8")
            with self.subTest(path=invalid), self.assertRaises(ValueError):
                restore(self.snapshot, self.root / "restored")

    def test_backup_cannot_recursively_include_itself(self):
        with self.assertRaises(ValueError):
            backup(self.chroma, self.inbox, self.direct, self.chroma / "backup", quiesced=True)
