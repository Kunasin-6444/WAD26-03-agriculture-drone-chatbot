> Historical snapshot before the 2026-10-17 MD overhaul. Not current instructions or status. Relative Markdown links rebased for this location.

---
name: pdf-ingestion
description: Build, debug, and test PDF ingestion for this project, including text, native tables, Vision extraction, Knowledge Units, and chunking.
---

# PDF Ingestion Skill

## Extraction strategy

PDF
 ->
text
 ->
native tables
 ->
Vision for meaningful visual content
 ->
KnowledgeUnit

---

## Rules

1. Preserve source filename.

2. Preserve page number.

3. Preserve source type.

4. Never invent missing document content.

5. Vision interpretation is useful but must remain traceable
   to extracted evidence.

6. Do not add image hosting to the MVP.

7. Do not rerun the entire PDF unnecessarily while debugging.

8. Prefer single-page tests during Vision development.

9. External API quota failures must not corrupt unrelated
   local processing.

10. A failed Vision page should not crash the entire ingestion batch
    when the current implementation is designed to tolerate it.

---

## Validation

For each ingestion change:

1. test one page
2. inspect KnowledgeUnits
3. inspect chunks
4. test retrieval
5. only then run broader ingestion

---

## Chunking baseline

Current baseline:

- 800 characters
- 120 character overlap

Do not optimize these numbers without retrieval evidence.