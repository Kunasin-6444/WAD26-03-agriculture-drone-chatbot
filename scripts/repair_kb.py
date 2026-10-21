"""
Repair the existing KB in place (no PDF re-reading, no vision calls).

    python -m scripts.repair_kb            # dry run: report only
    python -m scripts.repair_kb --apply    # write changes (re-embeds changed chunks)

1. Delete native-PDF chunks that carry no information beyond the vision chunks of the
   same page: pure page-number noise, or chunks whose letters/digits are >= 85%
   covered by the page's vision chunks and whose numbers all appear there too.
   Native text layers of the source PDFs have broken Thai (see app/ingestion/thai_text.py);
   the vision version of the same content is clean.
2. Repair SARA AM damage in the native chunks that are kept (they hold content vision
   did not capture, e.g. body text next to a picture) and re-embed only those.

All embeddings are computed before anything is written, and a rollback log with the
original text of every deleted/changed chunk is saved under cache/.
"""
from __future__ import annotations

import collections
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from app.ingestion.dedupe import assess_native
from app.ingestion.thai_text import repair_sara_am


def _origin(chunk_id: str) -> str:
    match = re.search(r"-p\d+-([a-z]+)-([a-z_]+)-\d+-[0-9a-f]{6}-chunk", chunk_id)
    return match.group(2) if match else "?"


def plan(ids: list[str], documents: list[str], metadatas: list[dict]) -> dict:
    pages = collections.defaultdict(list)
    for chunk_id, text, meta in zip(ids, documents, metadatas):
        pages[(meta["source_file"], int(meta["page_number"]))].append((chunk_id, text, _origin(chunk_id)))

    delete: list[dict] = []
    keep_native: list[dict] = []
    for (source_file, page), items in pages.items():
        vision_text = " ".join(t for _, t, o in items if o in ("vision", "vision_summary"))
        for chunk_id, text, origin in items:
            if origin not in ("native", "native_table"):
                continue
            record = {"id": chunk_id, "file": source_file, "page": page, "origin": origin, "text": text}
            verdict = assess_native(text, page, vision_text)
            if verdict.drop:
                delete.append({**record, "reason": verdict.reason})
            else:
                keep_native.append({**record, "coverage": verdict.coverage, "missing_numbers": list(verdict.missing_numbers)})
    return {"delete": delete, "keep_native": keep_native}


def main() -> int:
    apply = "--apply" in sys.argv
    from app.rag import vector_store

    collection = vector_store.collection
    data = collection.get(include=["documents", "metadatas"])
    result = plan(data["ids"], data["documents"], data["metadatas"])
    delete, keep_native = result["delete"], result["keep_native"]
    changed = [r for r in keep_native if repair_sara_am(r["text"]) != r["text"]]

    print(f"chroma: {vector_store.CHROMA_PATH}  chunks: {len(data['ids'])}")
    print(f"native chunks: {len(delete) + len(keep_native)}  -> delete {len(delete)}, keep {len(keep_native)}")
    print(f"kept native chunks needing SARA AM repair (re-embed): {len(changed)}")
    for r in keep_native:
        if r["missing_numbers"]:
            print(f"  KEPT (numbers not in vision {r['missing_numbers']}): {r['file'][:5]} p{r['page']} cov={r['coverage']}")
    if not apply:
        print("\ndry run only; pass --apply to write")
        return 0

    from app.rag.embedding import embed_text

    new_docs = {r["id"]: repair_sara_am(r["text"]) for r in changed}
    embeddings = {}
    for n, (chunk_id, text) in enumerate(new_docs.items(), 1):
        embeddings[chunk_id] = embed_text(text)
        if n % 10 == 0 or n == len(new_docs):
            print(f"  embedded {n}/{len(new_docs)}", flush=True)
        time.sleep(0.2)

    log_dir = Path("cache")
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"kb_repair_{datetime.now():%Y%m%d_%H%M%S}.json"
    log_path.write_text(json.dumps({
        "deleted": delete,
        "changed": [{"id": r["id"], "before": r["text"], "after": new_docs[r["id"]]} for r in changed],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    if delete:
        collection.delete(ids=[r["id"] for r in delete])
    if new_docs:
        collection.update(ids=list(new_docs), documents=list(new_docs.values()),
                          embeddings=[embeddings[i] for i in new_docs])
    print(f"applied: deleted {len(delete)}, updated {len(new_docs)}; rollback log: {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
