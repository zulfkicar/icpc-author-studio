# Prompt design

This document explains why [`GOAL-PROMPT.md`](GOAL-PROMPT.md) is structured the
way it is, which practices it borrows, and how to evaluate or revise it.

## 1. Design goals

The prompt must make an agent:

1. read the repository and the plan before editing;
2. execute one phase at a time without drifting into later work;
3. preserve existing behaviour and the verifier boundary;
4. produce rendered, measured evidence rather than prose;
5. stop on objective gates or a bounded turn/time limit;
6. ask only for decisions that change semantics, security or authority.

It is written for a coding agent with tools, not for a single-turn chatbot.

## 2. Source-to-section map

| Source | Principle | Where it appears |
|---|---|---|
| Anthropic Claude Code best practices | Tell the model what it cannot see | `<context>`: stack, current state, commands, constraints |
| Anthropic Claude Code best practices | Give it a check to run | `<quality_gates>` and the exact command block |
| Anthropic Claude Code best practices | Ask for evidence | `<output_format>`, `EVIDENCE.md`, “actual result” |
| Anthropic Claude Code best practices | Deterministic vs non-deterministic | gates are commands; review is model judgment |
| Anthropic Claude Code best practices | Be specific; say what “fixed” looks like | phase gates and acceptance criteria |
| Anthropic Claude Code best practices | Be ambitious about scope | first paragraph of `<mission>` |
| Anthropic Claude Code best practices | Unattended checklist | done condition, self-check, touch surface, stop bound, sign-off |
| Anthropic `/goal` | One measurable end state | `<goal_condition>` |
| Anthropic `/goal` | Stated check | named scripts and suites |
| Anthropic `/goal` | Constraints that must not change | preserve behaviour, verifier authority, secrets |
| Anthropic `/goal` | Turn/time bound | “60 turns or 4 weeks” |
| Anchored in transcript | Evidence must be visible in the conversation | output format + command results |
| OpenAI prompt engineering | Identity → instructions → examples → context | section order, examples in output format |
| OpenAI prompt engineering | Markdown/XML delimiters | XML tags for each contract |
| OpenAI prompt engineering | Few-shot patterns | evidence/status example |
| OpenAI prompt engineering | Coding agent role + structured tools + tests | `<role>`, execution protocol, gates |
| OpenAI prompt engineering | Agentic plan/decompose/TODO/persistence | execution protocol steps 1–7 |
| Google Gemini prompting | Clear, direct, consistent structure | short declarative sections |
| Google Gemini prompting | Define parameters and output verbosity | constraints, output format |
| Google Gemini prompting | Context first, instructions last | context before phase gates |
| Google Gemini prompting | Agentic risk/ambiguity/persistence | `<stop_and_ask>`, protocol step 4–7 |
| GitHub Spec Kit | Constitution → specify → plan → tasks → checklist → analyze → implement → converge | the package structure and “read order” |
| GitHub Spec Kit | Requirements-quality checklist is reviewer-owned | `05-TEST-PLAN.md` §10 |
| GitHub Spec Kit | Dependency-ordered tasks | `04-TASKS.md` |
| GitHub Spec Kit | Analyze and converge | `05-TEST-PLAN.md` §11 |
| UI UX Pro Max / UX/UI Agent Skills | Render, measure, 0 axe, keyboard, target size | constitution + phase gates |
| Cline/VS Code/Judge0 research | Persistent chat, five regions, native run panel | context + architecture |

## 3. Section-by-section rationale

### `<role>`

Gives the model a stable identity and a standard of evidence. It is short: a
long persona would compete with the repository facts.

### `<mission>`

States the end state, the phase order and the scope ambition. “Be ambitious” is
deliberate: models otherwise implement the smallest thing that satisfies the
literal request. It is paired with a bounded phase list so ambition does not
become scope creep.

### `<context>`

Contains only what the agent cannot reliably discover or would waste time
rediscovering:

- the current baseline and what is already done;
- the authoritative read order;
- the stack and the no-bundler constraint;
- the verifier/Judge0 boundary;
- the command environment.

It explicitly says “if a fact is in the repository, read the repository”. That
follows Anthropic’s rule: do not write down what the agent can find.

### `<constraints>`

Hard boundaries that are expensive to reverse:

- behaviour preservation;
- verifier authority;
- secret-test blocking;
- no native dialogs;
- no framework/bundler;
- no container restart during jobs;
- one phase per PR.

These are the “rules that cannot have exceptions” from Claude Code best
practices. In a harness that supports hooks or deny rules, mirror the security
and test rules there as deterministic enforcement, not just prompt text.

### `<execution_protocol>`

A seven-step loop: read → plan → implement → test → evidence → commit → next
phase. It encodes the agentic practices:

- plan before action;
- decompose into task IDs;
- test-first for regressions;
- read actual output before declaring success;
- record evidence;
- only then advance.

It also encodes the “one phase per PR” rule from the rollout plan.

### `<phase_gates>`

Each phase has a short, observable gate. The full detail lives in
`04-TASKS.md` and `05-TEST-PLAN.md`; the prompt repeats only the non-negotiable
outcomes so the model cannot lose them in a long context.

### `<quality_gates>`

Exact commands. This is the “give it a check to run” principle. A command is
better than an adjective: it returns pass/fail, and the output can be quoted.

### `<definition_of_done>`

The program-level end state. It is deliberately narrower than the phase gates:
regions, authority, dialogs, machines, AX, timing, evidence.

### `<stop_and_ask>`

Defines the only valid reasons to interrupt. It prevents the two common
failure modes:

- asking about routine choices (spacing, file names);
- silently making a semantic/security decision.

### `<output_format>`

A fixed report shape. It makes the agent surface evidence and risks, not just a
summary. The shape is a few-shot example: the model sees what a good report
looks like.

### `<goal_condition>`

The `/goal`-style completion condition. It has:

- one measurable end state (the shell works at four widths);
- stated checks (named scripts);
- constraints (behaviour preserved, verifier authority);
- a bound (60 turns / 4 weeks).

It is under 4,000 characters and is demonstrable from the transcript.

## 4. What was deliberately left out

- **Repository layout and file contents.** The agent can read them; repeating
  them wastes context and goes stale.
- **Vague “think hard” / “be thorough”.** Modern models have effort controls;
  vague emphasis does not replace a verifiable check.
- **A full restatement of the plan.** The prompt points to the package and
  repeats only the contracts that must not be lost.
- **Aesthetic prescriptions** (exact hex/spacing). Those live in the
  architecture/design docs and can change without changing the contract.
- **A generic “write tests” instruction.** The exact commands and acceptance
  criteria are stronger.
- **A promise that the agent can verify its own aesthetics.** The prompt says
  the opposite: axe/measurements are objective; taste is human review.

## 5. Anti-patterns avoided

| Anti-pattern | Why it fails | Replacement |
|---|---|---|
| “Improve the UI” | No observable end state | Five regions + four widths + named gates |
| “Make it accessible” | No definition | axe 0, AX-tree, keyboard map, target sizes |
| “Use best practices” | Unfalsifiable | Specific commands and documents |
| “Fix all bugs” | Unbounded | Phase gates + stop rules |
| “Be thorough” | No behavioural change | Checklist + evidence format |
| One giant prompt with every file | Context bloat, stale | Read the repo + package |
| Let the agent mark its own checklist | Self-approval | Reviewer-owned checklist |
| Trust a “done” message | No evidence | Commands + screenshots + `EVIDENCE.md` |
| Hidden deterministic rules in prose | Model may ignore | Hooks/deny rules in the harness where possible |

## 6. Evaluation rubric for the prompt itself

Run the prompt against Phase 1 in a fresh session and score:

| # | Criterion | Pass condition |
|---|---|---|
| 1 | Reads the package first | References the read order before editing |
| 2 | States the current shell correctly | Names regions, IDs, scrollers |
| 3 | Plans with task IDs | TODO uses D/S/E/R/A/M/P IDs |
| 4 | Preserves behaviour | No feature rewrite in the shell move |
| 5 | Uses the exact gates | Commands match `05-TEST-PLAN.md` |
| 6 | Produces evidence | Command output + screenshots |
| 7 | Stops at phase boundary | Does not start Monaco in Phase 1 |
| 8 | Asks only high-impact questions | No routine-choice questions |
| 9 | Handles failure honestly | Reports blocker, not green prose |
| 10 | Leaves the repo runnable | No broken IDs, no missing assets |

If fewer than 9 pass, revise the prompt, not the plan. Common fixes:

- add a missing constraint;
- move a critical instruction earlier;
- replace an adjective with a command;
- shorten a section that is diluting attention;
- add a phase-scoped prompt instead of making the full prompt longer.

## 7. Adapting to other harnesses

### Claude Code `/goal`

Use the short condition from `GOAL-PROMPT.md` as the goal, then paste the full
prompt as the first message. Keep the goal under 4,000 characters. The evaluator
only sees the transcript, so make sure the agent prints the command outputs.

### Codex / OpenCode / Cursor

Paste the full prompt. If the harness supports a TODO tool, require it. If it
supports subagents, use a fresh-context reviewer for the “analyze/converge”
step, not for the implementation.

### CI

The deterministic gates can run without a model:

```text
node --check web/app.js
python -m py_compile ...
qa/layout_regression.ps1
qa/accessibility_axe.ps1
qa/accessibility_tree.ps1
qa/test_ui_contracts.py
```

The prompt is for the implementation loop; CI is the backstop.

## 8. Maintenance

- Update the prompt when the plan changes, not when a single task changes.
- Keep the phase gates aligned with `05-TEST-PLAN.md`.
- If a gate is removed, say why in `06-ROLLOUT.md`.
- If a new security boundary appears, add it to the constitution first, then
  the prompt.
- Version the prompt in git; do not keep a private copy that drifts.
