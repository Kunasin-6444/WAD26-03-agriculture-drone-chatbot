"""
Benchmark tool for evaluating end-to-end CRAG latency and answer quality
across 5 representative dimensions.
Usage:
    python -m scripts.benchmark_latency
"""
import time
from app.rag.crag_service import run_crag_pipeline

BENCHMARK_QUERIES = [
    ("พัดส้มกับพัดฟ้าต่างกันอย่างไร", "in_scope_synonym"),
    ("หัวฉีดพัดส้มมีอัตราการไหลเท่าไรต่อหัวฉีด?", "in_scope_exact"),
    ("การขึ้นทะเบียนโดรนเกษตรต้องทำอย่างไร?", "caat_portal"),
    ("ราคาน้ำมันดีเซลวันนี้กี่บาท?", "web_fallback"),
    ("โดรนเกษตรบินไปฉีดปุ๋ยบนดาวอังคารได้ไหม?", "abstain"),
]


def main():
    print("=" * 60)
    print("BENCHMARK EVALUATION (REAL KKU GENAI + PARALLEL CRAG)")
    print("=" * 60)

    results = []
    for q, cat in BENCHMARK_QUERIES:
        t0 = time.time()
        resp = run_crag_pipeline(q)
        el = time.time() - t0
        results.append((q, cat, el, resp.source_type, resp.grade, resp.answer))
        print(f"\n[Category: {cat}] Query: {q}")
        print(f"Latency: {el:.2f}s | Source: {resp.source_type} | Grade: {resp.grade}")
        print(f"Answer snippet: {resp.answer[:150].strip()}...")

    avg_lat = sum(r[2] for r in results) / len(results)
    print("\n" + "=" * 60)
    print(f"AVERAGE LATENCY: {avg_lat:.2f}s across {len(results)} queries")
    print("=" * 60)


if __name__ == "__main__":
    main()
