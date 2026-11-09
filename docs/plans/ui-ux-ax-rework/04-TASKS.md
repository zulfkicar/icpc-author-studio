# Tasks

Dependency-ordered work. `[P]` means it can run in parallel with other `[P]`
tasks in the same phase. Every task has an acceptance check; “implemented” without
the check is not done.

Status: Phase 0, Phase 0.5, Phase 1 and the Phase 3 run-panel slice are complete. Phase 2 (Monaco/tabs) is next.

## Conventions

- ID format: `D` dialog, `S` shell, `E` editor, `R` run, `A` accessibility/
  evidence, `M` machine migration, `P` polish, `C` continuous.
- “Files” lists the expected touch points, not an exhaustive allowlist.
- “Verify” is the minimum check for that task; the phase gate still applies.
- Commit one task or one coherent group per commit.
- Update `EVIDENCE.md` when a task closes.

## Phase 0 — completed baseline

- [x] Grid constraint: scroll, composer and run panel stay in view.
- [x] Accessible action dialog replacing `prompt`/`confirm`.
- [x] Cancel button, Escape and backdrop close, with focus return.
- [x] Chat action labels and keyboard chat titles.
- [x] `web/machines.js` with connection/session/turn/approval/editor/run/modal.
- [x] `qa/layout_regression.ps1` and `qa/test_state_machines.mjs`.
- [x] Design, state, research and status documents.
- [x] Isolate copy optimization and defensive metadata parsing.

## Phase 0.5 — dialog consolidation (1 day)

- [x] **D-1** Create one dialog controller.
  - Files: `web/app.js`, `web/index.html`.
  - Covers: new problem, settings, context, action.
  - API: `openDialog({id, title, description, fields, confirmLabel, danger, validate})`.
  - Verify: all four open through the controller.
  - Est: 0.5d.

- [x] **D-2** Guarantee cancel parity.
  - Every dialog closes on Cancel, Escape and backdrop.
  - Focus returns to the invoker or `#composer`.
  - Verify: `layout_regression` checks all four.
  - Est: 0.2d.

- [x] **D-3** Dirty guard for settings.
  - If fields changed, confirm discard before close.
  - Verify: edit → Cancel → dialog stays until confirmed.
  - Est: 0.2d.

- [x] **D-4** Static lint for native dialogs.
  - Add `qa/lint_ui_contracts.py` or extend `test_ui_contracts.py`.
  - Fails on `prompt(`/`confirm(` in `web/*.js`.
  - Verify: intentional test fixture fails; real code passes.
  - Est: 0.2d.

- [x] **D-5** Dialog accessibility pass.
  - All dialogs have `aria-labelledby`/`aria-describedby`.
  - Errors are `role="alert"`.
  - Verify: AX-tree shows named dialogs and controls.
  - Est: 0.2d.

**Gate D:** `layout_regression`, axe, AX-tree, UI contracts, CDP workflow.

## Phase 1 — five-region shell (3–5 days)

### 1a. Scaffolding

- [x] **S-1** Add region markup without moving features.
  - Files: `web/index.html`, `web/style.css`.
  - Add `.activity-rail`, `.navigator`, `.editor-group`, `.agent-panel`,
    `.statusbar`.
  - Add `data-region` attributes.
  - Verify: screenshot + no visual regression.
  - Est: 0.5d.

- [x] **S-2** Switch `.layout` to the four-column grid.
  - Files: `web/style.css`.
  - `48px | var(--nav-width) | minmax(0,1fr) | var(--agent-width)`.
  - `grid-template-rows: minmax(0,1fr)`.
  - Verify: no overflow; layout regression.
  - Est: 0.2d.

- [x] **S-3** Preserve all existing IDs.
  - Add a `qa/ui_ids.json` manifest and a test that the IDs exist.
  - Verify: `test_ui_contracts` checks the manifest.
  - Est: 0.2d.

### 1b. DOM move

- [x] **S-4** Move chat pane into `.agent-panel`.
  - Keep `#messages`, `#composer`, `#chat-title`, `#agent-state`.
  - Verify: send/stream/scroll/focus tests pass.
  - Depends: S-1, S-2.
  - Est: 0.5d.

- [x] **S-5** Move inspector panels into `.editor-group`.
  - Keep `#panel-*` IDs; add editor tab bar.
  - `switchTab()` remains the controller.
  - Verify: Plan/File/Report/Diff/History/MCP open from tabs.
  - Depends: S-1, S-2.
  - Est: 0.5d.

- [x] **S-6** Move problem card and side panels into `.navigator`.
  - Keep `#side-chats`, `#side-files`, `#side-changes`.
  - Verify: switchSide + all three panels.
  - Depends: S-1.
  - Est: 0.3d.

- [x] **S-7** Add `switchActivity(section)` and rail wiring.
  - Maps rail → navigator/editor views.
  - Verify: every rail item changes the visible region.
  - Depends: S-4, S-5, S-6.
  - Est: 0.3d.

### 1c. Status and controls

- [x] **S-8** Add status bar.
  - Connection dot, backend chips, limits, cursor, language, verification.
  - Verify: values match current editor/summary/settings.
  - Depends: S-1.
  - Est: 0.5d.

- [x] **S-9** Add editor tab bar semantics.
  - `role="tablist"`, `aria-controls`, roving tabindex.
  - Verify: keyboard arrow/Home/End.
  - Depends: S-5.
  - Est: 0.3d.

- [x] **S-10** Add rail semantics.
  - `nav`, `aria-current`, badges, tooltips.
  - Verify: AX-tree and keyboard.
  - Depends: S-7.
  - Est: 0.2d.

### 1d. Resize and responsive

- [x] **S-11** Persist navigator/agent widths.
  - Use localStorage; double-click resets.
  - Verify: reload keeps width.
  - Est: 0.3d.

- [x] **S-12** Agent drawer < 1100 px.
  - Toggle button, focus trap while open, Escape closes.
  - Verify: 768/1100 screenshots.
  - Est: 0.5d.

- [x] **S-13** Navigator sheet < 760 px.
  - Full-height overlay; editor/agent tabs.
  - Verify: 320/480 screenshots; no horizontal scroll.
  - Est: 0.5d.

### 1e. Tests

- [x] **S-14** Region geometry regression.
  - `layout_regression` asserts non-overlap, composer/run panel visibility,
    region bounds at 1440/1100/768/320.
  - Est: 0.5d.

- [x] **S-15** Screenshot set.
  - `qa/screenshots.ps1` captures all regions at four widths.
  - Est: 0.2d.

**Gate S:** all of D + S; axe, AX-tree, UI contracts, CDP, soak.

## Phase 2 — editor (4–6 days)

- [ ] **E-1** Vendor Monaco lazily.
  - Files: `web/vendor/monaco/**`, `web/index.html`, `web/app.js`.
  - AMD loader; no bundler.
  - Verify: editor loads; network tab shows one lazy load.
  - Est: 1d.

- [ ] **E-2** Model per tab.
  - Map path → model + view state.
  - Verify: switch tabs preserves cursor/scroll.
  - Depends: E-1.
  - Est: 0.8d.

- [ ] **E-3** Tab bar.
  - Dirty dot, close, middle-click, `Ctrl+Tab`, `Ctrl+W`.
  - Verify: open 3 files, close middle, dirty guard.
  - Depends: E-2.
  - Est: 0.5d.

- [ ] **E-4** Breadcrumbs.
  - Workspace-relative path segments.
  - Verify: long paths truncate without overflow.
  - Est: 0.3d.

- [ ] **E-5** Save/reload/dirty state.
  - Save uses existing API; dirty flag from machine.
  - Verify: save toast, stale file reload, failed save returns to editing.
  - Est: 0.4d.

- [ ] **E-6** Diff editor.
  - `monaco.editor.createDiffEditor`.
  - Verify: change card opens diff tab; inline/side-by-side toggle.
  - Depends: E-1.
  - Est: 0.8d.

- [ ] **E-7** File-tree keyboard semantics.
  - `role="tree"`, arrows, Enter, changed-file labels.
  - Verify: keyboard-only open/expand.
  - Est: 0.5d.

- [ ] **E-8** Monaco fallback.
  - If load fails, show textarea + highlight.js with the same tab contract.
  - Verify: forced failure test.
  - Est: 0.4d.

- [ ] **E-9** Editor performance guard.
  - No layout shift; interactive < 2 s warm.
  - Verify: timing in CDP.
  - Est: 0.3d.

- [ ] **E-10** Editor tests.
  - open/save/reload, binary/read-only, dirty switch, diff, fallback.
  - Est: 0.5d.

**Gate E:** all of S + E; axe, AX-tree, keyboard, layout regression.

## Phase 3 — run panel and Judge0 (3–4 days)

- [x] **R-1** Backend selector.
  - Isolate/Judge0/Local; disabled states from settings.
  - Verify: setting URL shows/hides backend.
  - Est: 0.4d.

- [x] **R-2** Per-file stdin/backend persistence.
  - localStorage keyed by slug+path.
  - Verify: switch files, values restore.
  - Est: 0.3d.

- [x] **R-3** Output tabs.
  - stdin/stdout/stderr/compile/result.
  - Verify: CE shows compile; RE shows stderr; OK shows stdout.
  - Est: 0.6d.

- [x] **R-4** Status chip/time/memory.
  - Map result fields; truncate long messages.
  - Verify: all statuses.
  - Est: 0.3d.

- [x] **R-5** Run history.
  - Last 10 per file; compare output with previous.
  - Verify: history across reload.
  - Est: 0.5d.

- [x] **R-6** Cancel in-flight.
  - Abort fetch on file change/tab close.
  - Verify: no late render into wrong file.
  - Est: 0.3d.

- [x] **R-7** Quick-run warning.
  - “Quick run is not verification” next to selector.
  - Verify: visible and in AX name.
  - Est: 0.1d.

- [x] **R-8** Secret guard.
  - Client and server refuse `data/secret` and `.ans` for Judge0.
  - Verify: negative tests.
  - Est: 0.3d.

- [x] **R-9** Verification timing guard.
  - Test 100 tests under 15 min; fail on regression.
  - Est: 0.5d.

- [x] **R-10** Run tests.
  - live Judge0, Isolate, local, CE/RE/TO, output cap.
  - Est: 0.5d.

**Gate R:** all of E + R; `test_live_judge0`, `test_isolate_worker`,
`test_executor_limits`, run-panel CDP.

## Phase 4 — evidence, review, state, AX (3–4 days)

- [ ] **A-1** Report as editor tab.
- [ ] **A-2** Stale banner and limits block.
- [ ] **A-3** Review queue in navigator.
- [ ] **A-4** Diff tab from review/change cards.
- [ ] **A-5** Export predicate selector.
- [ ] **A-6** Status bar verification summary.
- [ ] **A-7** Keyboard map implementation.
- [ ] **A-8** Skip links and landmarks.
- [ ] **A-9** Focus-not-obscured checks.
- [ ] **A-10** Manual screen-reader checklist.
- [ ] **A-11** Evidence command output capture.
- [ ] **A-12** Screenshot set for review/export/evidence.

### Machine migrations

- [ ] **M-1** Chat machine.
  - Remove `chats/chatId/chatQuery` ad-hoc transitions.
- [ ] **M-2** File-load machine.
  - Remove `file`/`fileBusy` duplication.
- [ ] **M-3** Verification/export machine.
  - Remove scattered `lastStatus/stale/unreviewed` logic.
- [ ] **M-4** Changes/review machine.
  - Remove `selectedChange`/`approvalRendered` duplication.
- [ ] **M-5** MCP/settings/mentions/follow/tests/restore machines.
- [ ] **M-6** Transition tests for every machine.
  - Illegal event is a no-op; legal event updates the visible control.

**Gate A:** all of R + A + M; axe, AX-tree, keyboard, full CDP, soak.

## Phase 5 — polish (2–3 days)

- [ ] **P-1** Command palette.
- [ ] **P-2** Quick open.
- [ ] **P-3** Notification centre / long-job status.
- [ ] **P-4** Toast dedupe.
- [ ] **P-5** First-run tour / empty states.
- [ ] **P-6** Optional light theme with contrast gates.
- [ ] **P-7** Performance budgets in CDP.
- [ ] **P-8** Final documentation and evidence.

## Continuous tasks

- [ ] **C-1** Keep `EVIDENCE.md` current.
- [ ] **C-2** Update `IMPLEMENTATION-STATUS.md` every phase.
- [ ] **C-3** Keep `layout_regression` and `cdp_workflow` in sync.
- [ ] **C-4** Run the full gate set before each PR.
- [ ] **C-5** Remove dead fields after each machine migration.
- [ ] **C-6** Re-run the eval/verifier timing guard after backend changes.

## Dependency graph

```text
D -> S -> E -> R -> A/M -> P
S-1 -> S-2 -> S-4/S-5/S-6 -> S-7 -> S-12/S-13
S-5 -> S-9
E-1 -> E-2 -> E-3 -> E-5
E-1 -> E-6
R-1 -> R-3 -> R-5
A-5 depends on M-3
A-7 depends on S-9/S-10
M-1 depends on S-4
M-2 depends on E-2
```

## Parallelization

- Phase 1: `S-8`/`S-10` can run beside `S-4`/`S-6`; `S-14` after `S-12/S-13`.
- Phase 2: `E-6` and `E-7` can run beside `E-2`/`E-3`.
- Phase 3: `R-8`/`R-9` can run beside `R-3`/`R-5`.
- Phase 4: `A-1`/`A-3` can run beside machine migrations.
- Never parallelize edits to `web/app.js` without coordinating; it is the
  shared integration point.
