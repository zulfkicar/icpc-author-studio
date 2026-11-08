# Implementation Status

Updated: 2026-11-08  
Latest commit: `pending`  
Specification: [`MASTER-PLAN.md`](MASTER-PLAN.md)  
Verification: [`ADVERSARIAL-VERIFICATION.md`](ADVERSARIAL-VERIFICATION.md)  
Design: [`DESIGN.md`](DESIGN.md)

## Completed

### Context and provider

- 500,000-token input budget; 24 messages kept; 393,216 output maximum.
- `ContextBudgetMiddleware` clamps `max_tokens` against a 1,048,576 model window.
- Removed the 8,000-token output cap.
- Explabs `configured-model` defaults and per-model price table.
- Model retry, model fallback, tool retry, timeout and fallback key/base URL settings.
- `stream_usage=True` with real-provider usage and cost evidence.

### Prompting, skills and clarification

- Prompt split into `prompts/base.md`, `workflow.md`, `tools.md`, and mode files.
- `SkillRegistry` with progressive disclosure, `list_skills`, `load_skill`, `unload_skill`.
- 13 curated CP skills: constraints, domain taxonomy, difficulty calibration, coverage, test design, negatives, validator, checker, interactive, statement, limits, verifier audit, delivery.
- Active skills pinned into context and capped at two.
- Durable clarification via `ask_user` + `interrupt`; separate from approvals.
- Clarification answers persisted in `.agent/chats/<id>.clarifications.json`.
- Reviewer, test-designer and verifier-auditor read-only subagents; reviewer wrapped in a real `StateGraph`.

### Verification

- Kattis/ICPC package discovery: `statement/`, `data/sample`, recursive `data/secret`, groups, valid/invalid output, output validator.
- Standard, checker/output-validator and interactive modes.
- Checker self-test matrix: reference, wrong, malformed, empty, extra, valid/invalid fixtures, crash/timeout handling.
- Interactive executor harness with connected validator/solution pipes, transcript capture, wall-clock timeout and negative/reference checks.
- Test groups and cycle validation.
- Explicit float comparison with NaN rejection.
- Checker/interactive evidence included in the verification report and UI.
- Standard `sum-test` regression still verifies; checker and interactive fixtures verify.

### Persistence and review

- Conversation checkpoint history listing and conversation-only restore.
- Per-turn workspace snapshots; snapshot list and restore.
- Unified diff hunk parsing and selective hunk application.
- Scoped MCP stdio server with read/list/search/report tools, secret-test rejection and no shell/write/export.
- @-mentions, chat tabs, stage rail, history panel, clarification card, follow/pause scrolling, hunk selector, settings for context/fallback, and WCAG-minded focus/reduced-motion/target styles.

### Tests

Run locally:

```text
python qa/test_phase1.py
python qa/test_skills.py
python qa/test_verification_modes.py
python qa/test_hunks.py
python qa/test_snapshots.py
python qa/test_mcp.py
python qa/test_groups_float.py
python qa/test_security.py
python qa/test_stale_export.py
python qa/test_context_500k.py
python qa/test_adversarial_manifest.py
python qa/test_accessibility.py
python qa/stress_agent.py
```

Interactive (inside app container):

```text
docker exec icpc-author-agent python qa/test_interactive.py
```

All listed suites pass. Chrome CDP verified:
- open `submissions/accepted/ref.cpp`
- enter edit mode with line numbers
- run sample tests 1/1 through the executor
- chat tab creation
- @-mention popup
- stage rail rendering
- no console errors

Real provider smoke after the changes:

```text
text: xplabs-final
usage: input 3882 / output 5 / total 3887
estimated cost: $0.001463
```

## Latest evidence

```text
python qa/test_context_500k.py    -> 500K CONTEXT TEST PASSED
python qa/test_adversarial_manifest.py -> 146 rows mapped; 117 automated, 29 partial
python qa/test_accessibility.py   -> ACCESSIBILITY AUDIT PASSED
qa/cdp_workflow.ps1               -> followPaused=true, hunkRows=1, historyRows=9, mentionVisible=true
python qa/probe_long_context.py   -> input_tokens=500045, output_tokens=19, text=long-ok
docker exec ... qa/test_executor_security.py -> EXECUTOR SECURITY TESTS PASSED
```

## Remaining gaps

- A true hypervisor VM is still unavailable; the executor is a hardened container.
- Live DOMjudge import/export is intentionally not tested; no instance exists.
- All 146 adversarial rows are mapped in `qa/adversarial_manifest.json`: 117 automated, 29 partial. Partial rows are limited to container/network/VM checks, remaining UI matrix rows and provider failure modes.
- Real 500k long-context provider testing passed: 500,045 input tokens and `long-ok`; the opt-in probe is `qa/probe_long_context.py`. Synthetic 500k compaction passes in `qa/test_context_500k.py`.
- Follow/pause scrolling is implemented and the CDP workflow reports `followPaused=true`. Static WCAG audit (`qa/test_accessibility.py`) passes; a full browser-based keyboard matrix remains partial.
- Hunk UI and history/snapshot panel APIs are wired; the CDP workflow reports `hunkRows=1`, `historyRows=9`, `followPaused=true`, and the @-mention menu visible.
- Checker/interactor tests require the executor; CI skips the interactive suite when no executor is present.

## Evidence commands

```powershell
python -m py_compile server.py agent.py agent_state.py agent_middleware.py graph_agent.py `
  workspace.py verify.py package_model.py verification_modes.py executor_server.py `
  config.py winutil.py schemas.py skill_registry.py prompt_loader.py mcp_server.py `
  qa/stress_agent.py qa/test_phase1.py qa/test_skills.py qa/test_verification_modes.py `
  qa/test_interactive.py qa/test_hunks.py qa/test_snapshots.py qa/test_mcp.py `
  qa/test_groups_float.py qa/test_security.py
node --check web/app.js
```
