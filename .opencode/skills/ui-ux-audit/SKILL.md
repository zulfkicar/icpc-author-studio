---
name: ui-ux-audit
description: Audit and fix an existing web UI with rendered evidence, objective accessibility/layout gates, and a state-machine lens. Use when a UI has layout, scrolling, modal, focus, responsive, or interaction defects, or before shipping a redesign.
version: "1.0"
when_to_use: A UI defect is reported, a redesign is proposed, or a frontend change must be proven in a real browser rather than reviewed from source alone.
---

# UI/UX audit

This is a project-local distillation of two active upstream skills, used with
attribution:

- **UI UX Pro Max** (`nextlevelbuilder/ui-ux-pro-max-skill`, MIT, 146k+ stars,
  pushed 2026-11-07) — priority order: accessibility, touch/interaction,
  performance, style, layout, typography/color, motion, forms, navigation,
  charts. Its anti-patterns (hover-only actions, icon-only buttons without
  labels, hidden overflow clipping content, focus obscured by sticky UI,
  destructive actions without confirmation) are binding here.
- **UX/UI Agent Skills** (`plugin87/ux-ui-agent-skills`, MIT, 3.1k stars) —
  objective gates: axe roles/landmarks, contrast in every state, keyboard,
  target size, reduced motion, no horizontal overflow at 280px, screen economy,
  and the rule "render it and look at it; never critique from source alone".
- **Hallmark** (`Nutlope/hallmark`, MIT, 50k+ stars) — anti-AI-slop review:
  refuse decorative noise, empty frames, one-colour-word headlines, and
  machine-made filler.

The upstream repositories are references, not vendored dependencies. This file
records the subset that applies to this workbench so a future agent does not
have to re-derive it.

## Non-negotiable process

1. **Render before reviewing.** Start the app, open the affected screen at
   1440×900 and 320×800, and take a screenshot with the pointer parked off the
   UI. Source-only reviews are invalid.
2. **Reproduce with numbers.** Measure the element that is wrong
   (`getBoundingClientRect`, `scrollHeight` vs `clientHeight`,
   `offsetWidth - clientWidth`, computed `overflow`/`min-height`). A finding
   must name the element and the measurement.
3. **Fix the cause, not the symptom.** Example: a missing chat scrollbar and a
   disappearing composer were one grid-min-height defect, not two CSS bugs.
4. **Re-run the gates after the fix.** axe, AX tree, keyboard traversal,
   layout regression, and the project's own UI contracts.
5. **State the scope.** These gates prove objective correctness; they do not
   prove taste. Do not claim an aesthetic score from automated output.

## Gate set

### Layout and scroll

- No horizontal overflow at 280/320/768/1440.
- App shells use `min-height: 0` on flex/grid items that contain a scroller,
  and `grid-template-rows: minmax(0, 1fr)` on the workbench grid.
- The primary scroll region is reachable with a visible scrollbar
  (≥ 8px webkit thumb, `scrollbar-width: thin` in Firefox, non-transparent
  thumb, `scrollbar-gutter: stable` where content shifts matter).
- Sticky headers/footers never cover focused content (WCAG 2.4.11).
- The composer/input must be in the viewport in every conversation length;
  the run/stdin panel must be in the viewport under every runnable file.

### Accessibility

- axe: 0 serious/critical violations.
- Accessibility tree: every `button`, `textbox`, `combobox`, `tab` and `dialog`
  has a non-empty name; the conversation log is named; icons are `aria-hidden`.
- Keyboard: Tab reaches every control in reading order; Enter/Space activates;
  Escape closes overlays; focus returns to the invoker.
- Focus visible: ≥ 2px indicator with ≥ 3:1 contrast against adjacent colours.
- Target size: ≥ 24×24 CSS px on desktop; expand to 44×44 on coarse pointers.
- Contrast: 4.5:1 body text, 3:1 large text/UI; measure computed styles, do not
  eyeball.
- No colour-only status; pair status colour with text or an icon.
- Respect `prefers-reduced-motion`.

### Interaction and state

- No native `window.prompt`/`window.confirm`; use an app dialog with a title,
  description, labelled input, inline error, destructive styling, focus trap
  and focus return.
- Actions that depend on hidden hover are also revealed on `:focus-within` and
  on the active row.
- Destructive actions name the object and the consequence ("Delete chat? The
  transcript will be removed. This cannot be undone.").
- Busy states disable the control that started the work and explain what is
  happening; a failed async action returns to an editable state.
- Every implicit boolean/nullable pair is either derived from one state machine
  or documented in `docs/STATE-MACHINES.md`.

### Visual quality

- One accent, one success, one warning, one danger colour; no raw hex in
  component code when a token exists.
- Type scale has a clear body size; code uses a mono stack; labels are not
  dependent on letter-spaced all-caps at < 10px.
- Borders and one elevation level, not stacked shadows; no decorative gradient
  that competes with evidence tables.
- Empty states say what to do next; errors say what failed and how to recover.

## Workbench-specific acceptance

- Chat: transcript scrolls, scrollbar visible, composer always visible,
  "Follow live" appears only when the user scrolls away.
- Files: tree row is keyboard-activatable; opening a runnable file always shows
  the run panel, stdin, and every configured backend button.
- Run: Judge0/Isolate/local are labelled; quick-run is visibly not the
  verification authority; output/stderr/compile output are separable.
- Modals: new problem, settings, context and every rename/delete/restore flow
  use the same dialog grammar.
- Evidence: verification status, stale state and export gate are readable
  without opening a modal.

## Output format

```text
Verdict: pass | pass with findings | fail
Rendered: 1440×900, 320×800, dark, pointer off UI
Gates: axe 0 | AX tree 0 unnamed | keyboard pass | reflow pass | layout pass

Findings
# | Severity | Element | Measurement/evidence | Fix

Scope: automated gates prove objective correctness; taste is human review.
```
