# Visual audit

Screenshots: `qa/screenshots/01-overview.png` … `06-history.png`.
Captured with headless Chrome at 1440×900 through `qa/screenshots.ps1`.

## What works

- The dark workbench has a clear three-column hierarchy: problems/chats/files on
  the left, the conversation in the middle, evidence and review on the right.
- The stage rail makes progress legible at a glance and marks completed stages.
- The Plan panel reads as a real verification checklist, not decorative chrome.
- The composer carries the one rule that matters: deterministic verification
  gates export.
- The Report panel exposes checks, warnings, tests and the snapshot hash.
- MCP consent is visible as a first-class inspector tab, not hidden in settings.

## Problems found and fixed

| Problem | Fix |
| --- | --- |
| File-tree toggles, folder icons and row actions rendered as literal `?` | Replaced with `▾/▸`, `▣`, extension letters, `+`, `□`, `✎`, `×`; rows are now keyboard-activatable with `role="button"`, `aria-expanded` and Enter/Space. |
| MCP checkboxes were full-width, so “allow” wrapped under each checkbox | Added global checkbox sizing and flex `label.check`; MCP table columns now have fixed widths. |
| `--faint` text was 3.99:1 and primary buttons were 3.63:1 on dark surfaces | `--faint` raised to `#8792a3`, primary background to `#3d55c8`, hover to `#4d66d8`. Axe now reports **0 violations**. |
| Conversation log was scrollable but not focusable | Added `tabindex="0"`, `role="log"` and `aria-label="Conversation"`. |
| MCP tool rows had identical accessible names (“allow”, “Test”) | Added `aria-label="Allow <tool>"` and `aria-label="Probe <tool>"`. |
| Stage separators rendered as `?` | Replaced with escaped `>` text. |
| Sample-test tabs used `?` for both pass and fail | Now `PASS name` / `FAIL name`; text labels satisfy the color-only requirement. |
| Chat-tab close, “Running…”, “resuming…” rendered as `?` | Replaced with `×` and the ellipsis character. |
| Long file path wrapped the file header | `#file-name` shrinks with ellipsis; `#file-meta` stays on one line. |
| The report still showed stale pre-change warnings | Re-verified the package; the report now shows the new checker/memory wording and the spec audit. |

## Remaining suggestions

1. **Folder glyph.** `▣` is legible but reads as a checkbox at 10px. A small
   CSS folder shape (tab + body) would be more immediate than a glyph.
2. **Chat header.** “New chat · 0 messages” is generic. Use the problem name
   plus a state word (“Sum Test · ready”, “Sum Test · 3 unreviewed”).
3. **Report density.** The report table wraps long file paths. A two-line cell
   with the path in monospace and the status as a chip would scan faster.
4. **Stage rail.** Add a tooltip per stage with the exact evidence (test count,
   checker contract, measured limit). The rail currently says “done” without
   saying what proved it.
5. **MCP purpose column.** The purpose text wraps to four lines at 1440px.
   Truncate to two lines with a title attribute, or move the description to a
   tooltip.
6. **Plan panel.** Completed items are green checks but the evidence link is a
   bare filename on the far right. Make it a button that opens the file/report.
7. **Top bar.** “Build answers” and “Limits” are equally weighted with
   “Verify”; a step-number or disabled-until-ready state would clarify order.
8. **Empty state.** The middle pane is mostly blank before the first turn. The
   two sample prompts are good; add a third “load an existing package” action.

## Evidence

```text
qa/accessibility_axe.ps1
  {"violations":[],"passes":20,"incomplete":1}
  {"openInside":true,"label":"Provider settings","liveRegions":2,"closed":true,"focusReturned":true}
  AXE ACCESSIBILITY AUDIT PASSED

qa/cdp_workflow.ps1
  judge0Visible=true, mcpRows=5, mcpToggle=true, mcpSave=true,
  treeGlyphsOk=true, keyboardFocus moves, reflow320=true, console errors none

qa/soak_cdp.ps1
  {"iterations":30,"elapsedMs":213,"growth":82,"errors":[]}
```
