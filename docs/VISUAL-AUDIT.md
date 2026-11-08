# Visual audit and redesign

Screenshots: `qa/screenshots/01-overview.png` … `06-history.png`, captured at
1440×900 with headless Chrome through `qa/screenshots.ps1`.

## Design direction

The workbench was rebuilt around one question: *what is the evidence right now?*
The new shell separates four jobs:

1. **Problem** — workspace name, verification state and the section rail.
2. **Conversation** — the agent's work, with a stage stepper and an elevated
   composer.
3. **Evidence** — plan, file, report, diff, history and MCP in one inspector.
4. **Action** — Build answers, Limits, Verify, Export and backend quick-runs.

The visual language is a deep, slightly blue-black workbench with a single
indigo accent, emerald success, amber warning and rose failure. Surfaces use
one-pixel borders and very low-contrast gradients instead of heavy shadows, so
long evidence tables stay readable.

## What changed

- **New shell.** A 58px top bar with a brand block, labeled workspace switcher,
  status pill and action group. The left sidebar has a vertical section rail and
  a dedicated problem card. The right inspector has its own header and tab bar.
- **Stage stepper.** Compact numbered chips with connectors replace the old
  pill strip; completed stages are emerald, future stages are neutral.
- **Conversation.** The empty state is a deliberate landing panel, not a blank
  box. Messages have a clear user/assistant hierarchy; the composer is an
  elevated card with context chips, a focus ring and a prominent Send.
- **Inspector.** Plan, File, Report, Diff, History and MCP are first-class tabs.
  The report uses chips, tables and a warnings block. MCP tools are cards with
  name, purpose, per-tool argument input, consent and probe.
- **File/editor.** The file header ellipsizes long paths, the editor keeps its
  gutter and status bar, and the Run panel has Load sample, Run tests, Judge0,
  Isolate and Run.
- **Dialogs.** New/Provider/Context dialogs share a kicker, heading and action
  row; the provider dialog now includes Judge0 and Isolate URLs.
- **Accessibility.** Axe-core reports **0 violations**; 24px targets, focus
  rings, `aria-live` status, `role="log"` conversation, dialog labels and
  reduced-motion support are in place.
- **MCP default.** A fresh workspace is enabled with every read-only tool and
  `.` root, so relative paths work immediately. Secret tests and `.ans` files
  remain blocked.

## Remaining suggestions

1. **Report density.** Long file paths wrap; a two-line cell with a monospace
   path and a status chip would scan faster.
2. **Plan evidence links.** The filename on the right should open the file or
   report directly.
3. **Top bar order.** Build answers and Limits are peers of Verify; a numbered
   pipeline or disabled-until-ready state would clarify the order.
4. **Empty state.** Add a third action: “open an existing package”.

Implemented since the first pass: CSS folder shapes, a problem-name chat header
with “Start a conversation”, stage tooltips with evidence state, two-line MCP
purpose clamping, and a cleaner run toolbar.

## Evidence

```text
qa/accessibility_axe.ps1
  {"violations":[],"passes":20,"incomplete":1}
  {"openInside":true,"label":"Provider settings","liveRegions":2,
   "closed":true,"focusReturned":true}
  AXE ACCESSIBILITY AUDIT PASSED

qa/cdp_workflow.ps1
  judge0Visible=true, isolateVisible=true, mcpRows=5, mcpToggle=true,
  mcpSave=true, treeGlyphsOk=true, busyGuard=true, errorShown=true,
  approvalDedupe=true, clarificationVisible=true, xssEscaped=true,
  composerFocusable=true, followPaused=true, hunkRows=1, historyRows=9,
  mentionVisible=true, reflow320=true, keyboard focus moves

qa/soak_cdp.ps1
  {"iterations":30,"elapsedMs":213,"growth":82,"errors":[]}
```
