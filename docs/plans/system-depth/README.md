# Full system audit and implementation plan

Prepared: 2026-11-10
Status: audit and planning complete, implementation pending
Scope: `C:\Projects\author-agent`

The workbench has a functioning authoring runtime, deterministic package checks,
reviewable edits and execution workers. Its next stage needs two kinds of work:
repair inconsistent guarantees in the existing system, then add the domain
procedures and evidence needed to justify problems and solutions.

This package is the current forward plan. It incorporates the
[domain-depth scope](../../DOMAIN-DEPTH-PLAN.md) and supersedes the forward-looking
backlog in older plans where they conflict. It does not rewrite historical test
results, implement these changes or establish production readiness.

## Read the plan

| Document | Purpose |
|---|---|
| [01 — Audit](01-AUDIT.md) | Coverage, source-grounded findings, priorities and limitations |
| [02 — Architecture](02-ARCHITECTURE.md) | Target boundaries, evidence model, correctness workflow and authority |
| [03 — Skills, prompts and tools](03-DOMAIN-CATALOG.md) | Item-by-item changes to the agent's domain capabilities |
| [04 — Delivery backlog](04-BACKLOG.md) | Ordered tasks, dependencies, owning sources and acceptance criteria |
| [05 — Validation](05-VALIDATION.md) | Existing evidence, missing tests, benchmark design and release gates |
| [06 — Operations and migration](06-OPERATIONS.md) | Compatibility, backup, recovery, packaging and rollout |
| [07 — Sources](07-SOURCES.md) | Primary references and evidence provenance |
| [Source inventory](evidence/source-inventory.json) | Paths, hashes, sizes and Python symbol locations for 316 tracked files |
| [Per-file coverage](evidence/audit-coverage.json) | Review level and planned task ownership for every tracked path |
| [Audit probes](evidence/audit-probes.json) | Eleven isolated observations of current behavior |
| [Selected checks](evidence/selected-checks.json) | Commands, captured output and exit codes for this audit |
| [Plan validation](evidence/plan-validation.json) | Link, ID, dependency and source-integrity checks |

## Audit result

The audit identifies 37 findings and improvement areas, A01–A37. Six are P0
blockers for relying on the affected guarantees. Priority reflects impact within
this local single-user application, not a claim of an externally exploitable
vulnerability or a CVSS score.

Most urgent:

- Make execution fail closed in supported authoring launches.
- Canonicalize file identity before applying secret-data and consent policies.
- Bring interactive verification into the same complete report lifecycle.
- Enforce actual package resource limits through a shared worker contract.
- Use immutable execution inputs and controlled artifact publication.
- Serialize mutations and tie verification/export to an immutable revision.

Selected checks passed while the probes reproduced missing guarantees. Preserve
the useful tests and add checks for the uncovered behavior. A passing suite
alone must not substitute for examining what it tests.

## What to preserve

- The local single-user product scope and loopback binding.
- Deterministic package verification as the authority for its defined checks.
- Human control of export and review.
- Checkpointed conversations and inspectable package files.
- Separate workers, progressive skill loading and bounded model context.
- Existing source, packages, histories and raw evidence.

No framework replacement, public hosting, platform-prototype changes, paid run,
deployment or new service installation is part of executing this planning task.

Recheck the plan with `python -B docs/plans/system-depth/evidence/validate_plan.py`.
Reproduce the isolated observations with
`python -B docs/plans/system-depth/evidence/audit_probes.py`. The latter validates
observations about current behavior, not desired regression-test expectations.

## Delivery order

| Phase | Outcome | Exit condition |
|---|---|---|
| F0 | Reproducible baseline and contracts | Current behavior and desired invariants recorded |
| F1 | Trustworthy execution and package checks | A01–A06 repaired, adversarial boundary tests pass |
| F2 | Durable revisions and evidence | No stale evidence, lost approvals or silent recovery |
| F3 | Deep authoring for initial domains | Skills produce required artifacts and concrete failure diagnoses |
| F4 | Executable counterexample work | Differential search, reduction and mutation evidence reproduce |
| F5 | Integrated author/reviewer workflow | Proof gaps and review findings govern authoring readiness |
| F6 | Validated developer beta | Held-out evaluation and independent-author pilot meet preset gates |
| F7 | Selective formal proof and broader domains | A bounded pilot meets its explicit proof contract |

F1 and F2 establish the basis for later correctness claims. Domain examples and
benchmark curation can be prepared alongside them, but depend on the repaired
contracts before execution is trusted. See the backlog for task-level ordering.

## Completion and reporting

A task is complete only when its acceptance evidence is attached to the
relevant code revision. Track `planned`, `in-progress`, `implemented-unvalidated`,
`validated` and `blocked`, with a reason for any blocker. Preserve failures.
Do not mark an entire phase complete from one demonstration problem.

Use the task IDs in commits and review notes. Each task has an accountable
functional owner in the backlog. These are implementation responsibilities,
not instructions to launch additional autonomous agents.

Estimates are relative: S is a bounded change, M crosses several contracts,
L requires a new subsystem or multi-environment validation. They are planning
estimates, not calendar promises. Re-estimate after F0 and each phase exit.

The product is ready for this expanded scope when an author can trace a claim
from specification through argument and implementation to reproducible evidence,
see what is still uncertain, and review exactly the revision being exported.
