---
name: pdf-ingestion
description: Diagnose or modify PDF text, table, visual extraction and chunk provenance for a concrete ingestion task.
---

# PDF ingestion

Follow [AGENTS](../../../AGENTS.md), [INGESTION](../../../docs/INGESTION.md)
and [TEST_PLAN](../../../docs/TEST_PLAN.md).
No fixed chunk size, extractor, model or mandatory live ingestion sequence is imposed by this skill.

- Start with the affected source page/record. Preserve filename, document ID, page/range, source type and provenance.
- Keep row/column labels, units and conditions attached to values; do not fabricate unreadable visual content.
- Distinguish complete, degraded and failed extraction. Native text alone does not prove complete visual coverage.
- Use recorded/cached evidence and focused offline checks first. Vision/embedding calls require the user's permitted scope.
- Retry only affected work when warranted; do not reprocess the entire corpus by default.
- Do not corrupt unrelated pages, clear existing data or publish partial extraction as complete.
- Keep index publication and rollback safe; follow the approved CAAT source exclusions.

Broader ingestion or retrieval evaluation is a deliberate follow-up, not an automatic completion checklist.
