"""Inspect retrieved and packed evidence without answer generation or LINE sends."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--query")
    group.add_argument("--case", type=int, help="1-based live acceptance case")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    from app.rag.rag_service import retrieve_evidence
    from app.rag.evidence import pack_evidence
    from scripts.evaluate_acceptance import CASES
    if args.case is not None and not 1 <= args.case <= len(CASES):
        parser.error("--case outside the acceptance set")
    query = args.query if args.query is not None else CASES[args.case - 1]["query"]
    raw = retrieve_evidence(query)
    packed = pack_evidence(raw)
    ids = {item.id for item in packed}
    report = {"query": query, "sources": [{**item.__dict__, "characters": len(item.content),
                                              "packed": item.id in ids} for item in raw]}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"retrieved={len(raw)} packed={len(packed)} output={output}")
    return 0 if packed else 1


if __name__ == "__main__":
    raise SystemExit(main())
