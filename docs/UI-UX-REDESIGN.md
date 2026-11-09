# Workbench UI/UX/AX redesign

Status: Phases 0.5 (dialog controller), 1 (five-region shell), 2 (Monaco,
per-file tabs, Monaco diff, file-tree keyboard), 3 (run panel), 4
(evidence/review/state/AX) and 5 (notifications, toast dedupe, onboarding,
optional light theme, performance budgets) are implemented and gate-tested,
except the manual screen-reader sign-off. The four reported defects are fixed
and covered by a browser regression test; the full IDE rework is phased below.
Companion documents: [`VISUAL-AUDIT.md`](VISUAL-AUDIT.md),
[`STATE-MACHINES.md`](STATE-MACHINES.md),
[`IMPLEMENTATION-STATUS.md`](IMPLEMENTATION-STATUS.md).
Execution package (constitution, spec, architecture, tasks, test plan,
rollout, research, goal prompt): [`plans/ui-ux-ax-rework/README.md`](plans/ui-ux-ax-rework/README.md).

## 1. Executive decision

Keep the current evidence-first workbench, but replace the three-column
"chat + inspector" shell with a **five-region IDE**:

1. a narrow activity rail,
2. a navigator (chats, files, changes),
3. an editor group with tabs, breadcrumbs and a bottom run panel,
4. a persistent agent panel on the right (Cline-like), and
5. a status bar for backend health, limits, cursor and verification.

Judge0 stays a **quick-run backend**, never the verification authority. Its IDE
pattern is embedded natively in the editor's run panel rather than iframed: the
same Monaco-grade editing surface, language selector, stdin/stdout/compile
output, status and limits, but sharing the workspace, file model and agent
context. The deterministic verifier remains Isolate-backed.

The UI state layer becomes explicit, small and observable. It is already
started in `web/machines.js`; migration is additive so no current behaviour is
dropped.

## 2. What the audit found (and fixed)

The selected skill was **UI UX Pro Max**
(`nextlevelbuilder/ui-ux-pro-max-skill`, MIT, 146,849 stars, pushed
2026-11-07), applied through its priority gates, with the objective gates from
**UX/UI Agent Skills** (`plugin87/ux-ui-agent-skills`, MIT) and the anti-slop
lens from **Hallmark** (`Nutlope/hallmark`, MIT). A project-local copy of the
operating instructions is in
[`.opencode/skills/ui-ux-audit/SKILL.md`](../.opencode/skills/ui-ux-audit/SKILL.md).

### Defect 1 + 2: no chat scrollbar, composer disappears

**Root cause:** `.layout` was a grid with `grid-template-columns` but no row
constraint. `.chat-pane` had `min-height: auto` and `overflow: visible`, so a
long transcript grew the grid row to the transcript height instead of scrolling
inside it.

Measured before the fix at 1440×900 with 60 messages:

```text
chatPane height 6885 px, bottom 6943 px
messages height 6590 px, scrollHeight == clientHeight, scrollbar 0 px
composer top 6769 px, bottom 6929 px  (viewport is 900 px)
```

**Fix:** `grid-template-rows: minmax(0, 1fr)` on `.layout`; `min-height: 0;
overflow: hidden` on `.left`, `.chat-pane`, `.right`; `.messages` is the only
vertical scroller, with a 12 px visible thumb, `scrollbar-gutter: stable`,
`overscroll-behavior: contain` and a Firefox `scrollbar-color`.

Measured after:

```text
chatPane 842 px, messages 547 px, scrollHeight 6580, scrollbar 10 px
composer bottom 886 px (inside 900 px)
```

### Defect 3: run panel and custom input missing under a code file

**Root cause:** the same unconstrained grid row. The `.right` inspector grew to
6885 px, so `#panel-file` measured 6789 px and the run panel sat at 6790–6943
px, below the viewport. It was not a `hidden` or language-detection bug.

**Fix:** the grid constraint above; the run panel is `flex: 0 0 auto` inside a
now-bounded panel. Measured after: run panel 747–900 px, stdin 817–885 px,
visible for `submissions/accepted/ref.cpp`.

### Defect 4: native prompt/confirm for rename/delete and other actions

**Root cause:** `window.prompt`/`window.confirm` bypass the app's design,
focus, validation and accessibility model, and cannot name the object or the
consequence consistently.

**Fix:** a single accessible `<dialog id="action-dialog">` plus
`actionDialog({...})`. It provides:

- `aria-labelledby`/`aria-describedby`, an inline `role="alert"` error;
- a labelled input for rename/new-file flows;
- destructive styling for delete/discard/restore;
- native focus trap and Escape, plus explicit focus return to the invoker;
- promise results (`string | null` for prompts, `boolean` for confirms).

Every native prompt/confirm site is replaced: new file/folder, rename
file/folder, delete file/folder, discard edits (view and file switch), revert
unreviewed, rename chat, delete chat, restore checkpoint, restore snapshot.

### Extra findings fixed in the same pass

- Chat actions were hover-only. They now appear on hover, `:focus-within` and
  the active row, with object-specific `aria-label`s.
- Chat titles were `div`s with a click handler. They are now real buttons, so
  keyboard users can open a conversation and `aria-current` exposes the active
  one.
- Icon-only context-chip removal had no accessible name; it now names the file.
- Scrollbar thumbs globally were too low-contrast; they are now visible.

**Evidence:** `qa/layout_regression.ps1` asserts chat scrolling, a non-zero
scrollbar, composer visibility, run-panel/stdin visibility, dialog labelling,
focus containment/return, chat rename/delete through the dialog, and the state
machine snapshot. It passes; axe, AX-tree, UI contracts and the CDP workflow
also pass.

## 3. Research

| Project | Stars | License | Pushed | Pattern worth borrowing |
|---|---:|---|---|---|
| [microsoft/vscode](https://github.com/microsoft/vscode) | 195,192 | MIT | 2026-11-08 | Activity bar → sidebar → editor group → panel → status bar; command palette; tabs and breadcrumbs; diff editors; problems panel. |
| [coder/code-server](https://github.com/coder/code-server) | 79,790 | MIT | 2026-11-07 | VS Code's workbench in a browser; proves the full layout works over HTTP with a remote workspace. |
| [cline/cline](https://github.com/cline/cline) | 71,465 | Apache-2.0 | 2026-11-07 | Persistent chat webview (`App.tsx` keeps `ChatView` mounted), flex column with one scrolling message area, sticky composer, context mentions, approval/ask cards, checkpoints, mode toggle, pending-response confirmation. |
| [microsoft/monaco-editor](https://github.com/microsoft/monaco-editor) | 46,961 | MIT | 2026-11-08 | Browser editor, models per file, diff editor, workers; the same engine VS Code uses. |
| [gitpod-io/gitpod](https://github.com/gitpod-io/gitpod) | 13,798 | AGPL | 2026-11-08 | Workspace lifecycle and "open in IDE" handoff; useful for the run/workspace states, not for copying code. |
| [stackblitz/core](https://github.com/stackblitz/core) | 10,891 | MIT | 2024-06-09 | In-browser dev environment UX; older but a useful reference for first-run and file-tree density. |
| [codemirror/dev](https://github.com/codemirror/dev) | 7,807 | MIT | 2026-04-15 | Lighter editor alternative if Monaco's bundle/worker cost is rejected. |
| [judge0/ide](https://github.com/judge0/ide) | 1,127 | MIT | 2026-01-15 | The exact quick-run pattern: Monaco 0.44, GoldenLayout resizable panes, language/compiler options, stdin/stdout panes, Run, status line, theme toggle. |
| [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | 146,849 | MIT | 2026-11-07 | Priority gates: accessibility, interaction, layout, typography/color, motion, forms, navigation. |
| [plugin87/ux-ui-agent-skills](https://github.com/plugin87/ux-ui-agent-skills) | 3,136 | MIT | 2026-10-27 | 52 objective gates, 34 browser gates: axe roles, contrast in every state, keyboard, target size, reduced motion, no horizontal overflow at 280. |
| [Nutlope/hallmark](https://github.com/Nutlope/hallmark) | 50,814 | MIT | 2026-11-05 | Anti-AI-slop audit: no decorative filler, no empty frames, no machine-made hero patterns. |

What to borrow, specifically:

- **VS Code:** the five-region skeleton, one primary scroll per region, tabs
  with a dirty dot, breadcrumbs, a bottom panel that can become a full editor
  tab, and a status bar that is information, not navigation.
- **Cline:** the agent panel is persistent and never remounted; one flex column
  with `overflow-hidden`; the transcript is the only scroller; the composer is
  sticky and keeps drafts; approvals and clarifications are inline cards, not
  modal interruptions; context mentions are chips with explicit removal.
- **Judge0 IDE:** the run surface is part of the editor, not a separate page:
  language, compiler options, stdin, stdout/stderr, Run, status, limits. Its
  GoldenLayout panes are a warning as much as an inspiration: do not let users
  create arbitrary layouts that break the evidence flow.
- **Monaco/CodeMirror:** use a real editor model for multi-file tabs and diffs.
  Recommendation: lazy-load Monaco from a vendored AMD build, like Judge0,
  with the current textarea/highlight.js as the fallback. Revisit CodeMirror 6
  if bundle size or worker CSP becomes a blocker.

What not to copy:

- Cline's full settings/history view stack as full-screen takeovers; in this
  product evidence should stay beside the code.
- Judge0 IDE's iframe/embed route as the primary integration; it duplicates the
  editor and cannot share the workspace model.
- VS Code's full activity-bar surface area; this is a focused authoring tool,
  not a general IDE.

## 4. Product model

The workbench has four jobs, and the layout should make them obvious:

1. **Decide what to write** — the problem idea, plan and conversation.
2. **Write and run** — files, editor, quick runs, sample tests.
3. **Prove it** — deterministic verification, limits, review, stale state.
4. **Ship it** — export only when verified and reviewed.

The redesign keeps the current evidence-first identity: verification is always
visible, and the agent never approves its own work.

## 5. Target layout

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ top bar  Problem: [Claim or Concede v]   [verified]  Verify  Export  Settings │
├──────┬────────────────────┬─────────────────────────────────┬────────────────┤
│ rail │ navigator          │ editor group                    │ agent panel    │
│ 48px │ 260–320px          │ tabs · breadcrumbs              │ 360–440px      │
│      │                    │                                 │                │
│ Chat │ Conversations      │ 1  reference.cpp        ●       │ Conversation   │
│ Files│ ─────────────────  │ 2  validate.py                  │ header         │
│ Rev. │ Claim or Concede   │                                 │                │
│ Run  │ 2 messages · now   │ 1  #include <bits/stdc++.h>     │ transcript     │
│ Evid.│ …                  │ 2  using namespace std;         │ (only scroll)  │
│      │                    │ …                               │                │
│      │                    │                                 │ approval card  │
│      │                    │─────────────────────────────────│                │
│      │                    │ Run  [Isolate v] [Run] [Tests]  │ composer       │
│      │                    │ stdin · stdout · stderr · time  │ (sticky)       │
├──────┴────────────────────┴─────────────────────────────────┴────────────────┤
│ status  Judge0 ●  Isolate ●  Executor ●   2.0 s / 256 MiB   Ln 42  verified  │
└──────────────────────────────────────────────────────────────────────────────┘
```

On widths below ~1100 px, the agent panel becomes a toggleable right drawer and
the navigator collapses to icons. Below ~760 px, the navigator becomes a
full-height sheet; the editor and agent panel are tabs, not side-by-side. The
current 900 px rule that hides the inspector entirely is replaced by this
drawer model.

### 5.1 Activity rail

- 48 px wide, icon + tooltip + `aria-label`, roving tabindex.
- Sections: Conversations, Files, Review, Run, Evidence, History.
- Selecting a section updates the navigator; it does not destroy editor tabs.
- A badge shows unreviewed changes; a dot shows a running turn.

### 5.2 Navigator

- Conversations: search, new chat, active row, rename/delete on hover/focus,
  running indicator.
- Files: workspace tree with keyboard tree semantics (`role="tree"`,
  `aria-expanded`, arrow keys), changed-file dots, new file/folder, refresh.
- Review: unreviewed change list, per-file diff entry, "Mark reviewed" and
  "Revert unreviewed" with explicit counts.
- Run: recent runs, sample tests, backend status; the same data as the run
  panel but persistent.
- Evidence: verification summary, checks, warnings, limits, spec counts.
- History: checkpoints and snapshots with restore actions.

### 5.3 Editor group

- Tab bar with dirty dot, close button, middle-click close, `Ctrl+Tab` cycle.
- Breadcrumbs from workspace root to file.
- Monaco model per tab; preserve cursor/scroll per file.
- Diff view opens as a tab (`diff:path`) with a side-by-side/inline toggle.
- Bottom run panel, resizable, with:
  - backend segmented control: **Isolate** (default), **Judge0** (quick),
    **Local** (bwrap fallback);
  - language label, Run, Run sample tests, Load sample;
  - tabs for stdin, stdout, stderr, compile output, result;
  - status chip (`OK`, `RE`, `TO`, `CE`, `WA`), time, memory;
  - a visible "quick run is not verification" note;
  - per-file persisted stdin and backend.
- Empty state: "Open a file or create one" with a keyboard hint.

### 5.4 Agent panel

- Persistent like Cline's `ChatView`; do not remount on tab changes.
- Header: problem name, chat title, mode (Author/Debug/Review), state
  ("thinking", "waiting for approval", "stopped"), reload.
- Transcript: one `role="log"` scroller, stick-to-bottom with a "Follow live"
  pill when the user scrolls up.
- Event cards: assistant text, reasoning (collapsed), tool calls with
  arguments/results, file changes (click opens diff), verification evidence,
  errors.
- Inline approval card: approve/reject all, per-action args, no modal.
- Inline clarification card: labelled questions, recommended answer, submit.
- Composer: sticky, autosizing, context chips, `@` mentions, attachment-free,
  `Ctrl+Enter` send, queue when a turn is running, disabled only when approval
  is pending.
- A turn never makes the composer disappear; the status moves to the header and
  the status bar.

### 5.5 Status bar

- Left: Judge0, Isolate and executor health dots with tooltips; click opens
  settings/health evidence.
- Center: limits (time/memory), measured or "not measured".
- Right: cursor position, language, selection, verification state, export gate.

## 6. Judge0 embedding

### 6.1 Policy (unchanged)

- Judge0 CE is a **quick-run/IDE backend**; it is not the verification
  authority.
- Isolate 1.8.1 is the default verifier executor; bwrap remains for the LaTeX
  statement PDF and fallback.
- Secret tests and `.ans` files are never sent to Judge0.
- Quick-run output is labelled "unverified".

### 6.2 Native run panel, not an iframe

Use Judge0's IDE pattern natively:

1. Map the open file's extension to a Judge0 language id (C++/C/Python/Java/
   Kotlin); show the language and allow an override.
2. Build a submission: `source_code`, `stdin`, optional `compiler_options` and
   `command_line_arguments`, plus the workspace's limits.
3. Poll the token; render `status.description`, `time`, `memory`,
   `stdout`, `stderr`, `compile_output` in separate tabs.
4. Keep a per-file run history (last 10) with a diff against the previous run.
5. On failure, link "Open evidence" to the verification report, not to a
   Judge0 result.

Why not an iframe of `judge0/ide`:

- it brings a second editor, second file model and second theme;
- it cannot read the workspace or share context/tabs;
- it needs its own CSP and message bridge;
- its GoldenLayout lets the user hide the very panes the workbench needs.

If an "open in Judge0 IDE" escape hatch is still wanted, make it a separate
route with an explicit warning, not the primary experience.

### 6.3 Performance

- Judge0 calls are debounced per file; cancel in-flight runs when the file
  changes.
- The run panel shows a spinner with the backend name and a cancel action.
- Cap output (currently 4 MiB in the worker); render with virtualized or
  truncated blocks.
- The Isolate verifier copy is demand-driven: `data/` is copied only when argv
  references it (checker/interactor), not for every solution/validator run.
  This addresses the 15-minute eval budget regression found during this work.

## 7. Flows

### First run

Empty workspace → "New problem" dialog (name, idea, author, short name, start
now) → agent panel opens with a greeting and a suggested prompt → plan appears
in the editor group as `plan.md` and in the evidence panel.

### Author loop

User prompt → composer queues/disables → agent streams → tool cards/change
cards appear → file changes open as diffs on click → verify runs as a job →
evidence tab updates → export enables only when verified + reviewed.

### Quick run

Open file → run panel shows Isolate/Judge0 → load sample or type stdin → Run →
output tabs → status. Switching files preserves each file's stdin and backend.

### Review

Review queue in navigator → diff tab → per-hunk apply or revert → mark
reviewed → unreviewed badge falls → export gate updates.

### Failure

Compile error → stderr/compile tab focused, line links → editor jumps to the
line. Timeout → status chip and limit hint. Backend offline → status bar dot and
a retry action; the composer still works for non-run requests.

## 8. State machines and AX

The inventory and decision are in [`STATE-MACHINES.md`](STATE-MACHINES.md).
The implementation already mirrors seven machines:

```js
AuthorMachines.machines.turn.state;      // "idle" | "streaming" | ...
AuthorMachines.machines.editor.can("SAVE");
AuthorMachines.snapshot();                // serialisable
document.body.dataset.stateTurn;          // "streaming"
document.body.dataset.panel;              // "file"
document.body.dataset.side;               // "files"
```

The AX contract for the redesign:

- landmarks: `header`, `nav` (activity rail), `aside` (navigator and agent),
  `main` (editor group), `footer` (status);
- a skip link to the editor and to the composer;
- roving tabindex for the activity rail and tabs, `aria-controls` on tabs;
- the transcript is `role="log"`, `aria-live="polite"`, named
  "Conversation"; the agent state is a separate `role="status"`;
- the run panel is a labelled region with tabs for stdin/stdout/stderr;
- every icon button has an object-specific label;
- focus is never hidden by the sticky composer/status bar (scroll padding);
- all dialogs use the same action-dialog grammar and return focus;
- state attributes are the automation contract, not private CSS classes.

Keyboard map (target):

```text
Ctrl+K          quick open
Ctrl+Shift+P    command palette
Ctrl+Enter      send message
Ctrl+S          save file
Ctrl+`          toggle run panel
F8 / Shift+F8   next/previous problem
Alt+1/2/3       focus navigator/editor/agent
Ctrl+Tab        next editor tab
Ctrl+W          close tab
Escape          close menu/dialog, stop mention menu
```

## 9. Visual system

Keep the current deep blue-black identity and indigo accent; make it stricter.

| Token | Value | Use |
|---|---|---|
| `--bg` | `#0a0c10` | app background |
| `--bg-1` | `#0e1116` | panels |
| `--bg-2` | `#12161d` | cards, editor chrome |
| `--bg-3` | `#171c25` | hover/selected row |
| `--line` | `#232b37` | 1 px borders |
| `--line-2` | `#354154` | strong borders |
| `--text` | `#eef2f8` | primary text |
| `--muted` | `#9aa7ba` | secondary text |
| `--faint` | `#8290a5` | metadata (≥ 4.5:1 on `--bg`) |
| `--accent` | `#8b9cff` | selection/focus/links |
| `--green` | `#4bd6a0` | verified/pass |
| `--amber` | `#f0b35c` | stale/warning |
| `--red` | `#ff7f8f` | failure/destructive |

- Type: 13 px UI body, 12 px code, 11 px metadata; no body text below 12 px.
- Spacing: 4 px base; 8/12/16/24/32 steps; 1 px borders; one shadow level.
- Radii: 6/8/12; no pill for primary actions.
- Motion: 120 ms hover, 180 ms enter, 240 ms panel; honor reduced motion.
- Focus: 2 px `--accent`, 2 px offset; never `outline: none` without a
  replacement.
- Touch: 24×24 desktop minimum; 44×44 on `(pointer: coarse)`.

## 10. Phased delivery

### Phase 0 — stabilize (done)

- Fix grid/scroll/composer/run-panel.
- Replace native prompt/confirm with the action dialog.
- Add chat action labels/keyboard titles and focus-within actions.
- Add `web/machines.js` and mirror seven machines.
- Add `qa/layout_regression.ps1`; keep axe/AX-tree/CDP green.

### Phase 1 — shell restructure (3–5 days)

- Add the activity rail, navigator, editor group, agent panel and status bar as
  real regions; keep existing IDs/data so feature code still works.
- Move the inspector tabs into editor tabs (Plan/Report/Diff/History/MCP).
- Add resizable panes with persistence (already partly present) and a
  right-drawer mode below 1100 px.
- Acceptance: 320/768/1100/1440 screenshots; no horizontal overflow; composer
  and run panel always in viewport; axe 0; keyboard reaches every region.

### Phase 2 — editor (4–6 days)

- Lazy-load vendored Monaco; model per tab; dirty dot; save/reload; breadcrumbs;
  cursor/scroll persistence.
- Diff tab from review/change cards; per-hunk apply.
- Keyboard tree semantics for Files.
- Fallback to the current textarea if Monaco fails to load.
- Acceptance: open/save/reload/read-only/binary/diff; no stack of native
  confirms; CDP checks tab state and dirty guard.

### Phase 3 — run and Judge0 UX (3–4 days)

- Backend segmented control (Isolate/Judge0/Local), per-file persistence.
- Output tabs (stdin/stdout/stderr/compile/result), status/time/memory chips,
  run history, cancel.
- Sample tests from `data/sample`; never secret tests.
- Demand-driven Isolate copy (already implemented) and a verification timing
  budget test.
- Acceptance: live Judge0 and Isolate runs from the panel; output truncation;
  no secret path appears in a request; eval verification under budget.

### Phase 4 — evidence and AX (3–4 days)

- Evidence report as an editor tab with check groups, warnings, limits and
  stale banner.
- Review queue and export gate derived from the machines.
- Migrate chat selection, file load, verification and changes to machines
  (Phase B/C in `STATE-MACHINES.md`).
- Manual screen-reader pass (NVDA/VoiceOver) plus AX-tree/axe.
- Acceptance: one predicate for export; no duplicate guards; keyboard-only
  author→verify→review→export; AX tree has no unnamed controls.

### Phase 5 — polish (2–3 days)

- Command palette and quick open.
- Notification center for long jobs; toast dedupe.
- First-run tour and empty states.
- Light theme only if contrast gates are green in both themes.
- Performance budget: editor interactive < 2 s on a warm local server; no
  layout shift when a run starts; transcript append < 16 ms per frame.

## 11. Test matrix

| Gate | Tool | Pass condition |
|---|---|---|
| Layout | `qa/layout_regression.ps1` | scroll/composer/run panel/dialog/chat CRUD |
| Unit/state | `web/machines.js` + browser test | illegal event is a no-op; legal event updates UI |
| Accessibility | `qa/accessibility_axe.ps1` | 0 serious/critical violations |
| AX tree | `qa/accessibility_tree.ps1` | no unnamed buttons/textboxes; log/combobox named |
| UI contracts | `qa/test_ui_contracts.py` | all existing contracts |
| Workflow | `qa/cdp_workflow.ps1` | no console errors; all feature flags visible |
| Responsive | 320/768/1100/1440 screenshots | no horizontal overflow; regions reachable |
| Keyboard | CDP Tab/Enter/Escape | focus order, dialogs, focus return |
| Backend | `qa/test_live_judge0.py`, `qa/test_isolate_worker.py` | live runs pass |
| Verifier | `qa/test_testlib.py`, `qa/test_interactive.py`, eval | no budget regression |
| Soak | `qa/soak_cdp.ps1` | no growth/errors over 30 iterations |

## 12. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Monaco bundle/worker/CSP | lazy load, vendor like Judge0, textarea fallback, measure TTI |
| State migration regressions | additive mirror first, one machine per PR, keep current tests green |
| Judge0 cgroup v2 differences | keep the adapter flags; health check before enabling the selector |
| Secret test leakage | quick-run only accepts the open file; block `data/secret` and `.ans` in the client and server |
| Isolate copy cost | demand-driven `data/` copy (implemented); add a verifier timing budget test |
| Native dialogs creeping back | lint `web/*.js` for `prompt(`/`confirm(` in CI; layout regression fails if a dialog is missing labels |
| Hover-only controls | `:focus-within` and active-row visibility; keyboard test |
| Focus obscured by sticky UI | scroll padding + `scrollIntoView({block:"nearest"})` checks |
| Over-dense IDE on small screens | right drawer + navigator sheet; region tabs below 760 px |

## 13. Open questions

1. Is Monaco acceptable at ~5 MB/worker cost, or should the editor be CodeMirror
   6? Recommendation: Monaco for parity with Judge0/VS Code, lazy-loaded.
2. Should the run panel be shared across files (one stdin) or per-file?
   Recommendation: per-file, with a "copy stdin to all" action.
3. Do we need a light theme, or is dark-first enough for the authoring context?
4. Should evidence be an editor tab (recommended) or a right-side panel? The
   editor tab gives long reports room; the status bar keeps the summary.
5. Is a full command palette worth it for a single-user local tool? It is the
   cheapest way to make the IDE feel native and to expose rare actions to
   keyboard and agent automation.

## 14. Immediate next step

Phase 1 is the highest-leverage next change: restructure the shell without
touching backend behaviour, keep every existing ID working, and land the five
regions behind the current feature code. Phase 2 (Monaco) should wait until the
shell is stable and the layout regression covers the new regions.
