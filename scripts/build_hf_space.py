"""Assemble the folders uploaded to Hugging Face: a public Docker Space and a private index dataset.

The Space must be public for LINE to reach its webhook, so it holds only the app, the rich menu guides
and the start script. The index (document text) goes to a private dataset that the Space downloads at
start (scripts/fetch_index.py). Source PDFs, tests, docs, caches and every .env stay out of both.

    .venv/Scripts/python.exe -m scripts.build_hf_space
        -> ../agriculture-drone-chatbot-hf-space   (hf upload <owner>/<space> <folder> . --repo-type space)
        -> ../agriculture-drone-chatbot-hf-index   (hf upload <owner>/<dataset> <folder> . --repo-type dataset)
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT.parent / f"{ROOT.name}-hf-space"
DEFAULT_INDEX_OUT = ROOT.parent / f"{ROOT.name}-hf-index"
# (source relative to the repo, destination relative to the Space)
INCLUDE = [
    ("deploy/huggingface/Dockerfile", "Dockerfile"),
    ("deploy/huggingface/README.md", "README.md"),
    ("requirements.txt", "requirements.txt"),
    ("constraints.txt", "constraints.txt"),
    ("app", "app"),
    ("data/rich_menu_answers", "data/rich_menu_answers"),
    ("scripts/fetch_index.py", "scripts/fetch_index.py"),
]
INDEX = [("chroma_db", ".")]   # the private dataset holds the index files at its root
# Not needed at runtime: document embeddings are cached only while ingesting.
SKIP_DIRS = {"__pycache__", ".pytest_cache", "embedding_cache"}
NEVER = (".env",)


def _ignore(directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in SKIP_DIRS or name.startswith(NEVER) or name.endswith((".pyc", ".log"))}


def build(out: Path, include: list[tuple[str, str]] = INCLUDE) -> list[Path]:
    out = out.resolve()
    if out == ROOT or ROOT in out.parents:
        raise SystemExit(f"--out must be outside the repository: {out}")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for source, destination in include:
        src, dst = ROOT / source, out / destination
        if not src.exists():
            raise SystemExit(f"missing {source}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, ignore=_ignore, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
    files = sorted(path for path in out.rglob("*") if path.is_file())
    leaked = [path for path in files if path.name.startswith(".env")]
    if leaked:
        shutil.rmtree(out)
        raise SystemExit(f"refusing to build: secret file found {leaked}")
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Space folder (replaced if it exists)")
    parser.add_argument("--index-out", type=Path, default=DEFAULT_INDEX_OUT, help="private dataset folder (replaced)")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    for label, out, include in (("Space (public)", args.out, INCLUDE), ("Index (private dataset)", args.index_out, INDEX)):
        files = build(out, include)
        size = sum(path.stat().st_size for path in files) / 1_000_000
        print(f"{label}: {out.resolve()}  ({len(files)} files, {size:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
