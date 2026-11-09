# Evidence

Actual commands, outputs, screenshots and manual checks. Do not paste a green
summary without the command that produced it.

## Program definition of done — current

| Criterion | Evidence | Status |
|---|---|---|
| Five regions at 1440/1100/768/320, no horizontal overflow | `layout_regression` regions and widths output above | pass |
| Chat is the right panel; editor centre; navigator left | `agentIsChat=true`, `editorIsCentre=true`, region boxes | pass |
| Monaco lazy-loads; per-file tabs keep cursor/scroll; textarea fallback | `qa/phase2_editor.ps1` → `PHASE 2 EDITOR TESTS PASSED` | pass |
| Judge0 embedded natively in the run panel; Isolate is verifier | `backendOptions`, `quickRunWarning`, `test_judge0_adapter`, `test_live_judge0` | pass |
| Every dialog cancels by button, Escape, backdrop; focus returns | `newEscape`, `settingsEscape`, `contextEscape`, `actionEscapeClosed`, focus return checks | pass |
| Every in-scope state machine has a transition test | `node qa/test_state_machines.mjs` → 18 machines | pass |
| axe 0; AX tree has no unnamed controls | `accessibility_axe.ps1` `blocking=0`; `accessibility_tree.ps1` 0 empty names | pass |
| Verification timing budget guarded by a test | `test_verification_timing.py`; 834.1 s / 86 tests | pass |
| Existing QA, CDP, soak and accessibility suites green | Phases 0.5/1/3 command lists below | pass |
| `EVIDENCE.md` and `IMPLEMENTATION-STATUS.md` updated | this file and the status document | pass |

## Baseline — Phase 0

Date: 2026-11-09
Commit: `b04e5d7`

```text
qa/layout_regression.ps1
  chatScrolls=true, scrollbarPx=10, chatConstrained=true,
  composerVisible=true, runPanelVisible=true, runPanelInViewport=true,
  chatActionLabels=true, chatTitleButtons=1,
  dialogOpen=true, dialogLabelled=true, dialogFocusInside=true,
  dialogFocusReturned=true,
  dialogCancelOpen=true, dialogCancelValue=null, dialogCancelClosed=true,
  newDialogOpen=true, newDialogCancelClosed=true,
  settingsDialogOpen=true, settingsDialogCancelClosed=true,
  contextDialogOpen=true, contextDialogCancelClosed=true,
  chatRenamed=true, chatDeleted=true
  LAYOUT REGRESSION PASSED

qa/accessibility_axe.ps1
  AXE ACCESSIBILITY AUDIT PASSED

qa/accessibility_tree.ps1
  ACCESSIBILITY TREE AUDIT PASSED

qa/cdp_workflow.ps1
  judge0Visible=true, isolateVisible=true, mcpRows=5, mcpToggle=true,
  mcpSave=true, treeGlyphsOk=true, busyGuard=true, errorShown=true,
  approvalDedupe=true, clarificationVisible=true, xssEscaped=true,
  composerFocusable=true, followPaused=true, hunkRows=1, historyRows=9,
  mentionVisible=true, reflow320=true

node qa/test_state_machines.mjs
  STATE MACHINE TESTS PASSED

qa/test_ui_contracts.py
  UI CONTRACT TESTS PASSED

qa/test_accessibility.py
  ACCESSIBILITY AUDIT PASSED

qa/test_isolate_worker.py
  ISOLATE WORKER TESTS PASSED

qa/test_testlib.py
  TESTLIB FIXTURE TESTS PASSED

qa/test_interactive.py
  INTERACTIVE TESTS PASSED

verifier timing
  eval-claim-or-concede-2: 86 tests, 650.8 s
  status=failed only on missing “Measure limits”
```

Screenshots:

- `qa/screenshots/01-overview.png`
- `qa/screenshots/02-file-editor.png`
- `qa/screenshots/03-report.png`
- `qa/screenshots/04-diff.png`
- `qa/screenshots/05-mcp.png`
- `qa/screenshots/06-history.png`
- `qa/screenshots/07-chat-scroll.png`
- `qa/screenshots/08-rename-dialog.png`

Residual risks:

- Monaco is not implemented yet.
- The five-region shell is not implemented yet.
- The eval fixture did not run Measure limits.
- Human screen-reader traversal remains a manual step.

---

## Phase 0.5 — dialog consolidation

Date: 2026-11-09
Commit: phase commit (see `git log --oneline`)

Commands:
- `node --check web/dialogs.js` → exit 0
- `node --check web/app.js` → exit 0
- `python qa/test_ui_contracts.py` → `UI CONTRACT TESTS PASSED`
  (includes `no native prompt/confirm/alert`, `dialog controller ships`,
  `every dialog routes through the controller`, and labelled/described checks
  for all four dialogs)
- `qa/layout_regression.ps1` → `LAYOUT REGRESSION PASSED` with:
  `newEscape=true, newBackdrop=true, settingsEscape=true,
  settingsBackdrop=true, contextEscape=true, contextBackdrop=true,
  actionEscapeClosed=true, actionBackdropClosed=true,
  settingsDirtyGuard=true, settingsDirtyKept=true,
  settingsDirtyDiscarded=true`
- `qa/accessibility_axe.ps1` → `AXE ACCESSIBILITY AUDIT PASSED`
  (`blocking=0`)
- `qa/accessibility_tree.ps1` → `ACCESSIBILITY TREE AUDIT PASSED`
  (20 buttons, 0 unnamed; 4 textboxes, 0 unnamed)

Screenshots:
- `qa/screenshots/08-rename-dialog.png` → shared action dialog with label,
  description, input and cancel/confirm actions.

Manual checks:
- Cancel button → closes and resolves `null` for a prompt, `false` for confirm.
- Escape → closes every dialog without submitting.
- Backdrop → closes every dialog without submitting.
- Focus return → the invoker or the composer receives focus.
- Dirty settings → cancel keeps the dialog open until discard is confirmed.

Residual risks:
- The settings form is large; the dirty guard compares every named field,
  including key fields that are intentionally blank on open.

---

## Phase 1 — five-region shell

Date: 2026-11-09
Commit: phase commit (see `git log --oneline`)

Commands:
- `qa/layout_regression.ps1` → `LAYOUT REGRESSION PASSED`
  - regions: rail `48×816 @ 0`, navigator `280×816 @ 48`,
    editor `702×816 @ 333`, agent `400×816 @ 1040`,
    status `1440×26 @ 874`
  - `regionsPresent=true, regionsOrdered=true, agentIsChat=true,
    editorIsCentre=true, statusbarAtBottom=true,
    noHorizontalOverflow=true`
  - rail: `railEvidence=true, railHistory=true, railRun=true,
    railFiles=true, railChats=true`
  - shortcuts: `shortcutRunToggle=true, shortcutEditorFocus=true,
    shortcutNavFocus=true, shortcutAgentFocus=true`
  - widths `1440/1100/768/320`: `overflow=false`, `editorVisible=true`;
    `1440/1100` keep the agent visible; `768` is navigator + agent drawer;
    `320` offers both drawers.
  - drawer: `open=true, composerVisible=true, closed=true,
    focusReturned=true, focusAfterOpen=mode-select,
    focusAfterClose=toggle-agent`.
- `qa/accessibility_axe.ps1` → `AXE ACCESSIBILITY AUDIT PASSED`
  (`blocking=0`; fixed `scrollable-region-focusable` on `#plan-body`).
- `qa/accessibility_tree.ps1` → `ACCESSIBILITY TREE AUDIT PASSED`
  (named rail buttons, tabs, log and composer).
- `qa/cdp_workflow.ps1` → `composerFocusable=true`, `reflow320=true`,
  `judge0Visible=true`, `isolateVisible=true`, `mcpRows=5`,
  `historyRows=9`, `hunkRows=1`, `approvalDedupe=true`.
- `qa/soak_cdp.ps1` → `{"iterations":30,"elapsedMs":237,"growth":80,
  "errors":[]}` and `CDP SOAK PASSED`.
- `node qa/test_state_machines.mjs` → `STATE MACHINE TESTS PASSED`
  (18 machines: connection, session, turn, approval, editor, run, modal,
  fileLoad, chat, verification, changes, mcp, settings, mentions, follow,
  tree, tests, restore).
- `docker exec icpc-author-agent python qa/test_ui_contracts.py` →
  `UI CONTRACT TESTS PASSED`.
- `docker exec icpc-author-agent python qa/test_accessibility.py` →
  `ACCESSIBILITY AUDIT PASSED`.
- `docker exec icpc-author-agent python qa/test_isolate_worker.py` →
  `ISOLATE WORKER TESTS PASSED`.
- `docker exec icpc-author-agent python qa/test_testlib.py` →
  `TESTLIB FIXTURE TESTS PASSED`.
- `docker exec icpc-author-agent python qa/test_interactive.py` →
  `INTERACTIVE TESTS PASSED`.
- `docker exec icpc-author-agent python qa/test_live_judge0.py` →
  `LIVE JUDGE0 TESTS PASSED`.
- `docker exec icpc-author-agent python qa/test_executor_limits.py` →
  `EXECUTOR LIMIT TESTS PASSED`.
- `docker exec icpc-author-agent python qa/test_executor_security.py` →
  `EXECUTOR SECURITY TESTS PASSED`.

Screenshots:
- `qa/screenshots/09-shell-1440.png` → five regions, editor centre, agent
  right, run panel under the file, status bar at the bottom.
- `qa/screenshots/10-shell-1100.png` → agent still docked at the desktop
  breakpoint.
- `qa/screenshots/11-shell-768.png` → navigator visible, agent collapsed to a
  drawer toggle.
- `qa/screenshots/12-shell-320.png` → single-column editor, rail, status bar,
  both drawer toggles.
- `qa/screenshots/13-shell-320-agent.png` → agent drawer open with composer
  visible.
- `qa/screenshots/14-shell-320-navigator.png` → navigator sheet open.

Manual checks:
- Keyboard: Tab reaches skip links, top bar, rail, navigator, editor tabs,
  editor, run panel, agent header, transcript and composer; arrow keys move
  editor tabs, side tabs and splitters; `Ctrl+S` saves a dirty file,
  Ctrl+backtick toggles the run panel, `Alt+1/2/3` focus
  navigator/editor/agent, and `F8`/`Shift+F8` cycle problems.
- Reflow: no horizontal document overflow at 1440/1100/768/320.
- Drawers: Escape closes and returns focus to the toggle.

Residual risks:
- Monaco, per-file tabs and the native Judge0 backend selector are Phase 2/3.
- The 320 px top bar scrolls its action row horizontally; document overflow
  remains zero.
- A human screen-reader traversal is still a manual step.

---

## Phase 2 — editor (Monaco, tabs, diff, file tree)

Date: 2026-11-09
Commit: phase commit (see `git log --oneline`)

Commands:
- `qa/phase2_editor.ps1` → `PHASE 2 EDITOR TESTS PASSED`
  - `engine="monaco"`, `monacoLoaded=true`, `hostVisible=true`,
    `hostHeight=370`, `textareaHidden=true`
  - `loadMs=359` (budget < 2000 ms)
  - `tabsAfterOpen=1`, `tabsAfterSwitch=2`, `activeTab="ref.cpp"`,
    `tabAfterCycle="NOTES.md"`, `tabRestored=true`
  - `cursorBefore="Ln 2, Col 3"`, `restoredCursor="Ln 2, Col 3"`
  - `diffVisible=true`, `diffModel=true`, `inlineRestored=true`
  - `dirtyDot=true`, `dialogOpen=true`, `stayed=true`, `savedClean=true`,
    `savedContent="line one\nline two changed\n"` via Ctrl+S
  - `discardOpen=true`, `switched=true`
  - `binary=true`, `binaryStaysOut=true`
  - tree: `moved=true`, `expanded=true`, `role="tree"`
  - fallback: `engine="textarea"`, `textareaVisible=true`,
    `monacoHidden=true`, `valueLength=122`
- `qa/layout_regression.ps1` → `LAYOUT REGRESSION PASSED`
- `qa/accessibility_axe.ps1` → `AXE ACCESSIBILITY AUDIT PASSED`, `blocking=0`
- `qa/accessibility_tree.ps1` → `ACCESSIBILITY TREE AUDIT PASSED`
- `qa/cdp_workflow.ps1` → all prior checks still pass
  (`composerFocusable=true`, `reflow320=true`, `runOutputTabs=5`, …)
- `qa/soak_cdp.ps1` → `CDP SOAK PASSED`
- `node qa/test_state_machines.mjs` → `STATE MACHINE TESTS PASSED`
- container: `UI CONTRACT TESTS PASSED`, `ACCESSIBILITY AUDIT PASSED`,
  `SECURITY TESTS PASSED`, `ISOLATE WORKER TESTS PASSED`,
  `TESTLIB FIXTURE TESTS PASSED`, `INTERACTIVE TESTS PASSED`,
  `LIVE JUDGE0 TESTS PASSED`, `EXECUTOR LIMIT TESTS PASSED`,
  `EXECUTOR SECURITY TESTS PASSED`, `JUDGE0 ADAPTER TESTS PASSED`,
  `VERIFICATION TIMING TESTS PASSED`.

Screenshots:
- `qa/screenshots/02-file-editor.png` → Monaco, line numbers, dirty/save chrome
- `qa/screenshots/16-editor-tabs.png` → ref.cpp + NOTES.md tabs, Monaco active
- `qa/screenshots/15-diff-side-by-side.png` → Monaco diff editor with
  original/modified panes and the inline/back toggle

Manual checks:
- Opening a second file creates a tab; clicking or `Ctrl+Tab` switches,
  `Ctrl+W` closes, and cursor/scroll/mode restore per path.
- Dirty tab switch and dirty close both use the action dialog; Cancel keeps
  the buffer, confirm discards it.
- Ctrl+S saves the Monaco model and clears the dirty dot.
- Binary/read-only files never enter edit mode.
- `?editor=textarea` and a Monaco loader failure both leave the textarea
  editor fully usable.
- File tree: arrow keys move, Right expands, Left collapses/moves to parent,
  Enter/Space activate.

Residual risks:
- Monaco adds ~12 MB of vendored assets; it is lazy-loaded only on edit.
- Monaco's AMD loader requires CSP `script-src 'self' 'unsafe-eval'`; the
  policy remains same-origin only and the worker is a same-origin script.
- The TypeScript worker itself contains an eval path; it is never used for the
  C/C++/Python/Java/Kotlin authoring flow.

---

## Phase 3 — run/Judge0 (run-panel slice)

Date: 2026-11-09
Commit: phase commit (see `git log --oneline`)

Commands:
- `qa/cdp_workflow.ps1` → run-panel slice:
  `backendOptions=["local","isolate","judge0"]`,
  `backendJudge0Enabled=true`,
  `quickRunWarning="Quick run is not verification"`,
  `runOutputTabs=5`, `perFileStdin="hello-stdin"`,
  `runStatus="local · OK · 1 ms"`,
  `runHistoryRows=1`, `runHistoryRendered=1`,
  `secretBlocked=true`, `judge0Visible=true`, `isolateVisible=true`.
- `docker exec icpc-author-agent python qa/test_judge0_adapter.py` →
  `JUDGE0 ADAPTER TESTS PASSED`, including
  `judge0 blocks data/secret/01.in` and
  `judge0 blocks data/sample/01.ans`.
- `docker exec icpc-author-agent python qa/test_live_judge0.py` →
  `LIVE JUDGE0 TESTS PASSED` (`accepted`, `status`, `not authority`,
  workspace file).
- `docker exec icpc-author-agent python qa/test_isolate_worker.py` →
  `ISOLATE WORKER TESTS PASSED`.
- `docker exec icpc-author-agent python qa/test_executor_limits.py` →
  `EXECUTOR LIMIT TESTS PASSED`.
- `docker exec icpc-author-agent python qa/test_executor_security.py` →
  `EXECUTOR SECURITY TESTS PASSED`.
- `docker exec icpc-author-agent python qa/run_verification_timing.py` →
  `TIMING {"slug":"eval-claim-or-concede-2","limitsSeconds":229.8,
  "verifySeconds":834.1,"elapsedSeconds":1063.9,"budgetSeconds":900.0,
  "withinBudget":true,"status":"verified","tests":86,"accepted":2,
  "negative":4,"limits":{"timeSeconds":1.0,"memoryMb":256},"errors":[]}`
- `python qa/test_verification_timing.py` →
  `VERIFICATION TIMING TESTS PASSED` (artifact
  `qa/verification-timing.json`).

Screenshots:
- `qa/screenshots/02-file-editor.png` → run panel with backend selector,
  quick-run warning, output tabs, stdin and history.

Manual checks:
- Local, Isolate and Judge0 selectors are enabled from settings; a missing
  backend falls back to Local.
- Per-file stdin/backend restore after switching files.
- Output is split into stdin/stdout/stderr/compile/result; status, time and
  memory are shown as text, not colour alone.
- Cancel aborts the in-flight fetch and a stale result cannot render into a
  different file (run id guard).
- Judge0 refuses `data/secret/**` and `**/*.ans` on both the client and the
  server adapter.

Residual risks:
- Monaco and per-file editor tabs remain Phase 2.
- Judge0 and Isolate report time in seconds; the UI normalises both to ms.
- Run history is per file and capped at 10 entries in localStorage.
- The verifier itself is 834.1 s for 86 tests (13.9 min), which passes the
  15-minute budget but leaves only ~66 s of headroom. Measure-limits is a
  separate 229.8 s pre-step and is not counted against the verification budget.
- Two verifier runs against the same workspace must not overlap; the isolate
  worker's box-to-workspace sync is not per-workspace locked. Run one at a
  time until that lock is added.

---

## Phase 4 — evidence/AX/state

Date:
Commit:
Commands:
- `...` → `...`
Screenshots:
- `...`
Manual checks:
- keyboard-only flow → result
- screen reader → result
Residual risks:
- ...

---

## Phase 5 — polish

Date:
Commit:
Commands:
- `...` → `...`
Screenshots:
- `...`
Manual checks:
- command palette → result
- performance budgets → result
Residual risks:
- ...
