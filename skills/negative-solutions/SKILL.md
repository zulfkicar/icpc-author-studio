---
name: negative-solutions
description: Design genuinely wrong solutions that exercise specific defects.
when_to_use: Before verification; after tests are drafted.
version: 1
---

# Negative solutions

Choose defect families: wrong formula, overflow, off-by-one, greedy trap, wrong data structure, precision, duplicate handling, output format, time/memory.

Each negative must be genuinely wrong for the stated constraints. If it survives because it is actually correct, remove or replace it; never weaken tests or constraints. Record the expected killing test.

Output: defect family, source path, expected killing test, actual verdict.
