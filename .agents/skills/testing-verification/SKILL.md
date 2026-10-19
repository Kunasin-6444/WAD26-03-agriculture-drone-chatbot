---
name: testing-verification
description: Select and perform proportionate verification for behavior changes or an explicit testing request. Avoid unnecessary live calls and repeated full suites.
---

# Testing and verification

Follow [AGENTS](../../../AGENTS.md) and [TEST_PLAN](../../../docs/TEST_PLAN.md).
This replaces the former mandatory full-suite-before-every-completion workflow.

- Identify the changed user-visible behavior and risk. Choose the smallest meaningful offline check.
- Documentation-only edits need document/link checks, not pytest or live requests.
- Add or replace regression tests when they protect consequential behavior; avoid tests that just mirror implementation.
- Retain useful existing tests. Remove obsolete tests with a concrete replacement or explanation.
- Expand to integration/full regression when the change or release scope justifies it. Do not repeat after every minor edit.
- Run live/API, real LINE or ingestion only within the user's explicit scope; manual question submission authorizes that question.
- If a provider is unavailable, record it and stop the batch rather than repeat it until green.
- Separate historical results from current checks and explain untested limits briefly.

Passing every historical benchmark is not a gate for handing the owner a local manual trial.
Do not change gold or expected values merely to match generated output.
