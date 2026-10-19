"""Put chosen pages of one source file back to the chunks a backup index holds.

    python -m scripts.restore_pages --live chroma_db --backup cache/backup_xxx \
        --source "UAV06 โดรนฉีดพ่นเพื่อการเกษตร.pdf" --page 18 [--page 5] [--dry-run]

Safe order: the backup chunks are written back first, only then the live chunks the backup does not
have are deleted. Touches the named pages of the one source file; nothing else.
"""
import argparse
import sys

import chromadb

COLLECTION = "drone_knowledge"


def restore_page(live, backup, source: str, page: int, dry_run: bool) -> bool:
    where = {"$and": [{"source_file": source}, {"page_number": str(page)}]}
    old = backup.get(where=where, include=["documents", "metadatas", "embeddings"])
    current = live.get(where=where, include=[])
    if not old["ids"]:
        print(f"p{page}: backup has no chunks; left unchanged")
        return False
    extra = sorted(set(current["ids"]) - set(old["ids"]))
    print(f"p{page}: live {len(current['ids'])} chunks | backup {len(old['ids'])} | to delete {len(extra)}")
    if dry_run:
        return True
    live.upsert(ids=old["ids"], documents=old["documents"], metadatas=old["metadatas"], embeddings=old["embeddings"])
    if extra:
        live.delete(ids=extra)
    after = live.get(where=where, include=[])
    print(f"p{page}: live now {len(after['ids'])} chunks (expected {len(old['ids'])})")
    return len(after["ids"]) == len(old["ids"])


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", required=True)
    parser.add_argument("--backup", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--page", type=int, action="append", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    live = chromadb.PersistentClient(path=args.live).get_collection(COLLECTION)
    backup = chromadb.PersistentClient(path=args.backup).get_collection(COLLECTION)
    ok = [restore_page(live, backup, args.source, page, args.dry_run) for page in args.page]
    return 0 if all(ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
