---
description: Testing and verification rules for this project.
alwaysOn: true
---

# Testing Rules

1. Write tests alongside non-trivial features.

2. Run the smallest relevant test after each change.

3. Run the broader test suite before declaring completion.

4. Every bug fix should add a regression test when possible.

5. Tests must validate behavior and expected evidence.

6. Do not weaken assertions merely to make tests pass.

7. Do not delete failing tests unless the requirement itself changed.

8. External API tests should be isolated from pure unit tests.

9. Real retrieval tests should use representative Thai questions.

10. Integration tests must verify source/page metadata.

11. Never claim "all tests pass" unless the tests were actually run.