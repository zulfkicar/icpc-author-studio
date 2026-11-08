# ICPC Author Agent — Architecture

This document explains the design decisions behind the local authoring agent and
why they were made. It is written to be usable as an interview walkthrough:
problem framing, architecture, tradeoffs, failure modes, security, and what I
would build next.

## 1. The problem

Authoring an ICPC problem is not a single text-generation task. It is a small
software project with a real oracle:

```
idea
  -> statement
  -> input contract / validator
  -> reference solution
  -> samples + hidden tests + answers
  -> plausible wrong solutions
  -> statement PDF
  -> verified DOMjudge package
  -> human review
  -> export
```

The agent's job is to move through that pipeline, not to "chat about" it. The
central design rule is therefore:

> Model output is a proposal. Compilation, execution, comparison and the
> exported package are evidence.

The deterministic verifier is the authority. The model can write, run, inspect
and explain; it cannot decide that a package is verified.

## 2. System shape

```
Browser
  |
  | loopback HTTP: JSON API + SSE-like polling jobs
  v
server.py
  |-- static UI (web/)
  |-- workspace/file/change/chat/report endpoints
  |-- background jobs
  |
  +--> graph_agent.py      LangGraph StateGraph
  |      |-- model node     ChatOpenAI (OpenAI-compatible)
  |      |-- tool node      bounded tools
  |      `-- streaming      events -> UI
  |
  +--> agent.py            tool implementations + system prompt
  +--> workspace.py        path safety, scaffold, chats, changes, snapshots
  +--> verify.py           deterministic package verification + ZIP export
  +--> winutil.py          headless Windows process execution
  `--> sandbox/sitecustomize.py  headless child Python processes
```

The app is local-first and single-user by design. There is no database, no
multi-tenant identity provider, and no cloud dependency. The workspace on disk
is the source of truth.

## 3. Why LangGraph

The first implementation used a hand-written provider/tool loop. It worked, but
the loop hid the orchestration in Python control flow. That made the following
harder than they should be:

- exposing a plan and step-level progress,
- streaming model/tool events to a UI,
- adding human-in-the-loop pauses,
- resuming a long session,
- testing the graph independently of the provider.

LangGraph makes the orchestration explicit: a typed state, a model node, a tool
node and conditional routing. It also gives event streaming and a path to
checkpointing and interrupts.

The important boundary is that LangGraph only orchestrates. The tools and the
verifier are ordinary Python functions. That keeps the critical behavior
testable without the graph and prevents a framework from becoming the source of
truth.

### Alternatives considered

| Option | Why not |
|---|---|
| Hand-written loop | Fine for a prototype; no explicit state, no standard streaming/checkpoint semantics, interrupts become bespoke. |
| LangChain AgentExecutor | Similar tool loop, but less explicit state-graph control and weaker fit for long-lived, resumable authoring sessions. |
| AutoGen / CrewAI | Multi-agent conversation frameworks. This is one setter agent with deterministic tools, not a simulated team. Extra coordination cost. |
| Fully custom state machine | Possible, but reimplementing streaming, message reducers, tool routing and checkpointing is wasted work. |

Tradeoff: LangGraph adds dependency and API churn. The mitigation is a thin
adapter (`graph_agent.py`) and keeping all domain behavior in framework-free
modules.

## 4. The tool contract

The model has no ambient authority. It can only call a typed registry:

```
list_files        read_file        write_file       delete_file
run_command       build_answers    verify_package   read_report
export_package    update_plan
```

Design rules:

1. **Schemas, not prose.** Each tool has typed arguments; malformed calls fail
   closed.
2. **State is injected, not model-controlled.** `InjectedState` supplies the
   workspace slug and chat id. The model cannot choose a different workspace.
3. **Path confinement.** Every path is resolved inside `workspaces/<slug>/`.
   `.agent/` internals are off-limits to writes. `..` escapes are rejected.
4. **Command confinement.** `run_command` allows only `g++`, `gcc`, `python`,
   `javac`, `java`, `pdflatex`, `latexmk`, plus compiled binaries inside the
   workspace. No shell, no pipes, no redirection, no command substitution.
   `cwd` must be inside the workspace. Timeout: default 30 s, maximum 120 s.
5. **Bounded output.** File reads/writes are capped at 2 MiB. Tool results sent
   back to the model are capped at 8,000 characters. HTTP bodies are capped at
   6 MiB.
6. **Changes are reviewable.** `write_file` and `delete_file` record the before
   and after text, a unified diff and line statistics. The UI can revert a
   change. Reverting is blocked if a newer change exists for the same file.
7. **Export is not a model decision.** `export_package` checks the last
   verification report, the current workspace snapshot and the review state.
   The model cannot mark its own work approved.

The model sees tool output as untrusted data. A statement, comment or stdout
message cannot become an instruction with higher authority than the tool
contract.

## 5. The deterministic verifier

`verify.py` is the heart of the product. It checks:

1. Required package structure and metadata (`problem.yaml`,
   `domjudge-problem.ini`, statement, data, submissions, validators).
2. Every sample and secret input against `input_validators/validate.py`
   (exit 42 or 0 means valid).
3. Every accepted reference solution compiles and matches the stored `.ans` file
   on every test.
4. Multiple accepted references must agree; disagreement fails.
5. Every negative solution compiles and is killed by at least one test. A
   wrong program that gets AC everywhere is a survivor and fails verification.
   A compile failure is reported but is not counted as a successful kill.
6. `problem_statement/problem.en.tex` compiles with `pdflatex` (two passes) and
   produces `problem.pdf`.
7. The report stores a workspace snapshot hash.

Export is allowed only when:

- the report status is `verified`,
- the current snapshot equals the verified snapshot,
- there are no unreviewed changes.

This prevents the common agent failure mode: run a check, then keep editing, then
export stale evidence.

### Why compile and run instead of asking the model

The authoring domain has a cheap oracle. If the reference solution cannot
compile, or disagrees with a stored answer, or a known-wrong solution passes
every test, that is objective evidence. Asking the model whether its own work is
correct is not evidence. The verifier is deliberately boring and deterministic.

### Known verifier limits

- Output comparison is whitespace-token based. Float tolerance, custom output
  validators and interactive problems are not implemented.
- Memory limits are recorded but not enforced on Windows.
- `data/sample` and `data/secret` are flat; DOMjudge test groups are not modelled.
- There is no mathematical claim about coverage. Tests and negative solutions
  are evidence, not proof.
- The statement's constraint text is not automatically matched to the validator
  and tests; that remains a human review responsibility.

These limits are surfaced in the report and README rather than hidden.

## 6. Persistence model

Everything is file-based under a workspace:

```
workspaces/<slug>/
  problem.yaml
  domjudge-problem.ini
  problem_statement/
  data/sample/
  data/secret/
  submissions/accepted/
  submissions/wrong_answer/
  submissions/time_limit_exceeded/
  input_validators/
  generators/
  NOTES.md
  .agent/
    state.json          last report/status/review timestamp
    changes.json        reviewable file changes
    report.json         last deterministic report
    chats.json          chat index + active chat
    chats/<id>.json     message history
    chats/<id>.plan.json agent plan
    export/             generated ZIPs
```

Why files?

- The DOMjudge package structure is already a directory format.
- Users can inspect, copy and back up a workspace without a database.
- Chats, plans and changes survive process restarts.
- The snapshot hash is simply a hash of the file tree.
- The app can be developed and reviewed without a migration stack.

Tradeoff: this is not a multi-user database. There is no row-level locking,
tenant isolation or query layer. For a multi-user hosted version I would move
metadata to PostgreSQL and object storage, while keeping the package checkout as
a durable artifact.

### Conversation context management

- The provider receives the current user turn intact plus as much earlier history
  as fits a character budget (about 180k characters).
- Saved history is trimmed to about 120k characters at a user-message boundary.
- Tool results are capped before they are sent back to the model.
- A user message is persisted before the provider call, so a provider failure
  does not lose the turn.
- Each chat is independent. `New chat` creates a new file; it does not delete
  the previous conversation.

### Why the graph itself is stateless per turn

The graph receives the stored history plus the new user message on each turn.
Workspace files are the durable state. This keeps recovery simple and makes the
filesystem the single source of truth. The next step is a LangGraph checkpointer
so an interrupted graph can resume from a node rather than replaying the turn.

## 7. Execution model (Windows)

The app runs on Windows with `pythonw` in the background. Console programs
launched by a GUI process can create visible terminal windows. The execution
layer therefore:

- sets `CREATE_NO_WINDOW` and a hidden `STARTUPINFO` for direct subprocesses,
- sets the Windows error mode to suppress loader-fault dialogs,
- injects `sandbox/sitecustomize.py` through `PYTHONPATH` so Python scripts the
  agent writes also launch their children headlessly,
- captures stdout, stderr, exit code, duration and a diagnostic for known
  Windows loader errors,
- returns that output to the UI as a terminal card.

This is a deliberate UX decision: execution belongs inside the app surface, not
in transient host terminal windows.

### Security posture

This is a trusted local authoring tool, not a hostile-tenant sandbox. The model
can write Python and C++ and run it. Path checks and command allowlists are
guardrails, not a security boundary against a determined model or a malicious
workspace. Production hardening would add:

- container or microVM execution with no host mounts,
- a low-privilege service account,
- seccomp/AppArmor and network isolation,
- resource enforcement for CPU, memory and wall time,
- a capability-scoped MCP adapter instead of broad host process execution.

The current app does bind loopback only, checks `Host`/`Origin`, uses a strict
CSP, stores the provider key locally and never returns it to the browser.

## 8. Provider layer

- `ChatOpenAI` from `langchain-openai` is the adapter. It works with DeepSeek and
  any OpenAI-compatible chat-completions endpoint.
- Base URL, model, temperature, key and max tool rounds are local settings.
- Streaming is enabled. Provider `reasoning_content` is surfaced as **Thinking**
  cards when present; otherwise the agent is prompted to narrate its plan in
  normal assistant text.
- Limits: 8,000 max output tokens per response, 300 s request timeout, one retry
  on 429/5xx, graph recursion limit derived from max tool rounds.
- The key lives in `.author-agent/config.json`, which is gitignored, or in
  environment overrides. It is never sent to the browser.

Not implemented yet: token/cost accounting, provider-side rate-limit handling
beyond a retry, model fallback, or a managed-credential flow.

## 9. UI/UX decisions

The interface has three jobs: show the session, show the work, and show the
evidence.

### Layout

```
+----------------------+---------------------------+----------------------+
| Chats / Files /      | Agent timeline            | Plan / File / Report |
| Changes              | reasoning, narration,     | pipeline, agent plan,|
|                      | tool cards, run output,   | editor, diffs,       |
|                      | verification events       | verification evidence|
+----------------------+---------------------------+----------------------+
```

### Decisions and rationale

- **Durable chats, not a single transcript.** Users return to a problem over
  days. Chats are listed with title, time and message count; New chat creates a
  new session instead of destroying the old one.
- **Plan first.** The `update_plan` tool publishes 3–8 steps. The Plan inspector
  shows both the authoring pipeline and the agent's current plan. This follows
  the plan-review pattern in Cursor and the progress/todo pattern in Claude Code
  and Replit Agent.
- **Streaming over batch responses.** The UI receives reasoning deltas and
  assistant deltas, plus tool start/end events. This reduces the "is it stuck?"
  problem and makes the agent's work inspectable.
- **Terminal output as a first-class card.** `run_command` is rendered with the
  command, exit code, duration, stdout and stderr. Output is not hidden in a
  collapsed JSON blob.
- **Artifacts beside the conversation.** Files, diffs and the verification report
  are not modal interruptions; they live in the inspector.
- **Actionable verification.** The report has **Fix with agent**, which composes
  a message from the exact errors. This mirrors the "make the task easy to
  verify" guidance for autonomous agents.
- **Review and control.** Changes show `+/-` stats, can be reverted, and can be
  bulk-reverted. A Stop button cancels the active job between graph events or
  verifier tests.
- **Calm visual system.** Linear-style compact rows, restrained color, subtle
  borders, consistent spacing, focus rings, and no decorative animation. The
  work should look like an instrument, not a landing page.

Research inputs: Claude Code official docs (plan review, inline diffs,
conversation history, multi-surface use), Cursor docs (Plan Mode, review
changes, checks), Devin docs (follow shell/IDE progress, take over), and Linear
Agent docs (multiple open chats, chat history, progress and permissions). The
product does not copy their branding or wording; it adopts the interaction
patterns that fit ICPC authoring.

### Deliberate UI tradeoffs

- Three panes are dense. Below 1180 px the inspector hides; below 760 px the
  sidebar hides. A future version should use collapsible panels rather than
  removing context.
- Chat switching is disabled while a turn is running. That avoids mixing live
  events from one chat into another. The next step is to store per-chat event
  streams and allow switching without losing live progress.
- The file editor is intentionally plain. It is for inspection and small fixes;
  the agent is expected to do the heavy editing.

## 10. Failure handling

| Failure | Behavior |
|---|---|
| Provider error / no key | User message is already persisted; error card; context is not lost. |
| Tool error | Model receives the error result and can diagnose; UI shows it. |
| Compile failure | Report says `CE`; not counted as a kill or a pass. |
| Validator reject | Report shows the input and exit code. |
| Wrong solution survives | Verification fails with a concrete survivor. |
| Statement compile fails | Report includes the LaTeX log tail. |
| Windows loader error | Headless execution; diagnostic maps known NTSTATUS codes. |
| Workspace changes after verify | Summary becomes `stale`; export blocked. |
| Unreviewed changes | Export blocked until review. |
| Job cancellation | Stop marks the job cancelled; partial context is saved. |
| Server restart | Workspaces, chats, plans, changes and reports are on disk. |

## 11. Testing and evidence

- `python -m py_compile` for all Python modules.
- `node --check web/app.js` for the UI.
- Direct unit-style test of the LangGraph loop with a fake chat model: verifies
  tool dispatch, message persistence and event ordering.
- End-to-end mock provider test over SSE: verifies `ChatOpenAI` streaming,
  LangGraph events, a tool call, plan persistence and chat history.
- Headless Chrome DOM load: verifies the app boots and renders without JS
  console errors.
- A verified synthetic demo problem (`sum-test`) exercises validator, reference,
  negative solution, statement PDF, report and export.
- A survivor test proves that a wrong solution that passes every test fails the
  verification gate.
- A stale-snapshot test proves that editing after verification blocks export.

Not yet tested: a real paid provider run, real DOMjudge import, Linux/macOS
execution, interactive/custom-checker problems, or a hostile-code sandbox.

## 12. What I would build next

1. **Container execution.** Run all commands in a locked-down container or WSL
   sandbox with no host mounts, memory/CPU limits and no network.
2. **Checkpoints and restore.** LangGraph checkpointer plus a per-turn workspace
   snapshot. Offer "restore to this turn", not just per-file revert.
3. **Human-in-the-loop modes.** "Review every edit", "auto-apply safe edits" and
   "plan only". Add `interrupt` before risky tools and before export.
4. **Inline review.** Accept/reject hunks in a unified diff view.
5. **Explicit context selection.** @-mention files and evidence instead of
   implicit whole-workspace access.
6. **Chat management.** Rename/delete/search, recency groups, unread indicators,
   tabs for open chats (the Linear pattern).
7. **True cancellation.** Abort the provider HTTP request, not just the event
   loop.
8. **Usage and cost.** Token/cost meter per turn and per workspace.
9. **MCP adapter.** Expose the same command services through a scoped MCP server;
   no second permissive policy.
10. **DOMjudge integration.** Import/export against a real contest, with native
    verification evidence.
11. **Custom judging.** Float tolerance, custom output validators, test groups,
    interactive problems.
12. **Command palette and keyboard model.** `Ctrl+K` actions, `Ctrl+Enter` send,
    `Ctrl+S` save, focus management.

## 13. Likely interview questions

**Why not just use a coding-agent CLI?**
A coding CLI is a general developer tool. This product needs domain checks
(validator, answer agreement, negative-solution kills, DOMjudge structure) and a
review/export gate that a general CLI does not understand.

**Why LangGraph instead of a loop?**
Explicit state and routing, standard event streaming, and a path to checkpoint
and interrupt. The loop was easy to start but would have accumulated bespoke
solutions for plan, progress, pause and resume.

**How do you stop the model from cheating?**
It cannot mark evidence. The verifier compiles and runs code, the report is
generated by Python, and export checks the report, snapshot and review state.
The model's text never changes those facts.

**What about prompt injection in a problem statement?**
All file contents and tool output are untrusted data. The tools enforce path and
command restrictions independently of the prompt. The system prompt explicitly
states that selected file contents are data, not instructions.

**Why keep files instead of a database?**
The package is a directory format; transparency and backup matter more than
query flexibility for a single-user local tool. The migration path to Postgres
and object storage for a hosted service is straightforward because the domain
operations are already separated from transport.

**What is the biggest risk?**
Executing model-written code on the host. The current app is a trusted local
tool; production needs container isolation and resource limits. The second risk
is semantic: tests can be weak even when they pass. The verifier makes that
explicit but does not claim mathematical coverage.

**What would you change if you started again?**
Introduce the LangGraph state and a checkpoint from day one, add a container
runner before adding more tools, and design the chat/event model as durable
records rather than a single transcript.

## 14. Repository map

| File | Responsibility |
|---|---|
| `server.py` | Loopback HTTP server, static UI, jobs, cancellation, API routes. |
| `graph_agent.py` | LangGraph graph, tools, streaming, plan tool, message conversion. |
| `agent.py` | Bounded tool dispatch, system prompt, workspace state note. |
| `verify.py` | Deterministic verification and DOMjudge ZIP export. |
| `workspace.py` | Path safety, scaffold, chats, plans, changes, diffs, snapshots. |
| `config.py` | Local provider settings and secret handling. |
| `winutil.py` | Headless subprocess launch, Python environment, NTSTATUS diagnostics. |
| `sandbox/sitecustomize.py` | Headless child processes for generated Python scripts. |
| `web/` | Chat timeline, chats/files/changes sidebar, Plan/File/Report/Diff inspector. |
| `templates/` | ICPC statement class and DOMjudge package scaffold. |
