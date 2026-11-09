# Current state

Baseline: commit `b04e5d7` (or later) on `main`.
Stack: Python 3.13 app, classic-script frontend (`web/app.js`, no bundler),
Docker Compose, Judge0 CE 1.13.1 quick-run stack, real Isolate 1.8.1 verifier
executor, bwrap executor for the LaTeX statement PDF.

## 1. Repository map

| Path | Role |
|---|---|
| `web/index.html` | workbench shell, editor, chat, inspector, dialogs |
| `web/style.css` | tokens, layout, panels, dialogs, responsive rules |
| `web/app.js` | UI state, events, API calls, rendering, dialogs |
| `web/machines.js` | explicit state machines (new foundation) |
| `server.py` | HTTP routes, static files, jobs, verification, settings |
| `verify.py` | deterministic verifier |
| `isolate_worker.py` | Isolate `/run`, `/interact`, source-run API |
| `executor_server.py` | bwrap worker and LaTeX path |
| `judge0_adapter.py` | live Judge0 quick-run adapter |
| `qa/` | deterministic, browser, accessibility and soak tests |
| `docs/` | plans, decisions, evidence, status |
| `workspaces/` | one directory per problem (gitignored) |

## 2. Current shell

`main.layout` is a five-column CSS grid:

```text
left sidebar | splitter | chat pane | splitter | right inspector
```

- Left: problem card, Chats/Files/Changes tabs, side panels.
- Centre: chat header, stage rail, messages, composer.
- Right: inspector header, Plan/File/Report/Diff/History/MCP tabs.
- File editor and run panel live inside `#panel-file` in the right inspector.
- Top bar: problem switcher, status pill, Build answers, Limits, Verify,
  Export, Settings.
- Dialogs: `#new-dialog`, `#settings-dialog`, `#context-dialog`,
  `#action-dialog`.

The current layout is workable but not the target. The editor is cramped; the
chat and evidence compete; the run panel is hidden inside the inspector.

## 3. Current state fields

`web/app.js` keeps:

```js
slug, summary, tree, expanded, changes, chats, chatId, chatQuery,
plan, file, dirty, settings, tools, jobId, jobChatId, jobEvents,
pollTimer, activeTab, activeSide, selectedChange, pendingMessage,
pendingApproval, selectedContext, samples, activeSample, testResults,
openTabs, mentionQuery, follow, fileBusy, approvalRendered,
renderedChangeIds, fileMode, streaming
```

Many of these encode lifecycles. `web/machines.js` currently defines and
mirrors:

- `connection`
- `session`
- `turn`
- `approval`
- `editor`
- `run`
- `modal`

The remaining machines are catalogued in
[`../../STATE-MACHINES.md`](../../STATE-MACHINES.md):

- chat selection
- verification/export
- file load
- changes/review
- MCP consent
- settings
- mentions
- follow/scroll
- tree selection
- test tabs
- checkpoint restore

## 4. Current behaviours

### Chat

- `#messages` is `role="log"` and the only scroller.
- Composer is always visible after the grid fix.
- Chat actions are keyboard reachable; titles are buttons.
- Approval and clarification cards are inline.
- A running job locks chat switching/new chat/second send.
- A queued message (`pendingMessage`) sends when the job finishes.

### Editor

- Textarea + highlight.js, not Monaco.
- Single file at a time; no tabs; no per-file cursor/scroll.
- Dirty guard uses the action dialog.
- Run panel appears for C/C++/Python/Java/Kotlin files.
- Judge0 and Isolate buttons are separate; local Run is the default.

### Verification/export

- `summary.lastStatus`, `stale`, `unreviewed` drive the status pill and export
  button.
- Export is disabled unless verified + not stale + zero unreviewed.
- Verification report is a right-panel tab.
- Change diff is a right-panel tab.

### Dialogs

- All native `prompt`/`confirm` calls are gone.
- `actionDialog` supports prompt/confirm, danger, validation, focus return,
  Escape and backdrop cancel.
- New problem, settings and context dialogs have their own cancel listeners.
- Cancel coverage is now regression-tested.

## 5. Backend boundaries

- The default `AUTHOR_AGENT_EXECUTOR_URL` is the Isolate worker.
- `/run` is the executor-compatible argv/workspace API.
- `/interact` is the two-process interactive harness.
- `/isolate/run` is the source-run API used by the quick-run button.
- Judge0 is a live quick-run backend only.
- The bwrap executor remains for the statement PDF/LaTeX and fallback.
- Isolate copies `data/` only when argv references it. This fixed the
  15-minute eval budget regression.
- Metadata parsing is defensive (`_number`) so a corrupted/clock-skewed line
  cannot 400 a valid run.

## 6. Current evidence

Passing at baseline:

```text
qa/layout_regression.ps1
  chatScrolls=true, scrollbarPx=10, composerVisible=true,
  runPanelVisible=true, runPanelInViewport=true,
  dialogCancelClosed=true, newDialogCancelClosed=true,
  settingsDialogCancelClosed=true, contextDialogCancelClosed=true
node qa/test_state_machines.mjs
  STATE MACHINE TESTS PASSED
qa/test_ui_contracts.py
qa/test_accessibility.py
qa/accessibility_axe.ps1
qa/accessibility_tree.ps1
qa/cdp_workflow.ps1
qa/test_isolate_worker.py
qa/test_testlib.py
qa/test_interactive.py
```

Verifier timing:

```text
eval-claim-or-concede-2
  86 tests, 650.8 s (under the 15-minute budget)
  failed only on “Limits measured”
```

The package failure is a workflow state issue, not a verifier regression.

## 7. Known constraints

- In-memory jobs: restarting `author-agent` loses running jobs. Do not restart
  containers while a verification/eval is running.
- No bundler: Monaco must be vendored and lazily loaded, like Judge0 IDE.
- Docker on Windows/WSL: commands are run through
  `wsl -e sh -c "cd /mnt/e/ICPC/author-agent && ..."`.
- The app image must be rebuilt after source changes unless using a temporary
  `docker cp` for static files.
- Judge0 CE 1.13.1 targets cgroup v1; the adapter uses Isolate rlimits on this
  cgroup v2 host.
- The verifier still expects measured limits before export; the eval fixture
  did not run that step.

## 8. Current risks

| Risk | Current mitigation |
|---|---|
| Long chat pushes layout | grid/min-height fix + regression test |
| Native dialogs creep back | action dialog + static check recommended |
| Hidden hover actions | focus-within/active-row visibility |
| Isolate copy cost | demand-driven data copy + timing guard needed |
| Job loss on restart | document; avoid restarts during jobs |
| Monaco fallback | plan requires textarea fallback |
| State duplication | machines foundation; migrate incrementally |
| Secret leakage | server/client guards; add run-panel tests |

## 9. Baseline commands

```powershell
# rebuild the app after source changes
wsl -e sh -c "cd /mnt/e/ICPC/author-agent && docker compose up -d --build author-agent"

# UI / accessibility
& 'C:\Projects\author-agent\qa\layout_regression.ps1'
& 'C:\Projects\author-agent\qa\accessibility_axe.ps1'
& 'C:\Projects\author-agent\qa\accessibility_tree.ps1'
& 'C:\Projects\author-agent\qa\cdp_workflow.ps1'
node 'C:\Projects\author-agent\qa\test_state_machines.mjs'

# container suites
wsl -e docker exec icpc-author-agent python qa/test_ui_contracts.py
wsl -e docker exec icpc-author-agent python qa/test_accessibility.py
wsl -e docker exec icpc-author-agent python qa/test_isolate_worker.py
wsl -e docker exec icpc-author-agent python qa/test_testlib.py
wsl -e docker exec icpc-author-agent python qa/test_interactive.py
```
