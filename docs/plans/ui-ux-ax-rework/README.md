# UI/UX/AX rework — execution package

Status: **Phases 0-5 complete except the manual A-10 screen-reader sign-off.**
Baseline: commit `03714a6` or later.
Owner: workbench frontend + accessibility.
Canonical design rationale: [`../../UI-UX-REDESIGN.md`](../../UI-UX-REDESIGN.md).
Canonical state catalog: [`../../STATE-MACHINES.md`](../../STATE-MACHINES.md).

This folder is the execution package for turning the current workbench into the
five-region, Cline/VS Code-informed IDE described in the design document. It is
written so a coding agent can execute it phase by phase without re-deriving the
product, the constraints or the quality gates.

## Read order

1. [`00-CONSTITUTION.md`](00-CONSTITUTION.md) — non-negotiable principles.
2. [`01-SPEC.md`](01-SPEC.md) — what the user gets and why.
3. [`02-CURRENT-STATE.md`](02-CURRENT-STATE.md) — what exists today.
4. [`03-ARCHITECTURE.md`](03-ARCHITECTURE.md) — how the target is built.
5. [`04-TASKS.md`](04-TASKS.md) — dependency-ordered work.
6. [`05-TEST-PLAN.md`](05-TEST-PLAN.md) — how “done” is proven.
7. [`06-ROLLOUT.md`](06-ROLLOUT.md) — PR sequence, risks and rollback.
8. [`07-RESEARCH.md`](07-RESEARCH.md) — sources and decisions.
9. [`GOAL-PROMPT.md`](GOAL-PROMPT.md) — the executable prompt.
10. [`PROMPT-DESIGN.md`](PROMPT-DESIGN.md) — why the prompt is written this way.
11. [`EVIDENCE.md`](EVIDENCE.md) — commands, outputs, screenshots, residual risks.

If two documents conflict, stop and resolve in this order:
**constitution → spec → architecture → tasks → test plan → rollout**.
Do not “fix” a conflict by editing the lower document to match an accidental
implementation detail.

## Authority and scope

- The deterministic verifier remains the authority. Judge0 is a quick-run
  backend only.
- The workbench is a local, single-user authoring tool. No multi-user, cloud
  sync or live DOMjudge work is in scope.
- The current UI is the baseline. This is a rework, not a greenfield rewrite.
- Behaviour must be preserved unless a task explicitly changes it.

## Working agreement

- One phase per PR. One concern per commit where practical.
- Every task has an ID, files, dependencies and an acceptance check.
- Every visual change has a rendered screenshot, not only source review.
- Every regression fix starts with a failing test that reproduces the symptom.
- Every phase ends with the full gate set in
  [`05-TEST-PLAN.md`](05-TEST-PLAN.md), not a subset.
- Evidence goes in `qa/screenshots/` and `docs/plans/ui-ux-ax-rework/EVIDENCE.md`.

## Phase summary

| Phase | Outcome | Estimate |
|---|---|---|
| 0 | Dialog consolidation and baseline hardening | 1 day |
| 1 | Five-region shell: rail, navigator, editor, agent, status | 3–5 days |
| 2 | Monaco editor, tabs, breadcrumbs, diff, file-tree keyboard | 4–6 days |
| 3 | Judge0/Isolate run panel, output tabs, run history | 3–4 days |
| 4 | Evidence, review, export predicate, state migration, AX | 3–4 days |
| 5 | Command palette, onboarding, performance polish | 2–3 days |

Total: roughly **3–4 weeks for one developer**, with Phase 1 independently
shippable in under a week.

## Definition of program done

- Five regions exist and are usable at 1440/1100/768/320.
- Chat is the right agent panel; editor is the centre; navigator is the left.
- Judge0 is embedded natively in the run panel; Isolate remains the verifier.
- Every modal cancels via button, Escape and backdrop, with focus return.
- Every implicit state in scope is a named machine with transition tests.
- axe is 0, the AX tree has no unnamed controls, keyboard-only flows work.
- The verification timing budget is guarded by a test.
- All existing `qa/test_*`, CDP, soak and accessibility suites are green.
- `EVIDENCE.md` records commands, outputs, screenshots and residual risks.

## Update discipline

When a phase completes:

1. Append the evidence to `EVIDENCE.md`.
2. Update `../../IMPLEMENTATION-STATUS.md`.
3. Tick the task in `04-TASKS.md`.
4. Update `../../UI-UX-REDESIGN.md` only if the design changed.
5. Never rewrite history to make a failed gate look green.
