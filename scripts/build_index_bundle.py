"""Copy the search index into a folder for upload to the private Hugging Face dataset.

The deployed service (Render, see render.yaml) downloads the index from that dataset at start
(scripts/fetch_index.py) because the index holds the document text and is not in git. The embedding
cache is left out (only ingestion uses it) and the build refuses if any .env file would go along.

    .venv/Scripts/python.exe -m scripts.build_index_bundle      # -> ../agriculture-drone-chatbot-hf-index
    .venv/Scripts/hf.exe upload Kunasin/agri-drone-index ../agriculture-drone-chatbot-hf-index . --repo-type dataset
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT.parent / f"{ROOT.name}-hf-index"
INDEX = "chroma_db"
# Not needed at runtime: document embeddings are cached only while ingesting.
SKIP_DIRS = {"__pycache__", ".pytest_cache", "embedding_cache"}
NEVER = (".env",)


def _ignore(directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in SKIP_DIRS or name.startswith(NEVER) or name.endswith((".pyc", ".log"))}


def build(out: Path) -> list[Path]:
    out = out.resolve()
    if out == ROOT or ROOT in out.parents:
        raise SystemExit(f"--out must be outside the repository: {out}")
    source = ROOT / INDEX
    if not (source / "chroma.sqlite3").exists():
        raise SystemExit(f"no index at {source}")
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(source, out, ignore=_ignore)
    files = sorted(path for path in out.rglob("*") if path.is_file())
    leaked = [path for path in files if path.name.startswith(".env")]
    if leaked:
        shutil.rmtree(out)
        raise SystemExit(f"refusing to build: secret file found {leaked}")
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="folder to create (replaced if it exists)")
    args = parser.parse_args()
    files = build(args.out)
    size = sum(path.stat().st_size for path in files) / 1_000_000
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"Index folder: {args.out.resolve()}  ({len(files)} files, {size:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
