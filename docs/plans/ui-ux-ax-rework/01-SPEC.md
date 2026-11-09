# Specification

Status: approved target. This is the **what and why**, not the implementation.
Implementation detail belongs in [`03-ARCHITECTURE.md`](03-ARCHITECTURE.md).

## 1. Problem

The workbench currently mixes three jobs in a cramped three-column page:

- the agent conversation lives in the centre,
- file editing and evidence share a right inspector,
- workspace navigation is a left sidebar.

The result is workable but not an IDE. Users cannot keep a file open while
watching the agent, compare a diff against the chat, or run a file without
hunting through tabs. Evidence and chat compete for the same visual weight.
Several interaction states are implicit and duplicated across handlers.

This rework gives each job a stable region and makes the agent feel like a side
panel rather than the main page.

## 2. Users and jobs

### Persona A — problem author

Writes a problem from an idea, runs the reference, watches tests fail, fixes
them, reviews changes and exports.

Needs:
- see the agent’s reasoning and tool results while editing;
- run the open file quickly without leaving it;
- see verification evidence without losing the conversation;
- know what is unreviewed and why export is blocked.

### Persona B — reviewer

Inspects diffs, applies hunks, checks consistency and restores a checkpoint.

Needs:
- a review queue that is not buried in chat;
- side-by-side or inline diffs in the editor;
- clear stale/verified state;
- keyboard-only operation.

### Persona C — agent operator

Runs the agent for long turns and automates checks.

Needs:
- a stable machine-readable state (`data-state-*`,
  `window.__AUTHOR_AGENT__`);
- no invisible hover-only actions;
- deterministic evidence and test commands;
- safe stop/cancel/approval paths.

## 3. User stories

Each story has an ID, a priority and acceptance criteria. `P0` blocks the
phase; `P1` ships with the phase; `P2` can follow.

### US-1 — Five-region shell (P0)

As an author, I see a narrow activity rail, a navigator, a central editor
group, a right agent panel and a status bar, so each job has a stable place.

Acceptance:
- all five regions are visible at ≥ 1100 px;
- the editor takes the remaining width;
- the agent panel is resizable and remembers its width;
- the status bar shows backend health, limits, cursor and verification;
- no horizontal overflow at 1440/1100/768/320.

### US-2 — Conversation always usable (P0)

As an author, the composer is always visible in a long conversation, and the
transcript scrolls independently.

Acceptance:
- a 60-message chat scrolls; the scrollbar is visible;
- the composer remains inside the viewport;
- the follow/pause control appears only when scrolled away;
- sending does not move the composer.

### US-3 — File editor with tabs (P0)

As an author, I can open several files, keep their cursor/scroll, and see which
one is dirty.

Acceptance:
- tabs show file name and dirty dot;
- switching tabs preserves cursor and scroll;
- closing a dirty tab asks through the app dialog;
- binary and read-only files do not enter edit mode;
- the editor falls back to the textarea if Monaco fails to load.

### US-4 — Quick run in place (P0)

As an author, I can run the open file with Isolate, Judge0 or the local
fallback without leaving the editor.

Acceptance:
- backend selector is visible and labelled;
- stdin is per-file and persisted;
- stdout, stderr, compile output and result are separate;
- status, time and memory are shown;
- “Quick run is not verification” is visible;
- secret tests and `.ans` are never sent to Judge0.

### US-5 — Evidence without losing context (P0)

As an author, I can open the verification report as an editor tab and still
see the conversation.

Acceptance:
- report is a tab, not a modal;
- checks, warnings, limits and stale banner are visible;
- clicking a changed file opens its diff;
- verification status is visible in the status bar.

### US-6 — Review and export gate (P0)

As a reviewer, I can review changes, apply hunks, mark them reviewed and know
why export is disabled.

Acceptance:
- review queue is in the navigator;
- unreviewed count is visible;
- export is enabled only when verified, not stale and fully reviewed;
- the reason is available as text and title, not colour only.

### US-7 — Keyboard-first (P0)

As a keyboard user, I can navigate, edit, send, run and close overlays.

Acceptance:
- Tab reaches every control in reading order;
- arrow keys move within tabs and the file tree;
- Enter/Space activates;
- Escape closes menus/dialogs and returns focus;
- shortcuts: `Ctrl+K`, `Ctrl+Shift+P`, `Ctrl+Enter`, `Ctrl+S`, `Ctrl+\``,
  `Alt+1/2/3`, `F8`.

### US-8 — Responsive (P0)

As a user on a small screen, I can still reach the editor and agent.

Acceptance:
- < 1100 px: agent panel is a drawer;
- < 760 px: navigator is a sheet; editor/agent are tabs;
- no horizontal overflow at 280/320/768;
- run panel and composer remain reachable.

### US-9 — Agent-observable state (P0)

As an agent, I can read the current UI state without scraping private classes.

Acceptance:
- `document.body[data-state-*]` exists for every machine;
- `window.__AUTHOR_AGENT__` updates on each transition;
- `AuthorMachines.snapshot()` is serialisable;
- controls have stable IDs or `data-testid`s.

### US-10 — Dialog contract (P0)

As a user, every modal cancels consistently and never traps me.

Acceptance:
- Cancel button, Escape and backdrop close every dialog;
- focus returns to the invoker or a safe fallback;
- destructive dialogs name the object and consequence;
- validation is inline and announced.

### US-11 — History and restore (P1)

As an author, I can inspect checkpoints/snapshots and restore one.

Acceptance:
- history is an editor or navigator view;
- restore is confirmed through the app dialog;
- restored state is reflected in the editor and chat.

### US-12 — MCP consent (P1)

As an author, I can see and change MCP tools/roots without leaving the
workbench.

Acceptance:
- consent is per tool and per root;
- secret tests and `.ans` remain unselectable;
- test probes show the result inline.

## 4. Functional requirements

- **FR-1** The shell has five regions and a single primary scroller per region.
- **FR-2** Existing IDs and API routes remain valid unless a task explicitly
  migrates them.
- **FR-3** The chat is the right panel; the editor is the centre; the navigator
  is the left.
- **FR-4** Editor tabs persist across navigator changes.
- **FR-5** The run panel supports Isolate, Judge0 and local execution.
- **FR-6** Judge0 results are visibly quick-run and never verification.
- **FR-7** Verification report, diff and history are editor tabs or navigator
  views, not modal-only.
- **FR-8** Export is derived from verified + not stale + zero unreviewed.
- **FR-9** Every destructive action uses the action dialog.
- **FR-10** All dialogs cancel by button, Escape and backdrop.
- **FR-11** The file tree is keyboard-navigable.
- **FR-12** Machine state is mirrored to the DOM and a public snapshot.
- **FR-13** No secret test paths or `.ans` content reach Judge0.
- **FR-14** The verification timeout remains under the documented budget.
- **FR-15** A Monaco failure does not break file viewing/editing.

## 5. Non-functional requirements

### Accessibility

- WCAG 2.2 AA baseline; AAA where already achieved.
- 0 serious/critical axe violations.
- No unnamed controls.
- Focus not obscured by sticky UI.
- Reduced motion honoured.
- 24×24 desktop / 44×44 coarse targets.

### Performance

- Editor interactive < 2 s on a warm local server.
- No layout shift when a run starts.
- Transcript append < 16 ms per frame.
- No unbounded DOM growth in a 30-iteration soak.
- Verification: 100 tests under the 15-minute budget.

### Reliability

- A failed async action returns to an editable state.
- No “spinner forever” state.
- A lost job (server restart) produces a clear error, not a silent hang.
- Reconnect/reload preserves the selected file and chat when possible.

### Security

- No provider key in execution containers.
- No external network from executors.
- Path/zip traversal blocked.
- Output flood capped.
- Secret tests never exposed.

### Compatibility

- Chrome/Edge latest, Firefox latest.
- Windows + WSL + Docker developer flow.
- Classic-script frontend remains runnable without a bundler.

## 6. Success metrics

- All P0 user stories pass their acceptance checks.
- axe 0, AX tree 0 unnamed controls.
- Layout regression passes at 1440/1100/768/320.
- Existing backend/verification suites remain green.
- A keyboard-only author → run → verify → review → export flow completes.
- The 86-test Isolate verification remains under 15 minutes.

## 7. Out of scope

- Live DOMjudge import/export.
- True hypervisor VM isolation.
- Multi-user accounts, cloud sync or remote collaboration.
- A full VS Code extension.
- Reworking the authoring agent’s prompts or verifier semantics.
- A light theme (optional future; not required for done).
- An iframe embedding of `judge0/ide` as the primary experience.

## 8. Resolved decisions

| Decision | Choice | Why |
|---|---|---|
| Shell shape | Five regions | Matches VS Code/Cline mental model |
| Agent position | Right panel | Keeps editor central while chat stays visible |
| Judge0 | Native run panel | Shares workspace/editor; no second file model |
| Editor | Monaco, lazy | Parity with Judge0/VS Code; fallback preserves robustness |
| State | Custom FSM layer | No build step; incremental migration |
| Evidence | Editor tabs | Long reports need room; status bar keeps summary |
| Modals | One action dialog | Consistent cancel/focus/validation |
| Responsive | Drawers/sheets | Preserves all regions on narrow screens |

## 9. Open questions

1. Should run history be per file or global? **Default:** per file, with a
   “copy stdin to all files” action.
2. Should the agent panel be allowed to dock left? **Default:** right only for
   v1; add preference later if requested.
3. Should the command palette include every button? **Default:** navigation and
   high-frequency actions only; keep destructive actions out.
4. Should the status bar show token/cost usage? **Default:** yes, collapsed
   behind a tooltip; it is useful for long authoring runs.
