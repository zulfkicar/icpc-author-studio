---
name: interactive-design
description: Design and self-test an interactive protocol.
when_to_use: When the solution talks to the judge.
version: 1
---

# Interactive design

1. Define the protocol: initial data, query format, response format, limits, termination.
2. Implement interactor/output validator with explicit flushing.
3. Test reference and known wrong solutions.
4. Verify query-limit, invalid-query, early-exit, extra-output and deadlock behavior.
5. Capture an .interaction transcript and review it.
6. The deterministic harness owns the verdict.

Output: protocol, interactor path, transcript evidence, self-test matrix.
