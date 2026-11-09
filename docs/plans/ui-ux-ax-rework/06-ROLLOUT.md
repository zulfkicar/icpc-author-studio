# Rollout, risks and operations

## 1. PR sequence

One PR per phase; within a phase, one coherent commit per task group.

### PR-1 — Dialog consolidation

Scope: D-1..D-5.
Files: `web/app.js`, `web/index.html`, `qa/layout_regression.ps1`,
`qa/test_ui_contracts.py`.
Rollback: revert the PR; dialog markup and listeners are self-contained.
Gate: dialog matrix + axe/AX-tree.

### PR-2 — Shell scaffolding

Scope: S-1..S-3, S-8, S-10.
Files: `web/index.html`, `web/style.css`, `web/app.js`, tests.
Rollback: restore the previous grid/markup; no feature code moved yet.
Gate: layout regression + screenshots at 1440/1100/768/320.

### PR-3 — DOM move

Scope: S-4..S-7, S-9.
Files: `web/index.html`, `web/style.css`, `web/app.js`.
Rollback: revert the DOM move; IDs and handlers are unchanged.
Gate: full UI suite, chat/editor/run flows.

### PR-4 — Responsive shell

Scope: S-11..S-15.
Files: `web/style.css`, `web/app.js`, `qa/layout_regression.ps1`,
`qa/screenshots.ps1`.
Rollback: revert drawer/sheet CSS; desktop layout unaffected.
Gate: four widths + keyboard + axe.

### PR-5 — Monaco editor

Scope: E-1..E-10.
Files: `web/vendor/monaco/**`, `web/app.js`, `web/style.css`,
`web/index.html`, tests.
Rollback: disable Monaco loader and use the textarea fallback; files remain
editable.
Gate: editor matrix + fallback + performance.

### PR-6 — Run/Judge0 UX

Scope: R-1..R-10.
Files: `web/index.html`, `web/app.js`, `web/style.css`, `judge0_adapter.py`,
`server.py`, tests.
Rollback: revert to the three-button run panel; backend routes unchanged.
Gate: live Judge0/Isolate + security + timing.

### PR-7 — Evidence/review/state/AX

Scope: A-1..A-12, M-1..M-6.
Files: `web/app.js`, `web/machines.js`, `web/index.html`, `web/style.css`,
`qa/test_state_machines.mjs`, `qa/layout_regression.ps1`,
`qa/accessibility_*.ps1`.
Rollback: per-machine commits are revertible; keep the old field until the
machine PR is green.
Gate: full suite + manual screen reader.

### PR-8 — Polish

Scope: P-1..P-8.
Files: frontend + docs.
Rollback: per-feature commits.
Gate: final acceptance.

## 2. Branch and commit strategy

- Work on a short-lived branch per PR.
- Commit messages: `Area: imperative summary` plus a body with evidence.
- Keep docs and code in the same PR when the contract changes.
- Do not mix a state migration with a visual redesign in one commit.
- Never commit generated secrets, workspace data or `.env`.

## 3. Feature flags and toggles

No general feature-flag framework is needed. Use narrow, removable flags only
where a rollback would otherwise be expensive:

| Flag | Location | Purpose |
|---|---|---|
| `?editor=textarea` | URL/localStorage | force the editor fallback |
| `?agent=drawer` | URL | force drawer mode for testing |
| `localStorage.author-agent-layout` | client | persist widths/mode |

Remove a flag once the phase is stable for one release cycle.

## 4. Migration and rollback

### Shell move

- Move DOM nodes, keep IDs. If the move breaks a handler, fix the handler
  rather than adding a second hidden duplicate.
- Keep a screenshot before/after for the same workspace/file/chat.

### State migration

- Add the machine and mirror first.
- Move readers to the machine.
- Move writers to `send(event)`.
- Delete the old field in the same PR only after all references are gone.
- Keep the old field one commit longer if a rollback would otherwise lose data.

### Editor

- Monaco is lazy; a loader failure must leave the textarea path fully usable.
- Do not migrate file save/storage format; only the editing surface changes.

### Run panel

- Keep the existing API routes. The backend selector is a UI facade over the
  same endpoints.
- If Judge0 is unavailable, hide/disable it rather than failing a run.

## 5. Risk register

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-1 | DOM move breaks a handler | Medium | High | ID manifest; run full UI suite after move |
| R-2 | Monaco bundle/worker/CSP | Medium | High | lazy load; textarea fallback; measure TTI |
| R-3 | State migration regresses behaviour | Medium | High | additive mirror; one machine per PR; transition tests |
| R-4 | Responsive drawers trap focus | Medium | Medium | focus trap + Escape + return; keyboard test |
| R-5 | Judge0 secret leakage | Low | Critical | client/server block; negative tests |
| R-6 | Verifier budget regression | Medium | High | demand copy; timing guard; batch if needed |
| R-7 | In-memory job loss on restart | Medium | Medium | document; avoid restarts during jobs; surface error |
| R-8 | AX regression from density | Medium | High | axe/AX-tree every phase; manual pass |
| R-9 | Test flakiness under load | Medium | Medium | one retry, then fix cause; isolate browser runs |
| R-10 | Scope creep into backend redesign | Medium | High | constitution + task IDs; defer non-UI work |

## 6. Observability

Add lightweight client telemetry (local only, no external calls):

- `data-state-*` transitions;
- last 50 machine transitions in memory (`window.__AUTHOR_AGENT__`);
- last run result per file;
- visible toast/error for failed fetches.

Do not send telemetry to a third party. This is a local tool.

## 7. Performance operations

- Measure before/after each phase:
  - editor interactive time;
  - layout shift on run start;
  - transcript append frame time;
  - 30-iteration DOM soak growth;
  - 100-test verifier wall time.
- Record the numbers in `EVIDENCE.md`.
- A regression over budget blocks the phase.

## 8. Communication

- Update `IMPLEMENTATION-STATUS.md` after each phase.
- Append `EVIDENCE.md` with commands/output/screenshots.
- Open decisions are listed in `01-SPEC.md`; do not bury them in chat.
- If a phase is blocked, state the blocker, the attempted fixes, and the
  smallest next action.

## 9. Decision log

| Date | Decision | Reason | Reversible? |
|---|---|---|---|
| 2026-11-09 | Five-region shell | VS Code/Cline mental model | Yes, before PR-3 |
| 2026-11-09 | Agent panel right | Editor remains central | Yes |
| 2026-11-09 | Native Judge0 panel, no iframe | Shares workspace/editor | Yes |
| 2026-11-09 | Monaco lazy + fallback | Parity + resilience | Yes |
| 2026-11-09 | Custom FSM layer | No build step; incremental | Yes |
| 2026-11-09 | Evidence as editor tabs | Long reports need room | Yes |
| 2026-11-09 | One action dialog | Consistent cancel/focus | Yes |
| 2026-11-09 | Responsive drawers | Preserve regions on narrow screens | Yes |

## 10. Release checklist

- [ ] Phase gate green.
- [ ] `EVIDENCE.md` updated.
- [ ] `IMPLEMENTATION-STATUS.md` updated.
- [ ] Screenshots at four widths.
- [ ] No native dialogs.
- [ ] axe 0, AX-tree clean.
- [ ] No new secrets or workspace data committed.
- [ ] Rollback note present.
- [ ] PR description includes commands and actual results.
