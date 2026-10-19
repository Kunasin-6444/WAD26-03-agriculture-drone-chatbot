"""Offline storage backup/restore with checksums and no overwrite.

Stop the app and all ingestion processes before backup. A collection's SQLite
file and vector segments must represent the same quiescent point in time.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _copy_verified(source: Path, destination: Path) -> str:
    before = source.stat()
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError("Source changed during backup; stop app/ingestion first")
    checksum = digest(destination)
    if checksum != digest(source):
        raise RuntimeError("Source changed while checksumming")
    return checksum


def backup(chroma: Path, inbox: Path, direct_cache: Path, output: Path, *, quiesced: bool) -> dict:
    if not quiesced:
        raise ValueError("Stop app/ingestion and pass --quiesced before backup")
    if output.exists():
        raise FileExistsError("Backup destination already exists")
    if not (chroma / "chroma.sqlite3").is_file() or not inbox.is_file():
        raise ValueError("Both Chroma and LINE inbox must exist")
    output.parent.mkdir(parents=True, exist_ok=True)
    sources = {"chroma_db": chroma, "cache/direct_pdf": direct_cache}
    for source in sources.values():
        if output.resolve().is_relative_to(source.resolve()):
            raise ValueError("Backup destination must be outside source directories")
    with tempfile.TemporaryDirectory(prefix="snapshot-", dir=output.parent) as folder:
        staging = Path(folder) / "payload"
        staging.mkdir()
        hashes = {}
        for label, source in sources.items():
            if not source.exists():
                continue
            for path in sorted(source.rglob("*")):
                if path.is_symlink():
                    raise ValueError("Symlinks are not supported in storage snapshots")
                if path.is_file():
                    relative = (Path(label) / path.relative_to(source)).as_posix()
                    hashes[relative] = _copy_verified(path, staging / relative)
        # Keep WAL/SHM companions if a cleanly stopped process left them behind.
        for suffix in ("", "-wal", "-shm"):
            source = Path(str(inbox) + suffix)
            if source.exists():
                relative = "cache/line_inbox.sqlite3" + suffix
                hashes[relative] = _copy_verified(source, staging / relative)
        manifest = {"version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
                    "quiesced": True, "files": hashes,
                    "note": "No credentials. Inbox may contain pending user data; restrict backup access."}
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        staging.replace(output)
    return manifest


def restore(snapshot: Path, destination: Path) -> int:
    if destination.exists():
        raise FileExistsError("Restore destination must be new; never overwrite an existing deployment")
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != 1 or not manifest.get("files"):
        raise ValueError("Invalid snapshot manifest")
    files = []
    for name, checksum in manifest["files"].items():
        relative = Path(name)
        if (relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name
                or not (snapshot / relative).resolve().is_relative_to(snapshot.resolve())):
            raise ValueError("Invalid snapshot path")
        source = snapshot / relative
        if source.is_symlink() or digest(source) != checksum:
            raise ValueError("Snapshot checksum verification failed")
        files.append((relative, source))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="restore-", dir=destination.parent) as folder:
        staging = Path(folder) / "payload"
        staging.mkdir()
        for relative, source in files:
            _copy_verified(source, staging / relative)
        staging.replace(destination)
    return len(files)


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    save = sub.add_parser("backup")
    save.add_argument("--chroma", type=Path, default=Path(os.getenv("CHROMA_PATH", "chroma_db")))
    save.add_argument("--inbox", type=Path, default=Path(os.getenv("LINE_INBOX_DB_PATH", "cache/line_inbox.sqlite3")))
    save.add_argument("--direct-cache", type=Path, default=Path("cache/direct_pdf"))
    save.add_argument("--output", type=Path, required=True)
    save.add_argument("--quiesced", action="store_true")
    recover = sub.add_parser("restore")
    recover.add_argument("--snapshot", type=Path, required=True)
    recover.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "backup":
        result = backup(args.chroma, args.inbox, args.direct_cache, args.output, quiesced=args.quiesced)
        print(f"Backup verified: {len(result['files'])} files")
    else:
        print(f"Restore verified: {restore(args.snapshot, args.destination)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
