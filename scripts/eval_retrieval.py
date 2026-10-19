"""
Retrieval-only evaluation (embeddings only; no LLM). Gold pages are derived from the corpus
text with the predicates in tests/data/retrieval_gold.json, not from the retriever itself.

    python -m scripts.eval_retrieval                 # all retriever configurations
    python -m scripts.eval_retrieval --config global/none --verbose
    python -m scripts.eval_retrieval --mode direct --verbose
"""
from __future__ import annotations

import argparse
import json
import hashlib
from pathlib import Path

from scripts.retrieval_metrics import evidence_groups, score_ranking, validate_cases, verify_source_manifest

GOLD = Path(__file__).resolve().parents[1] / "tests" / "data" / "retrieval_gold.json"
CONFIGS = [(bm25, rerank) for bm25 in ("top50", "global") for rerank in ("legacy", "crop", "none", "diverse")]
KS = (3, 5, 8)


def gold_pages(case: dict, chunks: list[tuple[str, str, str]]) -> set[tuple[str, str]]:
    return set().union(*evidence_groups(case, chunks))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", choices=[f"{b}/{r}" for b, r in CONFIGS], help="bm25/rerank")
    parser.add_argument("--gold", type=Path, default=GOLD, help="Frozen source-annotated or legacy gold JSON")
    parser.add_argument("--split", choices=["all", "dev", "holdout"], default="all")
    parser.add_argument("--embedding-cache", type=Path, default=Path("cache/retrieval_eval_embeddings.json"))
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--mode", choices=["text", "direct"], default="text")
    parser.add_argument("--limit", type=int, help="Limit live embedding calls during smoke testing")
    parser.add_argument("--output", help="Optional JSON report path")
    args = parser.parse_args()

    from app.rag import slide_retriever as sr
    from app.rag import direct_pdf
    from app.rag.vector_store import collection

    data = collection.get(include=["documents", "metadatas"])
    chunks = [(m["source_file"], str(m["page_number"]), d) for d, m in zip(data["documents"], data["metadatas"])]
    gold_bytes = args.gold.read_bytes()
    dataset = json.loads(gold_bytes.decode("utf-8"))
    verify_source_manifest(dataset, Path(__file__).resolve().parents[1] / "data")
    cases = dataset["cases"]
    validate_cases(cases)
    if args.split != "all":
        cases = [c for c in cases if c["split"] == args.split]
    if args.limit is not None:
        if args.limit < 1:
            parser.error("--limit must be positive")
        cases = cases[:args.limit]
    validate_cases(cases)
    groups = {c["id"]: evidence_groups(c, chunks) for c in cases}

    original_embed = sr.embed_text
    from app.rag.embedding import EMBEDDING_MODEL
    try:
        cached = json.loads(args.embedding_cache.read_text(encoding="utf-8"))
        memo = cached["embeddings"] if cached.get("model") == EMBEDDING_MODEL else {}
    except (FileNotFoundError, ValueError, KeyError):
        memo = {}
    # Evaluation must not depend on the 3 s production budget: retry generously, embed each query once.
    def embed_once(text, *a, **k):
        if text not in memo:
            memo[text] = original_embed(text, max_retries=5, timeout_seconds=40.0)
            args.embedding_cache.parent.mkdir(parents=True, exist_ok=True)
            temporary = args.embedding_cache.with_suffix(".tmp")
            temporary.write_text(json.dumps({"model": EMBEDDING_MODEL, "embeddings": memo}), encoding="utf-8")
            temporary.replace(args.embedding_cache)
        return memo[text]
    sr.embed_text = embed_once
    direct_pdf.embed_text = sr.embed_text

    configs = [("direct", "none")] if args.mode == "direct" else ([tuple(args.config.split("/"))] if args.config else CONFIGS)
    summaries, results = [], []
    coverage = None
    if args.mode == "direct":
        indexed = direct_pdf.get_collection().get(include=["metadatas"])["metadatas"]
        coverage = {(m["source_file"], str(m["page_number"])) for m in indexed}
        print(f"Direct PDF index: {len(coverage)} pages. Gold pages come from the existing text corpus.")
    for bm25, rerank in configs:
        sr.RETRIEVER_BM25, sr.RETRIEVER_RERANK = bm25, rerank
        by_split: dict[str, list[dict]] = {}
        details = []
        for case in cases:
            pages = (direct_pdf.search_pdf_pages(case["query"], top_k=max(KS), timeout_seconds=40.0)
                     if args.mode == "direct" else sr.search_slides_pipeline(case["query"], top_k=max(KS))["top_pages"])
            ranked = [(p["source_file"], str(p["page_number"])) for p in pages]
            score = score_ranking(ranked, groups[case["id"]], KS)
            by_split.setdefault(case["split"], []).append(score)
            results.append({"config": f"{bm25}/{rerank}", "id": case["id"], "split": case["split"],
                            "ranked_pages": ranked, **score})
            details.append(f"    {case['id']} rank={score['rank']} aspect_ranks={score['aspect_ranks']}")
        for split, scores in by_split.items():
            n = len(scores)
            hits = {k: sum(s["hits"][k] for s in scores) for k in KS}
            mrr = sum(s["reciprocal_rank"] for s in scores) / n
            complete = {k: sum(s["complete"][k] for s in scores) for k in KS}
            aspect_coverage = {k: sum(s["coverage"][k] for s in scores) / n for k in KS}
            print(f"{bm25:6s}/{rerank:6s} {split:8s} n={n:2d} " + " ".join(f"hit@{k}={hits[k]:2d}" for k in KS) + f" MRR={mrr:.2f}")
            summaries.append({"config": f"{bm25}/{rerank}", "split": split, "n": n,
                              "hits": hits, "mrr": mrr, "complete": complete, "aspect_coverage": aspect_coverage})
        if args.verbose:
            print("\n".join(details))
    if args.output:
        report = {"mode": args.mode, "indexed_pdf_pages": len(coverage) if coverage is not None else None,
                  "gold_file": str(args.gold), "gold_sha256": hashlib.sha256(gold_bytes).hexdigest(),
                  "corpus_sha256": hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                  "gold_kind": "source_annotated" if all("evidence_groups" in c for c in cases) else "legacy_regex",
                  "partial_run": args.limit is not None, "split": args.split,
                  "cases_without_gold": [], "summaries": summaries, "results": results,
                  "note": "Retrieval only; no answer model. Query embeddings reused across configurations. A partial PDF index is not comparable to the full text index."}
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
