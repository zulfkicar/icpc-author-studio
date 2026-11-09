# Evidence

Actual commands, outputs, screenshots and manual checks. Do not paste a green
summary without the command that produced it.

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

Date:
Commit:
Commands:
- `...` → `...`
Screenshots:
- `...` → what it proves
Manual checks:
- Cancel/Escape/backdrop → result
- Focus return → result
Residual risks:
- ...

---

## Phase 1 — five-region shell

Date:
Commit:
Commands:
- `...` → `...`
Screenshots:
- `qa/screenshots/09-shell-1440.png` → ...
- `qa/screenshots/10-shell-1100.png` → ...
- `qa/screenshots/11-shell-768.png` → ...
- `qa/screenshots/12-shell-320.png` → ...
Manual checks:
- keyboard → result
- reflow → result
Residual risks:
- ...

---

## Phase 2 — editor

Date:
Commit:
Commands:
- `...` → `...`
Screenshots:
- `...`
Manual checks:
- dirty tab switch → result
- Monaco failure fallback → result
Residual risks:
- ...

---

## Phase 3 — run/Judge0

Date:
Commit:
Commands:
- `...` → `...`
Screenshots:
- `...`
Manual checks:
- Isolate/Judge0/Local → result
- secret guard → result
- timing → result
Residual risks:
- ...

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
