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

## Skill-based audit

Selected **UI UX Pro Max**
(`nextlevelbuilder/ui-ux-pro-max-skill`, MIT, 146,849 stars, pushed
2026-11-07) because it is recent, heavily used and its priority table starts
with accessibility and interaction, not decoration. Supplemented with the
objective gates from **UX/UI Agent Skills**
(`plugin87/ux-ui-agent-skills`, MIT) and the anti-slop review from
**Hallmark** (`Nutlope/hallmark`, MIT). The operating subset is vendored at
[`.opencode/skills/ui-ux-audit/SKILL.md`](../.opencode/skills/ui-ux-audit/SKILL.md).

Queries run against its local database (and applied):

- `"chat scroll composer sticky overflow" --domain ux` → overflow hidden can
  clip content; horizontal overflow is high severity; sticky UI must not
  obscure content.
- `"modal dialog destructive confirmation focus return" --domain ux` →
  confirm destructive actions, visible focus inside dialogs, focus not
  obscured, focus appearance ≥ 2 px / 3:1.
- `"scrollbar visibility scroll affordance" --domain ux` → input affordance and
  horizontal-scroll avoidance.

Those findings match the reproduced measurements: the shell was clipping the
composer and run panel instead of scrolling them, and native dialogs had no
app-level focus/validation contract.

## Reported defects fixed

The four user-reported defects had one root cause and three interaction
causes. They were reproduced with CDP measurements before the fix and are now
covered by `qa/layout_regression.ps1`.

| Defect | Root cause | Fix | Evidence |
|---|---|---|---|
| No chat scrollbar | `.layout` had no row constraint; `.chat-pane` had `min-height: auto; overflow: visible`, so the grid row grew to 6885 px and `.messages` never overflowed. | `grid-template-rows: minmax(0, 1fr)`; `min-height: 0; overflow: hidden` on the three regions; `.messages` is the only scroller with a 12 px thumb and stable gutter. | 60-message chat: messages 547 px, scrollHeight 6580, scrollbar 10 px. |
| Composer disappears in long chats | The same growth pushed the composer to 6769–6929 px in a 900 px viewport. | The grid constraint above. | Composer bottom 886 px; visible. |
| Run panel/custom input missing under a code file | The right inspector grew to 6885 px, so the run panel sat at 6790–6943 px, below the viewport. | The grid constraint above; run panel remains `flex: 0 0 auto`. | `submissions/accepted/ref.cpp`: run panel 747–900 px, stdin 817–885 px. |
| Native prompt/confirm for rename/delete | `window.prompt`/`confirm` bypass the app's design, validation and focus model. | One accessible `actionDialog` with labelled input, inline error, danger styling, focus trap and focus return; every call site replaced. | Rename/delete chat verified end-to-end in the layout regression. |

Also fixed: chat actions were hover-only and chat titles were not keyboard
controls; both now work on focus and expose object-specific labels. Icon-only
context-chip removal is labelled.

The full IDE redesign, Judge0 embedding and phased plan are in
[`UI-UX-REDESIGN.md`](UI-UX-REDESIGN.md). The implicit state-machine inventory
and decision are in [`STATE-MACHINES.md`](STATE-MACHINES.md).

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

qa/accessibility_tree.ps1
  {"buttons":9,"emptyButtons":[],"textboxes":3,"emptyTextboxes":[],
   "names":["combobox=Problem workspace","log=Conversation",
            "button=Verify","textbox=Message the agent",...]}
  ACCESSIBILITY TREE AUDIT PASSED

qa/layout_regression.ps1
  chatScrolls=true, scrollbarPx=10, chatConstrained=true,
  composerVisible=true, runPanelVisible=true, runPanelInViewport=true,
  chatActionLabels=true, dialogOpen=true, dialogLabelled=true,
  dialogFocusInside=true, dialogFocusReturned=true,
  chatRenamed=true, chatDeleted=true
  LAYOUT REGRESSION PASSED

qa/cdp_workflow.ps1
  judge0Visible=true, isolateVisible=true, mcpRows=5, mcpToggle=true,
  mcpSave=true, treeGlyphsOk=true, busyGuard=true, errorShown=true,
  approvalDedupe=true, clarificationVisible=true, xssEscaped=true,
  composerFocusable=true, followPaused=true, hunkRows=1, historyRows=9,
  mentionVisible=true, reflow320=true, keyboard focus moves

qa/soak_cdp.ps1
  {"iterations":30,"elapsedMs":213,"growth":82,"errors":[]}
```
