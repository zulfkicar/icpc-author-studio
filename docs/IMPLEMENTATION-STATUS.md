# Implementation Status

Updated: 2026-11-09
Specification: [`MASTER-PLAN.md`](MASTER-PLAN.md)
Verification: [`ADVERSARIAL-VERIFICATION.md`](ADVERSARIAL-VERIFICATION.md)
Design: [`DESIGN.md`](DESIGN.md)
Eval evidence: [`EVAL-RESULTS.md`](EVAL-RESULTS.md)
Visual audit: [`VISUAL-AUDIT.md`](VISUAL-AUDIT.md)
UI/UX/AX redesign plan: [`UI-UX-REDESIGN.md`](UI-UX-REDESIGN.md)
UI execution package: [`plans/ui-ux-ax-rework/README.md`](plans/ui-ux-ax-rework/README.md)
UI goal prompt: [`plans/ui-ux-ax-rework/GOAL-PROMPT.md`](plans/ui-ux-ax-rework/GOAL-PROMPT.md)
UI state machines: [`STATE-MACHINES.md`](STATE-MACHINES.md)
Readiness review: [`READINESS.md`](READINESS.md)
Context-overflow incident: [`INCIDENT-CONTEXT-OVERFLOW.md`](INCIDENT-CONTEXT-OVERFLOW.md)
Judge0 decision: [`JUDGE0-EVALUATION.md`](JUDGE0-EVALUATION.md)
Isolate backend: [`ISOLATE-BACKEND.md`](ISOLATE-BACKEND.md)

## Completed

### Context and provider

- 500,000-token input budget; 24 messages kept; 393,216 output maximum.
- `ContextBudgetMiddleware` clamps `max_tokens` against a 1,048,576 model window.
- Removed the 8,000-token output cap.
- Explabs `configured-model` defaults and per-model price table.
- Model retry, model fallback, tool retry, timeout and fallback settings.
- `stream_usage=True` with real-provider usage and cost evidence.
- `ProviderRefusalMiddleware` treats OpenAI-style `refusal` fields as errors.
- `StreamIntegrityMiddleware` rejects a truncated stream with no finish reason
  instead of committing partial text.
- Concurrent `load_skill` calls use a merge reducer, so parallel skill loads
  cannot corrupt graph state.
- **Context-overflow recovery:** `ContextBudgetMiddleware` now applies a
  conservative token estimate, truncates oversized tool results, drops oldest
  complete messages and clamps output to the provider window; summarization
  runs first for normal long histories. `read_file` blocks `data/secret/**` and
  `**/*.ans` and caps large reads at 200k chars. Failed/cancelled turns persist
  the checkpoint plus a visible error/partial message. The exact failed
  `new-idea` checkpoint compacts from 677,334 to 31,144 estimated tokens and a
  real provider turn now completes and saves `OK`. See
  [`INCIDENT-CONTEXT-OVERFLOW.md`](INCIDENT-CONTEXT-OVERFLOW.md).

### Prompting, skills and clarification

- Prompt split into `prompts/base.md`, `workflow.md`, `tools.md`, `spec.md` and
  mode files.
- `SkillRegistry` with progressive disclosure, `list_skills`, `load_skill`,
  `unload_skill`.
- 13 curated CP skills, pinned into context and capped at two.
- Durable clarification via `ask_user` + `interrupt`; separate from approvals.
- Reviewer, test-designer and verifier-auditor read-only subgraphs.

### Live execution workers

- **Real Isolate 1.8.1 worker** (`isolate-worker`) runs in the default compose
  stack and is the default `AUTHOR_AGENT_EXECUTOR_URL`. It compiles/runs
  C++/C/Python/Java inside Isolate per request, with CPU, wall, memory,
  file-size, stack and process limits, read-only root and no network. Its
  `/run` and `/interact` endpoints carry the deterministic verifier, checkers,
  interactors and solutions. The app also calls `/api/workspaces/<slug>/isolate/run`
  from the Run panel's **Isolate** button. See [`ISOLATE-BACKEND.md`](ISOLATE-BACKEND.md).
- **Live Judge0 CE 1.13.1 stack** (server, worker, PostgreSQL, Redis) runs from
  `docker-compose.judge0.yml`. The app calls it at
  `/api/workspaces/<slug>/judge0/run`; the Run panel has a **Judge0** button.
  See [`JUDGE0-EVALUATION.md`](JUDGE0-EVALUATION.md).
- **Local DOMjudge 9.0.1 import:** pinned `domjudge/domserver:9.0.1` +
  `mariadb:11.4` stack (`docker-compose.domjudge.yml`), with
  `scripts/domjudge-up.ps1` / `domjudge-down.ps1`. `qa/test_domjudge_import.ps1`
  exports the verified `sum-test` package, imports it through the DOMjudge API,
  and verifies the problem: HTTP 200, `sum-test-qa`, 6 test cases, statement
  `D.pdf`, no danger, no CRLF `.ans` warnings. A real
  `domjudge/judgehost:9.0.1` round-trip also passes: accepted **AC**, wrong
  **WA**, slow **TLE**. See [`DOMJUDGE-LOCAL.md`](DOMJUDGE-LOCAL.md). A
  multi-team/contest-load test is not yet performed.
- **Native run panel:** backend selector (Local/Isolate/Judge0), per-file
  stdin and backend persistence, stdin/stdout/stderr/compile/result tabs,
  status/time/memory text, last-10 history, abort-on-file-change and a visible
  "Quick run is not verification" warning. Judge0 and Isolate remain quick-run
  only. `judge0_adapter.is_blocked_path` refuses `data/secret/**` and `**/*.ans`
  server-side; the client refuses them before the request.
- The bwrap worker remains reachable at `AUTHOR_AGENT_BWRAP_EXECUTOR_URL` and
exposes an Isolate-style `POST /isolate/run` contract for the statement PDF and
fallback:
  `time`, `wallTime`, `memory`, `processes`, `stack`, `fsize`, `openFiles` and
  returns `status`, `exit`, `time`, `wallTime`, `maxRssKb`, `message`.
- Every run is copied into a private temporary workspace.
- The child runs under **bwrap** with a read-only system root, only `/work`
  writable, `--unshare-all`, `--cap-drop ALL` and an `RLIMIT_NPROC` wrapper
  applied inside the user namespace.
- `/app/workspaces` is hidden from the child; absolute cross-workspace reads
  return `BLOCKED`.
- CPU, wall, address space, process count, stack, file size and open-file limits
  are enforced.
- Process-group cleanup kills orphaned children.
- The executor has no provider key and no external network.

### ICPC Problem Package Format

- `icpc_spec.py` audits the ICPC subset:
  - required files and directories,
  - `problem_format_version`, name, license, rights owner,
  - `limits` keys and memory,
  - `validation: default|custom [interactive]`,
  - required validators,
  - `.interaction` line format,
  - UTF-8, BOM, CRLF and filename rules,
  - groups and cycles.
- Input validators must exit **42**; output validators are invoked as
  `<validator> input answer feedback_dir [flags]` with team output on stdin and
  must exit **42** (AC) or **43** (WA).
- `output_validators/` (ICPC subset) and `output_validator/` (2025-09 draft) are
  both discovered; `problem_statement/` and `statement/` are both accepted.
- `templates/testlib.h` is the official testlib header and is copied into the
  build directory automatically.

### Checkers, interactors and groups

- Real C++ testlib fixtures: `qa/fixtures/testlib/checker.cpp`,
  `interactor.cpp`, `transcript_checker.cpp`.
- Checker self-test matrix: reference, wrong, malformed, empty, extra,
  valid/invalid fixtures, crash and accept-all rejection.
- Interactive harness with connected validator/solution pipes, transcript
  capture, wall-clock timeout, reference/negative checks and exit-code contract
  handling.
- Interactive checker-on-transcript: a transcript checker validates the captured
  protocol and rejects a forged transcript.
- Group scoring (`scoring.py`): `points` and `depends`/`dependencies`; a group
  earns points only when its own tests and all dependencies pass. The Report
  panel renders a group table with points, tests, dependencies and blocked-by
  evidence.
- Explicit float comparison with NaN rejection.

### Persistence, MCP and UX

- Conversation checkpoints, conversation-only restore, per-turn snapshots,
  snapshot retention and restore.
- Unified diff hunk parsing and selective application.
- Scoped MCP stdio server with host consent (`mcp_consent.py`). A fresh
  workspace is enabled by default with every read-only tool and `.` root, so
  relative paths (`problem.yaml`, `data/sample/01.in`, `search_workspace`)
  work immediately. Roots and per-tool consent are editable; secret tests and
  `.ans` files remain blocked.
- MCP inspector tab: enable toggle, roots, per-tool consent, per-tool arguments, save and probe.
- @-mentions, chat tabs, stage rail, history panel, clarification card,
  follow/pause, hunk selector, settings for context/fallback.
- Axe-core WCAG audit, keyboard/dialog check, live regions, focus-visible,
  reduced-motion, target sizing, reflow at 320px.
- **Full workbench redesign** from scratch: new top bar, vertical section rail,
  stage stepper, elevated composer, evidence inspector, MCP tool cards, new
  tokens/surfaces/spacing, responsive layout. Screenshots in
  `qa/screenshots/`; notes in [`VISUAL-AUDIT.md`](VISUAL-AUDIT.md).
- **Reported UI defects fixed:** the grid row is constrained, so long chats now
  scroll with a visible scrollbar and the composer stays in view; runnable files
  keep the run panel and stdin in view; all native `prompt`/`confirm` flows use
  one accessible action dialog with labels, inline validation, danger styling
  and focus return. Chat actions and titles are keyboard reachable with
  object-specific names. Covered by `qa/layout_regression.ps1`.
- **Monaco editor and per-file tabs (Phase 2):** `monaco-editor@0.44.0` is
  vendored under `web/vendor/monaco/` and loaded lazily through the AMD loader
  on the first edit. One model and view state is kept per workspace path;
  `#editor-tabs` shows open files, dirty dots, close buttons, `Ctrl+Tab`/
  `Ctrl+W`, and dirty-close/dirty-switch confirmation. The inline diff gained a
  native Monaco side-by-side mode. If the loader or worker fails, or
  `?editor=textarea` is set, the existing textarea + highlight.js editor is used
  without losing the tab/dirty/save contract. The file tree is a `role=tree`
  with arrow-key navigation, expand/collapse and Enter/Space activation.
- **Five-region IDE shell (Phase 1):** activity rail, navigator, central editor
  group, right agent panel and status bar. The old three-column DOM was moved,
  not rewritten: existing IDs, routes and handlers are preserved. Widths persist
  per region (`--nav-width`, `--agent-width`), splitters support drag and arrow
  keys, and the `< 1100` agent drawer / `< 760` navigator sheet trap focus,
  close on Escape and return focus to their toggle. Editor tabs use
  `role=tablist` with roving tabindex and arrow keys. The status bar mirrors
  connection, Judge0/Isolate/executor health, measured limits, language, cursor
  and verification.
- **Evidence, review and state wiring (Phase 4):** the verification report is
  an editor tab with a stale banner, a limits block, checks/warnings and
  changed-file buttons that open the diff tab. The navigator review queue shows
  the unreviewed badge, hides reverted history behind a toggle, and exposes
  Mark reviewed / Revert. Export is derived from one `exportPredicate()`
  (verified + not stale + zero unreviewed) with a textual reason. The 18 state
  machines are wired to real actions (chat, file load, verification, changes,
  MCP, settings, mentions, follow, tests, restore) and mirrored to
  `data-state-*`; `approvalRendered` and `selectedChange` duplicates were
  removed. `qa/phase4_evidence.ps1` covers the machine transitions, review/
  export flow, focus-not-obscured and the keyboard map.
- **Command palette and quick open:** `Ctrl+Shift+P` and `Ctrl+K` open an
  accessible palette dialog with filtered commands/files, arrow navigation and
  Enter/Escape. Secret tests and `.ans` files are excluded from quick open.
- **Phase 5 polish:** a notification centre with an unread badge, pinned
  long-job status (`running → idle`, approval/failure/cancel details) and
  click-through to the relevant tab; toast dedupe (`data-count`, no repeated
  announcement); a three-step onboarding tour (first-run when there are no
  workspaces, plus a permanent `?` button) and an empty-state New problem CTA;
  an optional token-based light theme persisted by `theme.js` and applied to
  Monaco; and CDP performance budgets (editor warm 8 ms, transcript append
  0.17 ms, CLS 0.0141, 1 MB render 2 ms).
- **Dialog controller (Phase 0.5):** `web/dialogs.js` owns open, Cancel,
  Escape, backdrop, focus return and an async dirty-form guard for all four
  dialogs. The settings form refuses to close with unsaved changes until the
  discard action is confirmed. A static contract fails on any native
  `prompt`/`confirm`/`alert`.
- **Explicit state machines:** `web/machines.js` defines and mirrors 18
  machines to `data-state-*` and `window.__AUTHOR_AGENT__`: connection, session,
  turn, approval, editor, run, modal, fileLoad, chat, verification, changes,
  mcp, settings, mentions, follow, tree, tests and restore. Every machine has a
  legal-path, illegal-event and hydration test in
  `qa/test_state_machines.mjs`; see [`STATE-MACHINES.md`](STATE-MACHINES.md).
- **IDE redesign plan:** Cline/VS Code/Judge0-informed five-region layout,
  native Judge0 quick-run embedding, AX keyboard/landmark contract, phased
  delivery and acceptance gates; see [`UI-UX-REDESIGN.md`](UI-UX-REDESIGN.md).

### Fault injection, chaos, soak and eval

- Real HTTP fault proxy: 429, stream disconnect, refusal, no tool calling,
  text-only response.
- Chaos: real `RLIMIT_FSIZE` exhaustion through the Isolate endpoint, clock-skew
  ordering, event replay and duplicate suppression.
- Performance soak: executor run and fake-turn latency budgets; browser tab/DOM
  soak.
- `eval/run_eval.py` real-provider `sum` and `claim` fixtures verified; see
  [`EVAL-RESULTS.md`](EVAL-RESULTS.md).
- `judge0_adapter.py` is a live quick-run backend; the Isolate worker is the
  default verifier executor. Judge0 is not the verification authority. Live route evidence:
  Judge0 `ok=true, stdout=5, status=Accepted`; Isolate `ok=true, stdout=5,
  status=OK, isolate=1.8.1`.
- MCP is enabled by default with `.` root; live probes:
  `read_file problem.yaml`, `search_workspace timelimit` and `list_tests` all
  returned `ok=true`.

## Evidence

All of the following passed in the app container / on the host:

```text
PHASE 1 TESTS PASSED
SKILL TESTS PASSED
VERIFICATION MODE TESTS PASSED
HUNK TESTS PASSED
SNAPSHOT TESTS PASSED
MCP TESTS PASSED
GROUP/FLOAT TESTS PASSED
SECURITY TESTS PASSED
STALE EXPORT TESTS PASSED
500K CONTEXT TEST PASSED
ADVERSARIAL MANIFEST PASSED (146 rows, 146 automated, 0 partial)
ACCESSIBILITY AUDIT PASSED
EVENT LEDGER TESTS PASSED
UI CONTRACT TESTS PASSED
DISK/DB FAILURE TESTS PASSED
ICPC SPEC TESTS PASSED
GROUP SCORING TESTS PASSED
TESTLIB FIXTURE TESTS PASSED
INTERACTIVE TESTS PASSED
EXECUTOR SECURITY TESTS PASSED
EXECUTOR LIMIT TESTS PASSED
ISOLATE CONTRACT TESTS PASSED
ISOLATE WORKER TESTS PASSED
LIVE JUDGE0 TESTS PASSED
CHAOS TESTS PASSED
PROVIDER FAULT TESTS PASSED
JUDGE0 ADAPTER TESTS PASSED
ALL STRESS TESTS PASSED
SOAK TESTS PASSED
```

```text
qa/accessibility_axe.ps1
  {"violations":[],"passes":20,"incomplete":1}
  keyboard: openInside=true, closed=true, focusReturned=true
  AXE ACCESSIBILITY AUDIT PASSED

qa/accessibility_tree.ps1 -> ACCESSIBILITY TREE AUDIT PASSED (no unnamed buttons/textboxes)
qa/layout_regression.ps1 -> LAYOUT REGRESSION PASSED (scrollbar=10px, composer/run panel/stdin visible, dialog focus+rename+delete)
node qa/test_state_machines.mjs -> STATE MACHINE TESTS PASSED
qa/cdp_workflow.ps1
  judge0Visible=true, isolateVisible=true, mcpRows=5, mcpToggle=true,
  mcpSave=true, treeGlyphsOk=true,
  approvalDedupe=true, clarificationVisible=true, xssEscaped=true,
  composerFocusable=true, followPaused=true, hunkRows=1, historyRows=9,
  mentionVisible=true, reflow320=true, keyboard focus moves

qa/soak_cdp.ps1
  {"iterations":30,"elapsedMs":213,"growth":82,"errors":[]}

container soak
  runs: 20, median 371.6 ms, p95 479.2 ms
  turns: 8, median 411.6 ms, p95 652.3 ms

standard package through Isolate
  status=verified, spec 18/18, tests 6 (1 sample, 5 secret)
```

Real 500k probe:

```text
input_tokens: 500045
output_tokens: 19
text: long-ok
```

Real eval:

```text
claim: verified, 38 tests, 4 negatives, 18/18 spec, 3,119,413 input tokens
sum:   verified, 29 tests, 3 negatives, 1,325,603 input tokens
```

## Remaining gaps

- **True hypervisor VM:** unavailable in this environment. The executor is a
  hardened container plus a bwrap mount namespace, not a separate VM. This is a
  documented platform limitation, not a claim otherwise.
- **Live DOMjudge:** import and a single-judgehost AC/WA/TLE round-trip are
  tested against local DOMjudge 9.0.1. A multi-team contest/load test is not
  performed. Package compatibility and a DOMjudge metadata adapter are
  implemented.
- **Judge0 cgroup version:** Judge0 CE 1.13.1 targets cgroup v1. The adapter
  enables Isolate's rlimit path so it works on this cgroup v2 host; a future
  Judge0 release with cgroup v2 support would remove that workaround.
- **Manual screen-reader traversal:** axe (0 violations), an accessibility-tree
  audit (no unnamed buttons/textboxes, named log/combobox/textbox), and
  keyboard/dialog checks pass; a human screen-reader session is still a manual
  step.
- **Verifier backend:** the deterministic verifier, checkers and interactors
  run through Isolate; only the LaTeX statement PDF uses the bwrap executor,
  because that image carries TeX Live.
- **Verifier performance:** the first Isolate-backed 2-turn eval exceeded its
  15-minute budget because each verifier run copied the full 23 MB workspace.
  The worker now copies `data/` only when argv references it (checkers and
  interactors). The 86-test `eval-claim-or-concede-2` workspace was re-measured
  after **Measure limits**: verification completed in **834.1 s** (13.9 min,
  under the 900 s budget) and returned **verified** with 86 tests, 2 accepted
  references and 4 negative solutions. Measure-limits is a separate 229.8 s
  step; total wall time was 1063.9 s. `qa/test_verification_timing.py` guards
  the recorded artifact.
- **Verifier concurrency:** two verifier runs against the same workspace must
  not overlap. The isolate worker's box-to-workspace sync is not yet locked per
  workspace; run one verification at a time (the app already serializes agent
  turns per workspace, but not quick runs).
- **Adversarial depth:** all 146 rows have automated owners, but some use
  deterministic contract tests rather than live third-party fault injection
  (for example an actual disk-full filesystem rather than `RLIMIT_FSIZE`, or a
  real provider outage rather than the local HTTP proxy).

## Evidence commands

```powershell
python -m py_compile server.py agent.py agent_state.py agent_middleware.py graph_agent.py `
  workspace.py verify.py package_model.py verification_modes.py executor_server.py `
  config.py winutil.py schemas.py skill_registry.py prompt_loader.py mcp_server.py `
  mcp_consent.py icpc_spec.py scoring.py judge0_adapter.py `
  qa/stress_agent.py qa/test_phase1.py qa/test_skills.py qa/test_verification_modes.py `
  qa/test_interactive.py qa/test_hunks.py qa/test_snapshots.py qa/test_mcp.py `
  qa/test_groups_float.py qa/test_security.py qa/test_testlib.py qa/test_group_scoring.py `
  qa/test_provider_faults.py qa/test_chaos.py qa/test_isolate_contract.py qa/test_isolate_worker.py qa/test_live_judge0.py
node --check web/app.js
node --check web/dialogs.js
node --check web/machines.js
node qa/test_state_machines.mjs
python qa/test_context_budget.py
python qa/test_context_500k.py
python qa/test_verification_timing.py
powershell -NoProfile -ExecutionPolicy Bypass -File qa/test_domjudge_import.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File qa/test_domjudge_judging.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File qa/layout_regression.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File qa/accessibility_axe.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File qa/accessibility_tree.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File qa/cdp_workflow.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File qa/soak_cdp.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File qa/phase2_editor.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File qa/phase4_evidence.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File qa/phase5_polish.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File qa/phase5_perf.ps1
```
