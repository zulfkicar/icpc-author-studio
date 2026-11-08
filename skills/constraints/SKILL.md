---
name: constraints
description: Derive bounds, overflow and complexity requirements from the statement.
when_to_use: Before writing a reference or tests.
version: 1
---

# Constraints

1. Extract every variable, range, sum, product and output bound.
2. Derive the maximum/minimum values and required integer width.
3. Check whether the intended algorithm fits time and memory.
4. List boundary and overflow cases.
5. Record assumptions in NOTES.md and the brief.

Output: bound table, required complexity, overflow risks, edge cases.
