# Implementation Status

Updated: 2026-11-08
Specification: [`MASTER-PLAN.md`](MASTER-PLAN.md)
Verification: [`ADVERSARIAL-VERIFICATION.md`](ADVERSARIAL-VERIFICATION.md)
Design: [`DESIGN.md`](DESIGN.md)
Eval evidence: [`EVAL-RESULTS.md`](EVAL-RESULTS.md)
Visual audit: [`VISUAL-AUDIT.md`](VISUAL-AUDIT.md)
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
  stack. It compiles/runs C++/C/Python/Java inside Isolate per request, with
  CPU, wall, memory, file-size, stack and process limits, read-only root and no
  network. The app calls it at `/api/workspaces/<slug>/isolate/run`; the Run
  panel has an **Isolate** button. See [`ISOLATE-BACKEND.md`](ISOLATE-BACKEND.md).
- **Live Judge0 CE 1.13.1 stack** (server, worker, PostgreSQL, Redis) runs from
  `docker-compose.judge0.yml`. The app calls it at
  `/api/workspaces/<slug>/judge0/run`; the Run panel has a **Judge0** button.
  See [`JUDGE0-EVALUATION.md`](JUDGE0-EVALUATION.md).
- The bwrap worker still exposes an Isolate-style `POST /isolate/run` contract:
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

### Fault injection, chaos, soak and eval

- Real HTTP fault proxy: 429, stream disconnect, refusal, no tool calling,
  text-only response.
- Chaos: real `RLIMIT_FSIZE` exhaustion through the Isolate endpoint, clock-skew
  ordering, event replay and duplicate suppression.
- Performance soak: executor run and fake-turn latency budgets; browser tab/DOM
  soak.
- `eval/run_eval.py` real-provider `sum` and `claim` fixtures verified; see
  [`EVAL-RESULTS.md`](EVAL-RESULTS.md).
- `judge0_adapter.py` and `isolate_client.py` are live quick-run backends;
  neither is the verification authority. Live route evidence:
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

standard package through bwrap
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
- **Live DOMjudge:** intentionally not tested; no instance exists. Package
  compatibility and a DOMjudge metadata adapter are implemented.
- **Judge0 cgroup version:** Judge0 CE 1.13.1 targets cgroup v1. The adapter
  enables Isolate's rlimit path so it works on this cgroup v2 host; a future
  Judge0 release with cgroup v2 support would remove that workaround.
- **Manual screen-reader traversal:** axe (0 violations) and keyboard/dialog
  checks pass; a human screen-reader session is still a manual step.
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
```
