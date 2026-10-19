---
description: Proportionate verification without automatic live or repeated full-suite runs.
alwaysOn: true
---

# Verification rules

Follow [AGENTS.md](../../AGENTS.md) and [TEST_PLAN](../../docs/TEST_PLAN.md).
Documentation-only work gets documentation checks, not application/provider tests.
Use focused offline checks for changed behavior; expand only for a concrete integration or release risk.
Do not require a full suite after every fix or a live evaluation after every RAG change.
The owner stopped automatic API/live testing; explicit bounded requests and manual questions authorize their own scope.
Report actual results and limits. Previous reports are not fresh verification.
