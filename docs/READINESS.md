# Readiness review

Date: 2026-11-09
Commit reviewed: `b4a302c` (plus the CI/readiness docs in this change)
Environment: Windows 11 + WSL2 Ubuntu + Docker; Python 3.13 app; Judge0 CE
1.13.1; Isolate 1.8.1; bwrap executor.

## Verdict

**Ready for a single technical author to use locally as a developer preview.**
**Not ready to host as a shared multi-user service.**
**Not “battle tested” yet.**

The planned workbench features are implemented and the automated gates pass,
but the project has not been exercised by multiple independent authors, real
contest workflows, long-lived hosting, or a security review. Treat it as a
capable local beta, not a production service.

## Acceptance evidence

| Criterion | Evidence | Result | Notes |
|---|---|---|---|
| App starts and is reachable locally | `scripts/docker-up.ps1` → `ICPC Author Agent: http://127.0.0.1:8787/`; `/api/health` → `{"ok":true,"version":"0.1"}` | pass | Requires Docker Desktop/WSL2 and the keepalive wrapper |
| Five-region UI at 1440/1100/768/320 | `qa/layout_regression.ps1` → `LAYOUT REGRESSION PASSED`; screenshots 09–14 | pass | No horizontal overflow |
| Dialog cancel/focus contract | `layout_regression` → all cancel/escape/backdrop checks true | pass | |
| Monaco lazy load + textarea fallback | `qa/phase2_editor.ps1` → `PHASE 2 EDITOR TESTS PASSED`, `loadMs` 8–600 ms | pass | Fallback via `?editor=textarea` |
| Per-file tabs, cursor/scroll, dirty guards | `phase2_editor` → two tabs, cursor restored, dirty cancel/confirm | pass | |
| Run panel and Judge0 secret guard | `qa/cdp_workflow.ps1`; `qa/test_judge0_adapter.py` | pass | Judge0 is quick-run only |
| Evidence/review/export predicate | `qa/phase4_evidence.ps1`; screenshots 17–19 | pass | |
| Notifications, dedupe, tour, light theme | `qa/phase5_polish.ps1`; axe `lightBlocking=0`; screenshots 20–22 | pass | |
| Performance budgets | `qa/phase5_perf.ps1` → 8 ms editor, 0.17 ms append, 0.013–0.014 CLS, 2 ms 1 MB render | pass | |
| 18 state machines | `node qa/test_state_machines.mjs` | pass | |
| Context overflow and failure persistence | `qa/test_context_budget.py`, `qa/test_context_500k.py`, `qa/test_phase1.py`; exact chat recovered at 12,634 input tokens | pass | See `INCIDENT-CONTEXT-OVERFLOW.md` |
| Real provider turn saves output | temp chat → `OK`, `messages=2`; exact chat → `RECOVERED`, summary + saved | pass | Provider: `configured-model` |
| 86-test verifier under budget | `qa/verification-timing.json` → 834.1 s, verified, guard pass | pass | 900 s budget; ~66 s headroom |
| Judge0/Isolate/executor suites | `test_live_judge0`, `test_isolate_worker`, `test_executor_limits`, `test_executor_security` | pass | |
| checker/interactor/testlib | `test_testlib`, `test_interactive`, `test_verification_modes` | pass | |
| Accessibility automation | axe 0 dark/light; AX tree 0 unnamed controls | pass | |
| Manual screen-reader session | `SCREEN-READER-CHECKLIST.md` | **not tested** | Human NVDA/VoiceOver pass still unsigned |
| Shared-host auth / multi-user isolation | — | **not implemented** | Single-user loopback app |
| Public/LAN exposure security review | — | **not tested** | No auth, CSRF token, TLS or per-user root |
| Local DOMjudge import | `qa/test_domjudge_import.ps1` → HTTP 200, `sum-test-qa`, 6 tests, statement, no danger, no CRLF | pass | DOMjudge 9.0.1 + MariaDB 11.4 |
| DOMjudge submission judging | `qa/test_domjudge_judging.ps1` → accepted **AC**, wrong **WA**, slow **TLE** | pass | Real `judgehost:9.0.1` |
| True hypervisor VM isolation | — | **not tested** | Hardened containers + Isolate/bwrap |
| CI green on GitHub | `.github/workflows/checks.yml` | **not observed here** | Static/Python gates defined; browser gates are local |
| Battle-tested by independent authors | — | **not met** | This is the main release gap |

## What is proven

- End-to-end single-user authoring flow: create a problem, chat with the agent,
  edit files, run code, inspect changes, verify, review and export.
- Deterministic verification through Isolate, including checkers, interactors,
  groups and negative solutions.
- Live Judge0 quick-run with a client/server secret-test block.
- A local browser UI with keyboard navigation, dialogs, Monaco, evidence/review
  tabs, a command palette, notifications, onboarding and a light theme.
- Context recovery: the exact 1.12M-token failure now completes at 12.6k input
  tokens with a visible saved answer.
- A verified package imports into a real local DOMjudge 9.0.1 instance with
  HTTP 200, 6 test cases, a statement and no CRLF warnings.
- The full local judging loop works: accepted → **AC**, wrong → **WA**, slow →
  **TLE**, judged by `judgehost:9.0.1`.
- Provider, chaos, security, snapshot, MCP, group-scoring, ICPC-spec and UI
  contract tests.

## What “battle tested” still requires

- Several independent authors, at least 20–30 real problems, and real contest
  packages.
- Long sessions and restarts while jobs are active.
- Provider outages, rate limits, malformed tool output and disk-full recovery.
- A multi-team contest round-trip and DOMjudge under load or parallel
  judgehosts (the single-author judging loop is now proven).
- A security review of the local HTTP surface, workspace boundaries and
  provider-key handling.
- Backup/restore and upgrade rehearsals.
- Manual screen-reader sign-off.
- Chrome/Firefox and Windows/macOS/Linux usage by other people.

Until then, call it a **developer preview**, not production-ready.

## Sharing with other authors

### Recommended: one local instance per author

Each author keeps their own provider key and workspaces.

1. Share the repository (or a tagged archive).
2. They install Docker Desktop with WSL2.
3. They copy `.env.example` to `.env` and set their own
   `AUTHOR_AGENT_API_KEY`.
4. They run:
   ```powershell
   .\scripts\docker-up.ps1
   ```
5. They open `http://127.0.0.1:8787/` and create a workspace.
6. They stop with:
   ```powershell
   .\scripts\docker-down.ps1
   ```

Do **not** share `.author-agent/` or `.env`; both can contain the provider key.
Do not expose port 8787 to a LAN or the internet as-is.

### Sharing a problem

- Copy `workspaces/<slug>/` to the other author’s `workspaces/` directory, or
- Export the verified DOMjudge ZIP from the UI.

The workspace directory includes chats/checkpoints and secret tests. Share it
only with someone who is allowed to see those tests.

### Not recommended: one shared server

The current app is loopback-only, single-user and unauthenticated. A shared
server would give every visitor the same provider key, workspaces and execution
surface. Before that, add at minimum:

- authentication and per-user authorization;
- per-user workspace roots and isolation;
- TLS and a reverse proxy;
- request rate limits and execution quotas;
- backup/restore and retention;
- audit logs and secret management;
- a security review.

That work is not in this codebase.

## Operational notes

- **WSL idle shutdown:** plain `docker compose up -d` can become unreachable
  when WSL idles. Use `scripts/docker-up.ps1` (hidden keepalive) and
  `scripts/docker-down.ps1`.
- **In-memory jobs:** restarting `author-agent` loses running jobs. Avoid
  restarts while a turn or verification is active.
- **DOMjudge:** import and a single judgehost (AC/WA/TLE) are proven locally.
  The judgehost is privileged and uses `cgroup: host`; it is not a multi-team
  or load-tested contest server. See [`DOMJUDGE-LOCAL.md`](DOMJUDGE-LOCAL.md).
- **Verifier timing:** 834.1 s for 86 tests, under the 900 s budget but close.
- **Judge0:** CE 1.13.1 targets cgroup v1; the adapter uses Isolate rlimits on
  this cgroup v2 host.
- **Backups:** back up `workspaces/` (authored data) and `.author-agent/`
  (provider settings/key) securely. Neither is committed.
- **Context guard:** the conservative counter and hard trim are new; the exact
  failed chat and synthetic 500k case pass, but long-duration real-provider
  soak is still advisable.

## Decision

- **Local single-author use:** accepted as a developer preview.
- **Sharing with other authors:** accepted only as “each person runs their own
  local instance.”
- **Shared/multi-user hosting:** not accepted.
- **Contest-critical unattended use:** not accepted until the battle-test and
  security items above are closed.
