# Module cheat sheet

One page. What does what, who calls whom, and what proves it.

The app is a local single-author workbench. The workspace is the source of
truth; the verifier is the authority; the UI is an instrument.

---

## 1. The flow in one line

```text
Browser -> server.py -> graph_agent.py -> agent.py -> tools
        -> workspace.py (files) / verify.py (evidence)
        -> winutil.py -> isolate_worker.py / executor_server.py
        -> export ZIP -> DOMjudge 9.0.1
```

## 2. Modules

| Layer | Module | What it does | Read it for |
|---|---|---|---|
| HTTP | `server.py` | Loopback server, routes, jobs, event polling, per-workspace locks | `Handler`, `start_job`, `workspace_lock` |
| UI | `web/app.js` | Five-region UI, editor, run panel, evidence, review, dialogs | `app.js`, `dialogs.js`, `machines.js` |
| Agent | `graph_agent.py` | LangGraph graph, middleware order, turn lifecycle, checkpoint repair | `_graph`, `run_turn`, `_repair_checkpoint` |
| Tools | `agent.py` | Tool implementations, path/command guards, secret-read blocks, system prompt | `_dispatch`, `_clean_command`, `SYSTEM` |
| Middleware | `agent_middleware.py` | Pinned context, conservative counter, hard trim, stream/refusal guards | `PinnedContextMiddleware`, `ContextBudgetMiddleware` |
| State | `agent_state.py` | Typed graph state | `AuthorState`, `MAX_CONTEXT_FILES` |
| Prompts | `prompt_loader.py`, `prompts/` | Composes the system prompt | `compose_system`, `mode_text` |
| Skills | `skill_registry.py`, `skills/` | Curated CP skills, max two active | `index_text`, `pinned_text` |
| Settings | `config.py` | Provider settings, key storage, redaction | `load`, `save`, `public` |
| Workspace | `workspace.py` | Paths, scaffold, files, diffs, review, chats, plans, snapshots | `resolve`, `write_text`, `changes`, `snapshot_hash` |
| Package | `package_model.py` | Tests, validators, groups, interactive flag | `load`, `group_errors` |
| Verifier | `verify.py` | Structure, validator, references, negatives, limits, PDF, export | `verify`, `measure_limits`, `export_package` |
| Modes | `verification_modes.py` | Checker self-test, interactive harness | `checker_selftest`, `interactive_selftest` |
| Spec | `icpc_spec.py` | ICPC package format audit | `audit` |
| Scoring | `scoring.py` | Group points and dependencies | `evaluate` |
| Exec | `winutil.py` | Local process execution and remote executor client | `run_captured`, `run_measured` |
| Isolate | `isolate_worker.py` | Real Isolate 1.8.1 box lifecycle and limits | `run_argv`, `_isolate_args` |
| bwrap | `executor_server.py` | bwrap sandbox for LaTeX/PDF and fallback | `run`, `isolate_run` |
| Quick run | `judge0_adapter.py` | Optional Judge0 backend; blocks secret tests | `run_file`, `quick_run` |
| MCP | `mcp_server.py`, `mcp_consent.py` | Scoped MCP server and per-tool consent | `call`, `handle`, `allowed` |

## 3. Who calls whom

**One agent turn**

```text
Browser -> server -> start_job -> graph_agent.run_turn
  -> _run_turn_async -> _graph -> middleware -> model
  -> tool wrapper -> agent._dispatch -> workspace / verify / winutil
  -> save_chat_messages / save_plan / snapshot_turn
```

**Verification and export**

```text
Browser -> server -> verify.verify
  -> package_model.load -> _structure -> checker_selftest
  -> _compile -> _run -> winutil -> isolate_worker
  -> _statement -> winutil -> executor_server (pdflatex)
  -> icpc_spec.audit -> scoring.evaluate -> workspace.set_report
  -> export_package -> workspace.snapshot_hash -> zipfile
```

## 4. What proves what

| Claim | Proof |
|---|---|
| The package is structurally complete | `verify._structure` + 16 report checks |
| The validator accepts every test | `verify.verify` — 6/6, exit 42 |
| The reference is correct | `verify.verify` — AC on every test |
| The negative solution is killed | `verify.verify` — survivor check |
| Limits are measured | `verify.measure_limits` |
| The statement compiles | `verify._statement` — `pdflatex` twice |
| The package is spec-compliant | `icpc_spec.audit` — 18/18 |
| Export is safe | `verify.export_package` — verified + unchanged + reviewed |
| The ZIP imports into DOMjudge | `qa/test_domjudge_import.ps1` |
| The judgehost judges | `qa/test_domjudge_judging.ps1` — AC/WA/TLE |

## 5. If asked, say this

- **"The model proposes; the verifier proves."**
- **"Export is verified, unchanged and reviewed — or it is disabled."**
- **"Secret tests go to the verifier, not to the provider."**
- **"Isolate is the authority; Judge0 is a convenience."**
- **"It is a hardened container, not a hypervisor."**
- **"The single-author loop is proven; multi-user hosting is not."**

## 6. Read in this order

1. `verify.py` — the authority.
2. `agent.py` — the tool surface.
3. `graph_agent.py` — the turn lifecycle.
4. `workspace.py` — the source of truth.
5. `isolate_worker.py` — the execution boundary.

Full detail: `docs/TECHNICAL-DEEP-DIVE.md`.
