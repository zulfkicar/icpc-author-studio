---
name: checker-design
description: Write and self-test an output validator/checker.
when_to_use: When multiple outputs are correct or output requires semantic checking.
version: 1
---

# Checker design

1. State exactly what makes an output valid.
2. Implement a checker/output validator with testlib or the package's validator API.
3. Self-test: reference accepted, alternative valid accepted, known wrong rejected, malformed rejected, missing/extra rejected, invalid jury answer fails, timeout/crash fails.
4. Add valid_output and invalid_output fixtures.
5. Never treat a checker as trusted until the self-test matrix passes.

Output: checker path, matrix, failure messages.
