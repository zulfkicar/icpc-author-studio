---
name: validator-design
description: Write and self-test a strict input validator.
when_to_use: Before trusting any test input.
version: 1
---

# Validator design

1. Parse exactly the declared format.
2. Enforce every bound, count, range and relationship.
3. Reject malformed, missing, extra and out-of-range input.
4. Add invalid-input fixtures.
5. Run the validator on every test and on invalid fixtures.

Output: validator path, accepted/rejected fixtures, exit-code evidence.
