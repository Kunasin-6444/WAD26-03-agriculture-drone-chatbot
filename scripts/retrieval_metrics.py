"""Source-annotated retrieval contracts, independent of Chroma and providers."""
from __future__ import annotations

import re
import hashlib
from pathlib import Path


def evidence_groups(case: dict, chunks: list[tuple[str, str, str]]) -> list[set[tuple[str, str]]]:
    if "evidence_groups" in case:
        groups = []
        for group in case["evidence_groups"]:
            pages = {(p["source_file"], str(p["page_number"])) for p in group["pages"]}
            if not pages or any(not f or not n.isdigit() or int(n) < 1 for f, n in pages):
                raise ValueError(f"Invalid source pages: {case['id']}")
            groups.append(pages)
        if not groups:
            raise ValueError(f"No evidence groups: {case['id']}")
        return groups
    # Historical regex gold remains usable for comparisons, explicitly labelled.
    pages = {(file, page) for file, page, text in chunks
             if any(all(re.search(rx, text, re.IGNORECASE) for rx in predicate) for predicate in case["gold"])}
    if not pages:
        raise ValueError(f"No matching source pages: {case['id']}")
    return [pages]


def score_ranking(ranked: list[tuple[str, str]], groups: list[set[tuple[str, str]]], ks=(3, 5, 8)) -> dict:
    ranks = [next((i for i, page in enumerate(ranked, 1) if page in group), None) for group in groups]
    first = min((r for r in ranks if r is not None), default=None)
    return {"rank": first, "aspect_ranks": ranks, "reciprocal_rank": 1 / first if first else 0,
            "hits": {k: int(first is not None and first <= k) for k in ks},
            "coverage": {k: sum(r is not None and r <= k for r in ranks) / len(groups) for k in ks},
            "complete": {k: int(all(r is not None and r <= k for r in ranks)) for k in ks}}


def validate_cases(cases: list[dict]) -> None:
    if not cases:
        raise ValueError("Evaluation must contain cases")
    ids = [c["id"] for c in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate case IDs")
    if any(c.get("split") not in {"dev", "holdout"} or not c.get("query", "").strip() for c in cases):
        raise ValueError("Every case needs a dev/holdout split and a question")


def verify_source_manifest(dataset: dict, data_directory: Path) -> None:
    for filename, expected in dataset.get("source_sha256", {}).items():
        path = data_directory / filename
        if Path(filename).name != filename or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Gold source PDF changed; annotations must be reviewed/versioned")
