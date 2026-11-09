# Constitution

These principles outrank convenience, speed and visual preference. A change that
violates one is not done, even if the tests pass.

## Article 1 — Evidence over assertion

- A UI claim is proven by a rendered page, a measurement or a test output — not
  by reading the source.
- Every defect fix includes the before/after measurement or a screenshot pair.
- Every phase report includes the exact commands run and their actual output.
- “Looks fine” is not evidence. “Composer bottom 886 px in a 900 px viewport”
  is evidence.

## Article 2 — Preserve behaviour unless a task changes it

- Keep existing IDs, API routes, data shapes and user-visible workflows.
- The shell move must not rewrite feature logic. Move DOM first, then improve.
- A refactor that changes behaviour needs its own task and its own acceptance
  test.
- The verifier, executor and Judge0 boundaries are not UI refactor targets.

## Article 3 — Accessibility is a gate, not a polish step

Every phase must pass:

- axe: 0 serious/critical violations;
- AX tree: no unnamed `button`, `textbox`, `combobox`, `tab` or `dialog`;
- keyboard: every control reachable in reading order, Enter/Space activates,
  Escape closes overlays, focus returns to the invoker;
- focus visible: ≥ 2 px indicator with ≥ 3:1 contrast;
- target size: ≥ 24×24 CSS px desktop, ≥ 44×44 on coarse pointers;
- contrast: 4.5:1 body text, 3:1 large text and UI;
- no colour-only status;
- `prefers-reduced-motion` respected.

Accessibility may never be traded for density or aesthetics.

## Article 4 — One source of truth per state

- Every screen state is derived from a named machine in `web/machines.js`.
- No new nullable boolean may encode a lifecycle.
- `send(event)` is the only transition path; `set(state)` is only for
  hydration/workspace restore.
- Illegal events are no-ops with a development warning, never user-facing
  exceptions.
- UI controls are derived from state: disabled, hidden, labels and live text
  must not be set independently in three places.

## Article 5 — The verifier is the authority

- The deterministic verifier (Isolate-backed) decides whether a package is
  verified.
- Judge0 is a **quick-run** backend only. It never marks a package verified.
- The agent may propose, explain and audit; it may not approve its own work.
- Export is allowed only when: verified, not stale, zero unreviewed changes.
- Secret tests and `.ans` files never leave the workspace.

## Article 6 — Security and privacy are structural

- No provider key in the executor or isolate worker.
- No external network from execution containers.
- No unsandboxed model-written code.
- No path traversal, zip traversal, output flood or cross-workspace read.
- Destructive actions name the object and consequence and require explicit
  confirmation.
- Secrets are never written to docs, tests, screenshots or commit messages.

## Article 7 — Small, reversible changes

- One phase per PR; one concern per commit where practical.
- Prefer additive migration (new region, old IDs) over a flag day.
- Every phase has a rollback path in [`06-ROLLOUT.md`](06-ROLLOUT.md).
- If a change cannot be rolled back cleanly, it needs a feature flag or a
  smaller first step.

## Article 8 — Reproduce, then fix

- A bug fix starts with a failing test or a measured reproduction.
- A perf fix starts with a baseline timing and ends with a guarded budget.
- A visual fix starts with a screenshot and ends with a screenshot.
- A state fix starts with an illegal-state reproduction and ends with a
  transition test.

## Article 9 — Developer experience is part of the product

- No build step unless it buys something the project cannot get otherwise.
- New dependencies need a written justification and a removal path.
- Commands in docs must be copy-pasteable and current.
- The repo must remain runnable by one developer on Windows + WSL + Docker.
- Comments explain *why*, not *what*.

## Article 10 — Stop rules

Stop and ask only when:

- a decision changes semantics, security, verification authority or
  destructive behaviour;
- two authoritative documents conflict;
- a required service is unavailable and no local fallback exists;
- the same gate fails after two focused fix attempts;
- a change would require touching a secret or an out-of-scope system.

Do **not** stop for routine choices: spacing, naming, file placement, test
ordering, or which existing pattern to follow. Choose the documented default,
record it, and continue.

## Enforcement map

| Principle | Enforced by |
|---|---|
| Evidence | `qa/layout_regression.ps1`, screenshots, `EVIDENCE.md` |
| Behaviour preserved | existing `qa/test_*`, CDP workflow |
| Accessibility | axe, AX-tree, keyboard checks |
| One state truth | `qa/test_state_machines.mjs`, transition tests |
| Verifier authority | verifier tests, export predicate, no Judge0 approval |
| Security | `test_executor_security`, `test_executor_limits`, `test_security` |
| Reversible changes | PR sequence and rollback notes |
| Reproduce first | failing test in the task's first commit |
| DX | no-build rule, command checks |
| Stop rules | this document and the goal prompt |
