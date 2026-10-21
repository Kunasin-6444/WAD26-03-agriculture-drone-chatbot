"""
Retrieval-only evaluation (embeddings only; no LLM). Gold pages are derived from the corpus
text with the predicates in tests/data/retrieval_gold.json, not from the retriever itself.

    python -m scripts.eval_retrieval                 # all retriever configurations
    python -m scripts.eval_retrieval --config global/none --verbose
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

GOLD = Path(__file__).resolve().parents[1] / "tests" / "data" / "retrieval_gold.json"
CONFIGS = [(bm25, rerank) for bm25 in ("top50", "global") for rerank in ("legacy", "crop", "none")]
KS = (3, 5, 8)


def gold_pages(case: dict, chunks: list[tuple[str, str, str]]) -> set[tuple[str, str]]:
    pages = set()
    for source_file, page, text in chunks:
        for predicate in case["gold"]:
            if all(re.search(rx, text, re.IGNORECASE) for rx in predicate):
                pages.add((source_file, page))
                break
    return pages


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="bm25/rerank, e.g. global/crop")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    from app.rag import slide_retriever as sr
    from app.rag.vector_store import collection

    data = collection.get(include=["documents", "metadatas"])
    chunks = [(m["source_file"], str(m["page_number"]), d) for d, m in zip(data["documents"], data["metadatas"])]
    cases = json.loads(GOLD.read_text(encoding="utf-8"))["cases"]
    golds = {c["id"]: gold_pages(c, chunks) for c in cases}
    empty = [cid for cid, g in golds.items() if not g]
    if empty:
        print(f"WARNING: gold predicate matches no page in the KB for: {empty}")

    original_embed = sr.embed_text
    memo: dict[str, list[float]] = {}
    # Evaluation must not depend on the 3 s production budget: retry generously, embed each query once.
    sr.embed_text = lambda text, *a, **k: memo[text] if text in memo else memo.setdefault(
        text, original_embed(text, max_retries=5, timeout_seconds=40.0))

    configs = [tuple(args.config.split("/"))] if args.config else CONFIGS
    for bm25, rerank in configs:
        sr.RETRIEVER_BM25, sr.RETRIEVER_RERANK = bm25, rerank
        by_split: dict[str, list[int | None]] = {}
        details = []
        for case in cases:
            if not golds[case["id"]]:
                continue
            pages = sr.search_slides_pipeline(case["query"], top_k=max(KS))["top_pages"]
            ranked = [(p["source_file"], str(p["page_number"])) for p in pages]
            rank = next((i for i, key in enumerate(ranked, 1) if key in golds[case["id"]]), None)
            by_split.setdefault(case["split"], []).append(rank)
            details.append(f"    {case['id']} rank={rank} gold_pages={len(golds[case['id']])}")
        for split, ranks in by_split.items():
            n = len(ranks)
            hits = {k: sum(1 for r in ranks if r is not None and r <= k) for k in KS}
            mrr = sum(1.0 / r for r in ranks if r) / n
            print(f"{bm25:6s}/{rerank:6s} {split:8s} n={n:2d} " + " ".join(f"hit@{k}={hits[k]:2d}" for k in KS) + f" MRR={mrr:.2f}")
        if args.verbose:
            print("\n".join(details))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
