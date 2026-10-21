"""Fetch the search index from a private Hugging Face dataset before the service starts.

The Space must be public for LINE to reach its webhook, so it does not carry the index (the document
text). The index lives in a private dataset (HF_INDEX_REPO) and is downloaded with HF_TOKEN. Nothing is
downloaded when the index is already there, e.g. mounted for a local container test. Without an index
and without HF_INDEX_REPO the start fails loudly instead of answering "not found" to every question.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

INDEX_FILE = "chroma.sqlite3"


def fetch(target: Path, repo: str | None, token: str | None) -> str:
    if (target / INDEX_FILE).exists():
        return f"index present at {target}"
    if not repo:
        raise SystemExit(f"No index at {target}: set HF_INDEX_REPO (private dataset) and HF_TOKEN, or mount chroma_db")
    from huggingface_hub import snapshot_download
    snapshot_download(repo_id=repo, repo_type="dataset", local_dir=str(target), token=token or None)
    if not (target / INDEX_FILE).exists():
        raise SystemExit(f"The dataset {repo} has no {INDEX_FILE}")
    return f"index downloaded from {repo}"


def main() -> int:
    target = Path(os.getenv("CHROMA_PATH") or Path(__file__).resolve().parents[1] / "chroma_db")
    print(fetch(target, os.getenv("HF_INDEX_REPO"), os.getenv("HF_TOKEN")), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
