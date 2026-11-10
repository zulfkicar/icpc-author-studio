# ICPC Author Agent — Master Plan

> **Current forward plan (2026-11-10):** [Full system audit and implementation plan](plans/system-depth/README.md).
> It covers the whole authoring app and incorporates the domain-depth extension.
> This older plan remains a historical baseline where its backlog differs.

> **Scope extension (2026-11-10):** [Domain depth and correctness](DOMAIN-DEPTH-PLAN.md)
> adds substantive skills, proof obligations, executable refutation, structured
> review and behavioral evaluation. This follow-up is scoped, not implemented.
> Baseline gaps below are historical. See [Implementation Status](IMPLEMENTATION-STATUS.md)
> for recorded implementation progress.

Status: implementation plan
Baseline: `f16ff8d`
Design specification: [`DESIGN.md`](DESIGN.md)
Canonical verification plan: [`ADVERSARIAL-VERIFICATION.md`](ADVERSARIAL-VERIFICATION.md)

## 1. Purpose

Build a local, inspectable ICPC problem-authoring agent that can take a problem idea to a package which is:

- authored with human-visible reasoning and evidence,
- verified by deterministic tools,
- reviewed by humans where judgment is required,
- resumable across sessions,
- safe to run with model-generated code,
- honest about what it has and has not proved.

The product is not a chat wrapper around a compiler. It is a **workbench** where every stage is visible: planning, writing, test design, validation, checker/interactor work, verification, review and delivery.

## 2. Current baseline

Already present:

- `create_agent` runtime with middleware.
- Durable `AsyncSqliteSaver` checkpoints.
- Pinned working memory, todo list, summarization.
- HITL export approval and optional write approval.
- Context tools, modes, reviewer tool.
- Separate hardened executor container for compilation/execution.
- Explabs provider defaults.
- File explorer, editor, sample test runner.
- Fake-model stress suite and CI.
- Real-provider smoke and full verifier through the executor.

Known gaps:

- Context budget is too small for the model.
- No clarification mechanism.
- No curated competitive-programming skills.
- Reviewer is not a real subgraph.
- No checker/interactor verification.
- No test groups or float tolerance.
- No agentic verifier.
- UX is not consistently follow-along.
- No history restore, snapshots, hunk review or MCP.
- No @-mentions or chat tabs.
- No full adversarial verification suite.
- True hypervisor VM is not available.

## 3. Goals and non-goals

### Goals

1. 500k input context budget with compaction and safe output reservation.
2. Curated competitive-programming skills with progressive disclosure.
3. Clarification for high-impact ambiguity.
4. Deterministic verification for standard, checker, interactive, grouped and float-tolerant problems.
5. Agentic verifier that proposes and explains but never overrides deterministic evidence.
6. Follow-along UX with readable output at every stage.
7. Durable history, restore, inline hunk review and a scoped MCP adapter.
8. Adversarial tests for correctness, security, concurrency and recovery.
9. A proper `Design.md` that governs the UI.
10. A single goal prompt that can drive implementation to completion.

### Non-goals

- Live DOMjudge integration. No DOMjudge instance is available.
- A true hypervisor VM in this environment. The executor is a hardened container.
- Multi-user auth/RBAC.
- Managed credential storage.
- Billing integration.
- Interactive/custom checker support is **in scope**; live judge integration is not.

## 4. Product principles

1. **Follow along.** No important action is hidden in a terminal or raw log.
2. **Evidence over assertion.** A claim without an artifact is not evidence.
3. **Deterministic authority.** Agents propose; the harness decides.
4. **Human control.** Approve, reject, edit, stop, retry, restore.
5. **Progressive disclosure.** Summary first, detail on demand, raw on request.
6. **Recognizable states.** Queued, running, passed, failed, cancelled, stale.
7. **Readable output.** Structured renderers for tools, tests, diffs, checkers, transcripts.
8. **No silent semantics.** Ask when ambiguity changes the problem.
9. **No hidden agency.** Tools have scopes; approvals show exact effects.
10. **Accessible by default.** Keyboard, focus, contrast, status announcements.

## 5. Architecture

```text
User
  |
  v
Author app
  |-- prompt assembly: base + mode + skill index + pinned memory + evidence
  |-- skill registry: load only relevant SKILL.md
  |-- author agent: create_agent + middleware
  |-- clarification/approval state machines
  |-- reviewer subgraph
  |-- test-designer and verifier-auditor subagents
  |-- checkpoint + per-turn workspace snapshots
  |-- event ledger: run id, sequence, stage, tool, status, artifacts
  |
  v
Executor container
  |-- compilers, Python, Java, TeX
  |-- no API key, no host port, no external network
  |-- read-only root, dropped caps, resource limits
  |-- per-run workspace copy (target state)
```

### 5.1 App boundary

The app owns provider key, checkpoints, prompts and skills, package metadata, UI state, and human approvals/clarifications. The app must not execute model-written code locally. All compile/run/verify calls go to the executor.

### 5.2 Executor boundary

Current state: one hardened executor container with the `workspaces` volume.

Target state:

- per-run temporary workspace copy,
- no access to other problems,
- cgroup/process limits per run,
- output cap,
- wall-clock cap,
- process-tree termination,
- no network,
- no `.author-agent`,
- checker/interactor run in the same restricted worker.

### 5.3 Human boundaries

Two distinct interrupts:

- **Approval** — an action is about to happen; show exact command/diff and evidence.
- **Clarification** — semantics are unknown; show questions, options, recommended default, and impact.

They must not share a schema or UI card.

## 6. Token and context policy

The model advertises a 1,048,576-token window and 393,216 output tokens. The plan uses a **500,000-token input budget**.

```yaml
modelWindowTokens: 1048576
contextBudgetTokens: 500000
summaryTriggerTokens: 500000
summaryKeepMessages: 24
maxOutputTokens: 393216
noAppCostCap: true
```

Why 500k:

- 500k input + 393k output = 893k, under the model window.
- Leaves ~155k headroom for system/tool/schema tokens and provider differences.
- Compaction still happens before the provider limit.

### 6.1 ContextBudgetMiddleware

Before each model call:

1. Estimate input tokens.
2. Reserve output tokens.
3. If input + output > model window, clamp `max_tokens`.
4. If output room is below a safe floor, trigger compaction.
5. Emit a `context_budget` event with estimated input, reserved output, and compaction state.

### 6.2 Memory hierarchy

- Checkpoint messages: authoritative conversation.
- Pinned memory: brief, decisions, requirements, open questions, focus, todos, mode, selected context, verifier evidence.
- Active skills: full instructions for max 2 skills.
- Summaries: compacted history; never the only copy of critical facts.
- Workspace files: package state.
- Snapshots: per-turn workspace state.

### 6.3 Unlimited tokens, bounded operations

No app-level token or cost cap. However: tool-call limit, wall-clock limit, executor CPU/memory/PID limits, output caps, provider rate-limit handling, cost telemetry and cancellation. Unlimited token spend must still be observable and interruptible.

## 7. Prompt architecture

Replace the monolithic prompt with composable files:

```text
prompts/
  base.md
  workflow.md
  tools.md
  modes/author.md
  modes/debug.md
  modes/review.md
  skills/<name>/SKILL.md
  assembly.py
```

### 7.1 Base prompt

Must define identity and mission, success criteria, evidence contract, tool policy, clarification policy, approval policy, memory/compaction rules, security rules, output style, stop conditions, subagent delegation and verifier authority.

### 7.2 Workflow contract

```text
Observe -> Plan -> Act -> Verify -> Record -> Review -> Deliver
```

The agent must inspect before writing, state intent before a tool batch, use the verifier as truth, record decisions, keep todos current, and stop when green or blocked.

### 7.3 Skill protocol

- System prompt includes only the skill index.
- `load_skill(name)` activates full instructions.
- Active skill instructions are pinned.
- Max 2 active skills.
- Skills cannot grant permissions.
- `unload_skill` removes instructions from pinned context.

### 7.4 Tool policy

Every tool description must include purpose, inputs, side effects, failure modes, read/write/execute scope, examples, and whether human approval is required.

## 8. Competitive-programming skills

Each skill is a `SKILL.md` package with frontmatter:

```yaml
name: test-coverage
description: Build and audit a requirement-level coverage matrix.
when_to_use: Before trusting tests or verification.
tools: [read_file, search_workspace, run_tests]
version: 1
```

| Skill | Purpose | Mandatory output |
|---|---|---|
| `constraints` | Derive bounds, overflow and complexity requirements | Bound table + assumptions |
| `domain-taxonomy` | Identify intended technique, alternatives and unintended easy paths | Classification + rationale |
| `difficulty-calibration` | Estimate difficulty with uncertainty | Insight/implementation/edge-case rubric |
| `test-coverage` | Requirement coverage matrix | Matrix + uncovered risks |
| `test-design` | Samples, secrets, generators, stress tests, oracle | Test plan + seeds |
| `negative-solutions` | Wrong-solution families and survivors | Expected kill matrix |
| `validator-design` | Testlib validator, invalid input | Validator self-test plan |
| `checker-design` | Output validator/checker, multiple answers, partial scoring | Checker self-test matrix |
| `interactive-design` | Interactor protocol, flush, query limits | Transcript + self-test plan |
| `statement-quality` | Ambiguity, notation, examples, format | Statement review checklist |
| `performance-limits` | Worst-case tests, measured limits | Timing/memory evidence |
| `verifier-audit` | Independent evidence audit | Findings only, no approval |
| `delivery` | Metadata, review, export readiness | Final checklist |

### 8.1 Difficulty calibration

Estimate from insight depth, required algorithm/data structure, implementation burden, edge-case density, constraint tightness, intended solution length, and a local calibration corpus. Never present a single precise rating without confidence and alternatives.

### 8.2 Coverage

Coverage is requirement-level: constraint boundaries, structural cases, output multiplicity, precision, adversarial cases, performance cases, malformed input, negative-solution families and interactive protocol states. Optional gcov/llvm-cov and mutation testing for critical validators/checkers.

## 9. Clarification

### 9.1 Policy

Ask when ambiguity changes statement meaning/output format, constraints/input domain, intended technique, multiple valid answers, checker/interactor protocol, scoring/groups/limits, whether a negative solution is genuinely wrong, or destructive actions. Do not ask for naming, style, sample ordering, minor wording or safe defaults.

### 9.2 Mechanism

```text
ask_user(questions, options, context, recommended, blocking=True)
```

- Implemented with LangGraph `interrupt()`.
- `pending_clarification` is durable.
- `open_questions` and `clarifications` are state.
- Resume with answers; record as decisions.
- Batch 1-3 questions.
- Never re-ask answered questions.
- If unanswered: `Blocked on clarification`, no invented semantics.
- UI: inline clarification card, not a modal.
- Tests: pause/resume, batching, duplicate suppression, compaction survival.

### 9.3 Distinction from approval

Approval: “May I do this?” Clarification: “What does this mean?” They use separate schemas, cards and audit records.

## 10. Approvals

Approval cards show tool/action, exact command or diff, affected files, risk, test evidence, approve/reject/edit, pending queue and audit history. Export is always gated; write/delete gated when review mode is on; edit applies to write approval only; double resume is idempotent; stale approvals cannot execute.

## 11. Skills and subagents

### 11.1 Reviewer subgraph

`ReviewerState` + `StateGraph` wrapping a read-only `create_agent`. Tools: list/read/report only. No secret tests or answers. Proposal-only findings. No approval/export.

### 11.2 Test-designer subagent

Read-only. Proposes missing cases, groups, boundary conditions and adversarial tests. Cannot write package files.

### 11.3 Verifier-auditor subagent

Reviews checker/interactor evidence and transcripts. Can inspect scoped test data. Proposes fixes and additional self-tests. Cannot set `verified` or approve.

### 11.4 Delegation

Main agent delegates when a skill requires independent review. Subagent output returns as proposal evidence. Subagents cannot spawn unrestricted tools.

## 12. Verification architecture

Full adversarial matrix: [`ADVERSARIAL-VERIFICATION.md`](ADVERSARIAL-VERIFICATION.md).

### 12.1 Canonical package model

Use Kattis/ICPC package semantics: `problem.yaml`, `statement/`, `data/sample/`, `data/secret/`, `data/invalid_input/`, `data/invalid_output/`, `data/valid_output/`, `input_validators/`, `output_validator/`, `submissions/`, `test_group.yaml`, `.interaction`.

DOMjudge adapter: `domjudge-problem.ini`, `special_run`, `special_compare`. No live DOMjudge import is claimed.

### 12.2 Modes

`standard`, `output_validator`/checker, `interactive`, `interactive_checker`, grouped/scoring variants.

### 12.3 Checker/output-validator self-test

1. Reference output accepted.
2. Alternative valid output accepted.
3. Known wrong output rejected.
4. Malformed output rejected, not crashed.
5. Missing/extra output rejected.
6. Invalid jury answer yields `FAIL`, not silent success.
7. Checker timeout/crash fails.
8. `data/valid_output` accepted.
9. `data/invalid_output` rejected.
10. Feedback is readable.

### 12.4 Interactive self-test

Compile interactor/output validator and reference. Run reference and known wrong solutions. Enforce query limits, flush, wall-clock and validation limits. Capture `.interaction` transcript. Optional checker on transcript. Agent audits semantics; harness owns verdict.

### 12.5 Groups and float

`test_group.yaml` groups, dependencies and scoring. Group-aware reports. Explicit float comparator/output validator; no implicit tolerance. Invalid/valid output corpora per group where relevant.

### 12.6 Agentic verifier boundary

Allowed: propose tests, propose checker/interactor fixes, inspect transcripts, explain failures. Not allowed: set verified, approve own checker, bypass self-tests, alter constraints/limits silently, read secrets outside scoped tools.

Justification: LLM judges have position, verbosity and self-enhancement biases; they are not a correctness oracle.

## 13. UX and follow-along

### 13.1 Stage model

```text
Plan -> Generate -> Validate -> Build answers -> Measure -> Verify -> Review -> Export
```

Each stage: queued/running/passed/failed/cancelled/stale, elapsed, evidence and artifacts.

### 13.2 Event schema

```json
{
  "runId": "...",
  "seq": 42,
  "at": "...",
  "stage": "verify",
  "tool": "verify_package",
  "intent": "Check the package after fixing the validator",
  "status": "failed",
  "durationMs": 1834,
  "summary": "1 negative solution survived",
  "detail": "...",
  "artifacts": ["report.json", "verify.log"],
  "raw": "..."
}
```

### 13.3 Readable renderers

Command card, test card, diff card, verifier checklist, checker matrix, interactive transcript, PDF preview, generic tool card, raw toggle. Every output supports copy, expand, search, download and raw view.

### 13.4 Follow behavior

Auto-follow by default. Pause on scroll-up. Jump to live. Do not steal scroll. Collapse passes; expand failures. Keyboard shortcuts. Visible cancellation.

### 13.5 Accessibility

WCAG 2.2 AA: status announcements, focus visible/not obscured, keyboard operable, 24x24 targets, reflow at 320px, no color-only meaning, pause/stop/hide, reduced motion and contrast.

### 13.6 Anti-patterns

Chat-only status, raw JSON by default, hidden terminal, modal spam, auto-scroll hijack, color-only pass/fail, approval without effect, clarification without context.

## 14. `Design.md` outline

Create `docs/DESIGN.md` with product ethos; information architecture; design tokens; components; interactions; readable-output contract; accessibility; performance; trust/security; references; anti-patterns; acceptance checklist.

## 15. History, restore, hunk review, MCP

### 15.1 Conversation restore

`GET history` via `aget_state_history`; show turn summaries and checkpoint ids; restore conversation only.

### 15.2 Workspace snapshots

Snapshot before each turn. Exclude `.agent`, build artifacts and caches. Store zip + manifest. Retention policy. Restore checkpoint + files together. Preview changed files before restore.

### 15.3 Inline hunk review

Parse unified diff. Show per-hunk context. Accept/reject individual hunks. Recompute file content atomically. Record audit.

### 15.4 MCP adapter

Scoped stdio server. Read/list/search/report/verify tools. No broad shell. Per-server consent. Roots and data boundaries. Tool annotations treated as untrusted until reviewed. Explicit user consent before tool invocation.

## 16. Low-risk UI and resilience

@-mentions with file autocomplete and context chips; chat tabs; provider fallback/price UI; event sequence/replay/reconnect; failure recovery; keyboard shortcuts; performance pass.

## 17. Implementation phases

### Phase 0 — Design and schemas

Deliver `docs/DESIGN.md`, event schema, package-format schema, clarification/approval state machines. Acceptance: docs reviewed; schemas versioned.

### Phase 1 — Foundation

500k context policy, ContextBudgetMiddleware, remove 8k output cap, fallback/retry/timeout, MODEL_PRICING, CI expansion, prompt-injection/secret-redaction tests. Acceptance: 500k synthetic test, compaction, fallback, pricing, CI.

### Phase 2 — Prompts, skills, clarification, subagents

Prompt split; SkillRegistry and `load_skill`; 13 curated skills; clarification interrupt/UI contract; reviewer subgraph; test-designer/verifier-auditor; prompt/skill/compaction tests. Acceptance: skill load/compact; clarification pause/resume; reviewer read-only; no secret access.

### Phase 3 — Verification 2.0

Package model and adapter; checker mode + self-test; interactive mode + transcript; groups; float; invalid/valid corpora; agentic auditor; local fixtures. Acceptance: adversarial verifier matrix passes.

### Phase 4 — Follow-along UX

Stage rail; tool cards; readable renderers; test/checker/interactive views; approval/clarification cards; follow/pause/raw; accessibility/performance. Acceptance: CDP interaction tests, WCAG checks.

### Phase 5 — History, hunk, MCP

Conversation restore; snapshots; restore-to-turn; hunk accept/reject; MCP server with consent. Acceptance: restore file/checkpoint; hunk tests; MCP scoping.

### Phase 6 — Low-risk UI and resilience

@-mentions; chat tabs; fallback/price UI; replay/reconnect; CI extensions.

### Phase 7 — Hardening and VM

Stress suites; real Explabs smoke; adversarial UI/security tests; VM track documentation; DOMjudge skip note; commit/push.

## 18. Risks

- 500k actual provider behavior must be measured, not assumed.
- Interactive/checker correctness cannot be proven exhaustively.
- No live DOMjudge instance.
- True hypervisor VM unavailable.
- LLM judges are biased; deterministic authority is mandatory.
- Prompt injection through files/tool output is a real risk.
- Context compaction can lose nuance; pinned memory and skills mitigate.
- Checker/interactor code is unsafe until sandboxed and self-tested.
- Unlimited tokens can hide runaway behavior; operational limits remain.

## 19. Definition of done

- 500k context policy implemented and tested.
- Clarification and approval are separate, durable and visible.
- Curated skills load progressively and survive compaction.
- Reviewer is a real read-only subgraph.
- Checker/interactive/groups/float verification works locally.
- Agentic verifier cannot override deterministic evidence.
- Follow-along UX exists for every stage and tool.
- Readable output and raw output are both available.
- History/restore/snapshots/hunks/MCP work.
- @-mentions/chat tabs/fallback/price work.
- Adversarial suite passes.
- Real Explabs smoke passes.
- Docs and Design.md updated; changes committed and pushed.
- DOMjudge live integration explicitly marked unverified.
- True VM limitation documented.

## 20. Goal prompt

```text
Goal: Implement the ICPC Author Agent master plan end-to-end in C:\Projects\author-agent, starting from commit f16ff8d. Work autonomously and do not stop for routine choices. Ask the user only for high-impact ambiguity that changes semantics, constraints, checker/interactor behavior, scoring, limits, or destructive actions. Read docs/MASTER-PLAN.md and docs/ADVERSARIAL-VERIFICATION.md first and treat them as the specification.

Hard constraints:
- Deterministic harness is the final authority. Agents may propose, explain and audit; they may never mark a package verified, approve their own checker, or bypass self-tests.
- Context budget: 500,000 input tokens. Summary trigger: 500,000. Keep 24 messages. maxOutputTokens: 393,216. No app-level cost cap. Add ContextBudgetMiddleware and test a synthetic 500k context.
- Provider: Explabs https://api.example.invalid/v1, model configured-model. Keep the key local and never commit it.
- Do not implement live DOMjudge integration. No DOMjudge instance is available. Implement Kattis/ICPC package compatibility and a DOMjudge metadata adapter only.
- Do not claim a true hypervisor VM. The executor is a hardened container; document the limitation.
- Preserve existing working behavior while extending it. Read the repository before editing.

Execution order:
Phase 0: Create docs/DESIGN.md. Define the event schema, package-format schema, clarification state machine and approval state machine.
Phase 1: Implement 500k context policy, ContextBudgetMiddleware, remove the 8k output cap, fallback/retry/timeout middleware, MODEL_PRICING, CI expansion, prompt-injection and secret-redaction tests.
Phase 2: Split prompts into base/workflow/tools/modes. Build SkillRegistry with list_skills/load_skill/unload_skill. Add the curated CP skills: constraints, domain-taxonomy, difficulty-calibration, test-coverage, test-design, negative-solutions, validator-design, checker-design, interactive-design, statement-quality, performance-limits, verifier-audit, delivery. Add ask_user clarification with durable interrupts, batching, recommended defaults, blocked state and UI contract. Convert reviewer to a real StateGraph read-only subgraph. Add test-designer and verifier-auditor subagents.
Phase 3: Implement Kattis/ICPC package semantics, output validator/checker mode, interactive mode, groups, float tolerance, invalid/valid output corpora, checker/interactor self-test matrices, and agentic verifier boundaries.
Phase 4: Build the follow-along workbench: stage rail, readable tool cards, test cards, verifier checklist, checker matrix, interactive transcript, approval cards, clarification cards, follow/pause/raw, error recovery, WCAG 2.2 AA and performance.
Phase 5: Add conversation restore, per-turn workspace snapshots, restore-to-turn, inline hunk accept/reject, and a scoped MCP server with explicit consent and roots.
Phase 6: Add @-mentions, chat tabs, fallback/price UI, event replay/reconnect, and CI extensions.
Phase 7: Run the full adversarial verification suite, real Explabs smoke, full local verifier, checker/interactive fixtures, headless Chrome interaction tests, accessibility checks and performance checks. Fix all failures. Commit and push.

Verification requirements:
- Extend qa/ with deterministic fake-model tests.
- Add adversarial tests from docs/ADVERSARIAL-VERIFICATION.md: wrong solution survivors, checker accepts-everything, checker rejects-valid, malformed output, checker crash, interactor deadlock/flush/query-limit, path traversal, zip traversal, output flood, Unicode, timeout, memory, concurrent jobs, crash recovery, stale report, unreviewed export, double resume, prompt injection, secret leakage, context overflow, fallback, compaction and UI race conditions.
- Run py_compile, node --check, stress suite, CDP UI tests and the full local verifier.
- CI must pass without provider credentials.

Definition of done:
- All phases implemented except live DOMjudge and true hypervisor VM, which must be documented as gaps.
- 500k context and clarification are tested.
- Skills load progressively and survive compaction.
- Checker/interactive/groups/float work locally.
- Follow-along UX and readable output exist for all stages.
- History/restore/hunks/MCP work.
- Adversarial suite passes.
- Real Explabs smoke passes.
- Docs updated, committed and pushed.
Report the commit hash, test evidence and residual risks.
```
