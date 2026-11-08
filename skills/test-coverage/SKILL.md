---
name: test-coverage
description: Build a requirement-level coverage matrix and identify gaps.
when_to_use: Before trusting tests or verification.
version: 1
---

# Test coverage

Build a matrix over: constraint boundaries, structural cases, output multiplicity, precision, adversarial cases, performance, malformed input, negative-solution families and interactive protocol states.

For each cell record: covered by which test, expected behavior, gap or risk. Do not treat line coverage as proof of semantic coverage.

Output: matrix, uncovered risks, recommended tests.
