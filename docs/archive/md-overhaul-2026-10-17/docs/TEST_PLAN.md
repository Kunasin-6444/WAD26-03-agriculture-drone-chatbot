> Historical snapshot before the 2026-10-17 MD overhaul. Not current instructions or status. Relative Markdown links rebased for this location.

# Test Plan

## คำสั่งและหลักฐานรุ่นปัจจุบัน

ดู [รายงานส่งมอบ](../../../RELEASE_READINESS_2026-10-17.md) และรันจาก repository root:

```powershell
.venv/Scripts/python.exe -B -m pytest -q tests -p no:cacheprovider
.venv/Scripts/python.exe -B -m scripts.verify_ingestion
.venv/Scripts/python.exe -B -m scripts.audit_contract_gaps --output docs/CONTRACT_CURRENT.json
.venv/Scripts/python.exe -B -m scripts.eval_retrieval --config global/diverse --gold tests/data/source_gold.json --output docs/RETRIEVAL_CURRENT.json
.venv/Scripts/python.exe -B -m scripts.evaluate_acceptance --warmup --output docs/ACCEPTANCE_CURRENT.json
.venv/Scripts/python.exe -B -m scripts.evaluate_acceptance --warmup --gold tests/data/source_gold.json --output docs/SOURCE_CURRENT.json
.venv/Scripts/python.exe -B -m scripts.evaluate_acceptance --warmup --cases tests/data/hybrid_acceptance.json --output docs/HYBRID_CURRENT.json
.venv/Scripts/python.exe -B -m scripts.smoke_deployment --output docs/DEPLOY_CURRENT.json
docker build --target test -t agriculture-drone-chatbot:test .
```

Pytest/integrity/contract probes/deployment smoke เป็น offline ส่วน live acceptance ใช้ API จริงและมีค่าใช้จ่าย Retrieval ใช้ embedding cache สำหรับคำถามที่เคยประเมิน การประเมิน source gold ต้องใช้ PDF เดิมตาม SHA ที่ตรึงไว้ ห้ามปรับคำถาม/เฉลย holdout เพื่อให้คะแนนดีขึ้น

คำสั่ง `scripts.evaluate_benchmark` และ `scripts.benchmark_latency` ใช้ evaluator เดียวกันแล้ว ไม่มี keyword-only success gate เก่า ผล semantic/aspect และ latency ต้องรายงานแยกกัน รวม provider failures ในตัวหาร และห้ามแก้ app/harness ระหว่างรัน final batch

## Principle

Tests must verify behavior.

Do not treat "function executed without exception"
as sufficient evidence of correctness.

---

# Level 1 — Unit Tests

## Chunking

Verify:

- empty input
- short text
- text larger than chunk size
- overlap
- invalid overlap
- metadata preservation

---

## Knowledge Unit

Verify:

- schema validation
- valid source types
- required metadata
- empty content handling

---

## Retrieval Formatting

Verify:

- retrieved chunks are formatted correctly
- source filename is preserved
- page number is preserved
- source type is preserved

---

# Level 2 — Component Tests

## Embedding

Verify:

- non-empty vector returned
- dimension is 3072
- empty input raises error
- temporary API failure is retried

Do not hard-code exact vector values.

---

## Chroma

Verify:

- insert
- upsert
- query
- metadata
- persistence

Use an isolated test collection/database where possible.

---

# Level 3 — Retrieval Tests

Use real representative questions.

Example:

### Q1

"หัวฉีดพัดส้มมีอัตราการไหลเท่าไรต่อหัวฉีด?"

Expected evidence:

UAV07 page 12 table containing:

พัดส้ม
1600 rpm
500 ml/หัวฉีด
1500 ml / 3 หัวฉีด

---

### Q2

"ที่ความสูง 1 เมตร หน้ากว้างการฉีดพ่นต่อหัวเท่าไร?"

Expected evidence:

UAV07 page 12 table:

1.0 m
2.8 m per head
4.5 m for 3 heads

---

### Q3

"หัวฉีดแบบใดมีอัตราการไหลสูงที่สุด?"

Expected evidence:

UAV07 page 12 flow-rate table.

The test should verify that the relevant table is
retrieved in the top-K context.

Do not require an exact rank unless the evaluation
explicitly defines one.

---

# Level 4 — Generation Tests

Verify:

- answer uses retrieved evidence
- answer includes source
- unsupported claims are not generated
- Thai response quality
- source/page references are preserved

Use deterministic or controlled evaluation
where practical.

---

# Level 5 — CRAG Tests

## In-scope

Expected:

KB answer

## Out-of-scope

Expected:

web fallback

## Ambiguous

Expected:

clarification or abstain,
depending on implementation

## Unsupported

Expected:

abstain

---

# Level 6 — Web Fallback Tests

Verify:

- Tavily called when KB is insufficient
- official sources preferred
- URL retained
- web answer does not claim KB evidence

---

# Level 7 — LINE Tests

Verify:

- signature verification
- message parsing
- reply token handling
- successful answer
- error handling

---

# Level 8 — End-to-End

Flow:

LINE message
 ->
FastAPI
 ->
CRAG
 ->
retrieval/web
 ->
LLM
 ->
LINE reply

At least 20-30 real Thai questions should be tested
before final delivery, including:

- in-scope
- out-of-scope
- ambiguous
- unsupported
