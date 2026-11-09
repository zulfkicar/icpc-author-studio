# Test plan and quality gates

A phase is done only when every gate for that phase passes and the evidence is
recorded. “Tests pass” without the command output is not evidence.

## 1. Gate philosophy

- **Deterministic first:** every claim has a command that returns pass/fail.
- **Render, don't infer:** layout and focus require a real browser.
- **One primary scroller per region:** assert geometry, not just CSS.
- **State is observable:** assert `data-state-*` and
  `AuthorMachines.snapshot()`, not private variables.
- **No silent skips:** a skipped test is reported as skipped, never counted as
  pass.
- **Flakes are defects:** retry once for diagnosis, then fix the cause.

## 2. Baseline commands

```powershell
# Rebuild the app after source changes
wsl -e sh -c "cd /mnt/e/ICPC/author-agent && docker compose up -d --build author-agent"
```

### Browser / UI

```powershell
& 'C:\Projects\author-agent\qa\layout_regression.ps1'
& 'C:\Projects\author-agent\qa\accessibility_axe.ps1'
& 'C:\Projects\author-agent\qa\accessibility_tree.ps1'
& 'C:\Projects\author-agent\qa\cdp_workflow.ps1'
& 'C:\Projects\author-agent\qa\soak_cdp.ps1'
& 'C:\Projects\author-agent\qa\phase2_editor.ps1'
node 'C:\Projects\author-agent\qa\test_state_machines.mjs'
```

### Container

```powershell
wsl -e docker exec icpc-author-agent python qa/test_ui_contracts.py
wsl -e docker exec icpc-author-agent python qa/test_accessibility.py
wsl -e docker exec icpc-author-agent python qa/test_isolate_worker.py
wsl -e docker exec icpc-author-agent python qa/test_testlib.py
wsl -e docker exec icpc-author-agent python qa/test_interactive.py
wsl -e docker exec icpc-author-agent python qa/test_live_judge0.py
wsl -e docker exec icpc-author-agent python qa/test_executor_limits.py
wsl -e docker exec icpc-author-agent python qa/test_executor_security.py
wsl -e docker exec icpc-author-agent python qa/test_verification_timing.py
```

The heavy timing measurement is explicit:

```powershell
# 86 tests, measure limits + verify, writes qa/verification-timing.json
wsl -e docker exec icpc-author-agent python qa/run_verification_timing.py
```

### Static

```powershell
node --check web/app.js
node --check web/machines.js
python -m py_compile isolate_worker.py server.py verify.py winutil.py
```

## 3. Phase gates

### Phase 0.5 — dialogs

| Gate | Check |
|---|---|
| Open/close | all four dialogs open and close in CDP |
| Cancel button | closes and resolves null/false |
| Escape | closes without submitting |
| Backdrop | closes without submitting |
| Focus return | invoker or composer receives focus |
| Validation | empty/invalid input stays open with `role="alert"` |
| No native dialogs | static lint passes |
| AX tree | dialogs and controls named |

### Phase 1 — shell

| Gate | Check |
|---|---|
| Regions exist | `activity/navigator/editor/agent/status` present |
| Geometry | regions do not overlap; editor width > 0 |
| Scrollers | messages/editor/report scroll independently |
| Composer | visible at 60 messages |
| Run panel | visible under a runnable file |
| Responsive | 1440/1100/768/320, no horizontal overflow |
| Keyboard | Tab reaches every region; rail/tabs arrow keys |
| Landmarks | `nav/main/aside/header/footer` |
| AX tree | no unnamed controls |
| Existing IDs | manifest check |

### Phase 2 — editor

| Gate | Check |
|---|---|
| Monaco | `qa/phase2_editor.ps1`: `engine="monaco"`, `monacoLoaded=true`, host visible |
| Tabs | `tabsAfterSwitch=2`, `activeTab` returns, `Ctrl+Tab` cycle, `Ctrl+W` close |
| View state | `cursorBefore` equals `restoredCursor` |
| Dirty guard | `dialogOpen=true`, Cancel keeps buffer, confirm discards |
| Save | Ctrl+S clears the dirty dot and writes `line two changed` |
| Binary/read-only | `binary=true`, `binaryStaysOut=true` |
| Diff | `diffVisible=true`, `diffModel=true`, inline restores |
| Fallback | `?editor=textarea` → `engine="textarea"`, textarea editable |
| Performance | `loadMs < 2000` |
| Keyboard | file tree `moved=true`, `expanded=true`, `role="tree"` |

### Phase 3 — run/Judge0

| Gate | Check |
|---|---|
| Backends | Isolate/Judge0/Local visibility from settings |
| Per-file state | stdin/backend restore after switch/reload |
| Output | stdout/stderr/compile/result separated |
| Statuses | OK/RE/TO/CE/WA rendered |
| History | last 10; compare previous |
| Cancel | file change aborts in-flight render |
| Security | secret paths blocked; only open file sent |
| Live | Judge0 and Isolate runs pass |
| Timing | 86-test verifier under 15 min; `qa/test_verification_timing.py` guards the recorded artifact |

### Phase 4 — evidence/AX/state

| Gate | Check |
|---|---|
| Report tab | checks/warnings/limits/stale |
| Review queue | unreviewed count, diff, mark reviewed |
| Export | derived predicate; reason exposed |
| Machines | chat/file/verify/changes transitions tested |
| Keyboard map | Ctrl+K, Ctrl+Shift+P, Ctrl+Enter, Ctrl+S, Ctrl+` |
| Focus | not obscured by sticky UI |
| Screen reader | manual checklist signed |
| AX tree | clean |
| Soak | 30 iterations, no growth/errors |

### Phase 5 — polish

| Gate | Check |
|---|---|
| Palette | opens, filters, executes |
| Quick open | opens files |
| Notifications | long job updates, dedupe |
| Onboarding | first-run path |
| Theme | optional; contrast in both |
| Performance | budgets met |

## 4. Browser test matrix

| Width | Height | Purpose |
|---|---|---|
| 1440 | 900 | desktop target |
| 1100 | 800 | drawer breakpoint |
| 768 | 900 | tablet / sheet |
| 320 | 800 | narrow reflow |

For each: screenshot with pointer off the UI, no horizontal scrollbar on the
body, composer/run panel reachable.

## 5. Accessibility checklist

Automated:

- axe 0 serious/critical;
- AX-tree: every interactive node named;
- tabs: `aria-selected`, `aria-controls`;
- dialogs: labelled, described, focus trapped, Escape, focus return;
- live regions: transcript/status/run result;
- reduced motion: no essential animation.

Manual:

- Tab through the full shell in reading order;
- Enter/Space activate every button;
- arrow keys move tabs and tree;
- Escape closes menus/dialogs;
- focus visible in every state;
- 200% zoom / 400% reflow;
- screen reader announces transcript, status, errors and dialog titles;
- no focus hidden behind sticky composer/status bar.

## 6. State-machine tests

For every machine:

1. legal event updates state and visible control;
2. illegal event is a no-op and warns in development;
3. hydration via `set()` does not invent transitions;
4. `snapshot()` is serialisable;
5. `data-state-*` updates;
6. a terminal/error state returns to a recoverable state.

Minimum examples:

```js
turn: idle --START--> streaming --WAIT--> waiting --RESUME--> streaming
editor: view --EDIT--> editing --SAVE--> saving --SAVED--> view
modal: closed --OPEN--> open --CLOSE--> closed
```

## 7. Verifier / backend tests

- `test_isolate_worker.py` — health, C++ accepted, metadata, CE, limits,
  network, read-only root, file-size.
- `test_isolate_contract.py` — isolate sandbox metadata, path blocking,
  read-only root, limits, process cap.
- `test_testlib.py` — checker selftest, reference accepted, wrong rejected,
  interactive transcript.
- `test_interactive.py` — interactive selftest, transcript checker, forged
  transcript rejected.
- `test_executor_limits.py` / `test_executor_security.py` — output flood,
  memory/PID, orphan cleanup, cross-workspace block.
- `test_live_judge0.py` — live Judge0 health and run.
- Timing: 86-test workspace under 15 min (currently 650.8 s).

## 8. Evidence artifacts

```text
docs/plans/ui-ux-ax-rework/EVIDENCE.md
qa/screenshots/01-overview.png
qa/screenshots/02-file-editor.png
qa/screenshots/03-report.png
qa/screenshots/04-diff.png
qa/screenshots/05-mcp.png
qa/screenshots/06-history.png
qa/screenshots/07-chat-scroll.png
qa/screenshots/08-rename-dialog.png
qa/screenshots/09-shell-1440.png
qa/screenshots/10-shell-1100.png
qa/screenshots/11-shell-768.png
qa/screenshots/12-shell-320.png
qa/screenshots/13-shell-320-agent.png
qa/screenshots/14-shell-320-navigator.png
qa/screenshots/15-diff-side-by-side.png
qa/screenshots/16-editor-tabs.png
```

`EVIDENCE.md` entry format:

```markdown
## Phase N — <name>
Date:
Commit:
Commands:
  - command → result
Screenshots:
  - path → what it proves
Manual checks:
  - keyboard → result
Residual risks:
  - ...
```

## 9. Flake and failure policy

- A failing gate blocks the phase.
- Retry a browser test once to distinguish flake from regression.
- A repeated flake is a defect; fix the selector/timing, not the assertion.
- Never delete or weaken a test to get green.
- If a gate cannot run (service unavailable), mark the phase **blocked**, not
  **done**.
- Record the actual output, including failures.

## 10. Requirements-quality checklist

Reviewer-owned; implementation must not self-approve unchecked items.

- [ ] Every P0 user story has an acceptance check.
- [ ] Every acceptance check maps to a command or a screenshot.
- [ ] The five regions and their scrollers are unambiguous.
- [ ] The editor fallback path is specified.
- [ ] Judge0 quick-run vs verifier authority is unambiguous.
- [ ] Secret-test blocking is specified on both client and server.
- [ ] Every destructive action uses the dialog contract.
- [ ] Every state machine has states, events and a terminal/error path.
- [ ] The responsive breakpoints and drawer behavior are specified.
- [ ] The AX contract is testable without reading private variables.
- [ ] Rollback exists for each phase.
- [ ] Out-of-scope items are explicit.

## 11. Convergence

Before declaring the program done:

1. Read the spec and architecture again.
2. Walk every P0 acceptance criterion against `EVIDENCE.md`.
3. Run the full gate set.
4. Open a fresh-context review of the diff against the spec.
5. Fix every Critical/Major finding.
6. Record residual risks and open decisions.
7. Only then mark the program complete.
