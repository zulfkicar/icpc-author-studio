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
  -> measured time / memory limits
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
  +--> graph_agent.py      LangChain create_agent runtime
  |      |-- model node     ChatOpenAI (OpenAI-compatible)
  |      |-- tool node      bounded tools
  |      |-- middleware     pinned context, todo, HITL, summarization, errors
  |      `-- checkpointer   AsyncSqliteSaver per workspace
  |
  +--> agent_state.py       typed working-memory state
  +--> agent_middleware.py  pinned context + tool-error middleware
  +--> agent.py            tool implementations + system prompt
  +--> workspace.py        path safety, scaffold, chats, changes, snapshots
  +--> verify.py           deterministic package verification + ZIP export
  +--> winutil.py          headless Windows process execution
  `--> sandbox/sitecustomize.py  headless child Python processes
```

The app is local-first and single-user by design. There is no multi-tenant
identity provider and no cloud dependency. The workspace on disk is the source
of truth for the package; the per-workspace SQLite checkpoint is the durable
conversation state. Both are local.

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
run_command       build_answers    measure_limits   verify_package
read_report       export_package   search_workspace list_tests
report_summary    write_todos      update_brief     record_decision
set_focus         review_package
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
6. Time and memory limits were measured from the accepted reference runs, not
   guessed at problem creation. The measured values are written to
   `problem.yaml`, `domjudge-problem.ini` and the statement.
7. `problem_statement/problem.en.tex` compiles with `pdflatex` (two passes) and
   produces `problem.pdf`.
8. The report stores a workspace snapshot hash.

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
- Memory limits are measured but not enforced on Windows.
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
    chats/<id>.json     message mirror (UI/backup)
    chats/<id>.plan.json agent plan (mirrored from todos)
    checkpoints.sqlite  LangGraph AsyncSqliteSaver (authoritative agent state)
    pending/<id>.json   pending human approvals
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

- The checkpointer stores the full message state plus working memory.
- `SummarizationMiddleware` compacts old history (30k-token trigger, keep the
  latest 12 messages) using the configured provider. It is tool-pair safe.
- `PinnedContextMiddleware` re-injects the brief, decisions, requirements, open
  questions, focus, mode, todos, selected-file snippets and verifier evidence on
  every model call. Compaction cannot erase those facts.
- Tool results are bounded by each tool; `read_file` supports line ranges and
  `search_workspace` returns bounded snippets.
- A failed turn's user message is preserved in the visible mirror; incomplete
  tool-call groups are removed from the checkpoint before the next model call.
- Each chat has its own `thread_id`; `New chat` creates a new thread and does not
  delete the previous one.

### Durable checkpoints and migration

`graph_agent.py` opens `<workspace>/.agent/checkpoints.sqlite` with
`AsyncSqliteSaver` and uses the chat id as `thread_id`. On a new thread it seeds
from the existing JSON chat mirror, including the plan as todos. On later turns
it sends only the new user message; the checkpointer supplies history and
working memory. The JSON chat/plan files are a UI and backup mirror, written
after each turn; the checkpoint is authoritative for the agent.

Human-in-the-loop pauses are real graph pauses: the assistant tool call remains
pending, `pending/<id>.json` records the interrupt, and the UI resumes with
`Command(resume={interrupt_id: decision})` for per-call mode. The runtime skips
checkpoint repair for these paused tasks; it repairs only crashed/recursion
limited turns. One persistent event loop is used for all turns so provider
clients do not outlive a closed `asyncio.run` loop.

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

## 8. Deployment

The app is packaged as a single container:

- `Dockerfile`: `python:3.13-slim-bookworm` plus g++, the JDK, latexmk and TeX
  Live packages (`lmodern` included).
- `docker-compose.yml`: one service, published to `127.0.0.1:8787`, healthcheck,
  `init`, `restart: unless-stopped`, `no-new-privileges`.
- Runs as UID 1000 (`app`), not root.
- Bind-mounts `./workspaces` and `./.author-agent` so existing problems, chats
  and the provider key carry over. Named volumes are an alternative for an
  isolated install.
- `.dockerignore` excludes `.author-agent`, `workspaces`, `.env`, keys, logs and
  build artifacts, so the image never contains private problem data or the API
  key.
- `.env` is optional; the key can also be entered in Settings and stored in the
  state directory.

The container is the process boundary, not a per-submission sandbox. Model-written
code runs as the app user inside the container and can see the mounted
workspaces. For a multi-user service, run each submission in a separate
container or microVM with a read-only checkout and no shared mounts.

## 9. Provider layer

- `ChatOpenAI` from `langchain-openai` is the adapter. It works with DeepSeek and
  any OpenAI-compatible chat-completions endpoint.
- Base URL, model, temperature, key and max tool rounds are local settings.
- Streaming is enabled. Provider `reasoning_content` is surfaced as **Thinking**
  cards when present; otherwise the agent is prompted to narrate its plan in
  normal assistant text.
- One persistent event loop is shared by all turns; per-turn model clients are
  closed after use. `Accept-Encoding: identity` avoids a streaming decoder bug
  in the pinned `httpx2`/OpenAI dependency set.
- Limits: 8,000 max output tokens per response, 300 s request timeout, one retry
  on 429/5xx, model-call limit from `maxToolRounds`, and a wider graph step budget
  because middleware nodes add steps.
- `AIMessage.usage_metadata` is accumulated per turn and emitted as a usage
  event; absent usage is labelled unreported. There is no cost meter.
- The key lives in `.author-agent/config.json`, which is gitignored, or in
  environment overrides. It is never sent to the browser.

Not implemented yet: provider-side rate-limit handling beyond a retry, model
fallback, or a managed-credential flow.

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
- **Plan first.** The `write_todos` tool maintains the task list; the runtime
  mirrors it into the per-chat plan. The Plan inspector
  shows both the authoring pipeline and the agent's current plan. This follows
  the plan-review pattern in Cursor and the progress/todo pattern in Claude Code
  and Replit Agent.
- **Streaming over batch responses.** The UI receives reasoning deltas and
  assistant deltas, plus tool start/end events. This reduces the "is it stuck?"
  problem and makes the agent's work inspectable.
- **Terminal output as a first-class card.** `run_command` is rendered with the
  command, exit code, duration, stdout and stderr. Output is not hidden in a
  collapsed JSON blob.
- **Readable artifacts.** File reads are syntax-highlighted code cards, file
  writes are compact change cards, verification is a summary card, and raw JSON
  is only a collapsed fallback. highlight.js is vendored locally.
- **Lightweight IDE.** The File inspector has View/Edit modes, syntax
  highlighting, and a Run panel that compiles and executes the selected source
  with user-provided stdin. This gives authors a direct local test loop.
- **Resizable panes.** Draggable splitters between the sidebar, chat and
  inspector, with widths remembered in the browser.
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
| Provider error / no key | The user message is preserved in the visible mirror; error card; the checkpoint is repaired before the next turn. |
| Tool error | Async `ToolErrorMiddleware` turns it into a `ToolMessage`; the model can diagnose and the transcript stays valid. |
| Crashed/recursion-limited turn | The next turn removes incomplete assistant/tool groups and orphan tool messages from the checkpoint (while preserving real HITL pauses). |
| HITL approval pending | The graph is paused; `pending/<id>.json` stores interrupts; the UI resumes with the approval decision. |
| Concurrent workspace writes | Jobs are serialized per workspace; metadata files use unique temporary names and atomic replace. |
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
- Direct unit-style tests of the `create_agent` runtime with fake chat models:
  tool dispatch, durable two-turn memory, todo mirror, pinned context, review
  mode and HITL pause/resume.
- Real-provider HTTP smoke test: two consecutive turns with usage metadata.
- Real-provider HITL HTTP test: export paused before the tool, approval resumed,
  the export gate still refused an unverified package, pending state cleared.
- A verified synthetic demo problem (`sum-test`) exercises validator, reference,
  negative solution, statement PDF, report and export.
- A survivor test proves that a wrong solution that passes every test fails the
  verification gate.
- A stale-snapshot test proves that editing after verification blocks export.
- A real-provider eval baseline (`eval/run_eval.py --fixture sum`) authored a
  package; one repair turn removed a negative solution that was actually correct
  for the constraints; the verifier finished green.
- Headless Chrome DOM load: verifies the app boots and renders without JS
  console errors.

Not yet tested: real DOMjudge import, Linux/macOS execution,
interactive/custom-checker problems, or a hostile-code sandbox.

## 12. What I would build next

1. **Container execution.** Run all commands in a locked-down container or WSL
   sandbox with no host mounts, memory/CPU limits and no network.
2. **Restore to a turn.** Checkpoints are durable; add a UI picker to restore
   conversation/workspace state to an earlier turn, not just per-file revert.
3. **Approval modes.** Export and reviewed writes are gated; add "plan only" and
   "auto-apply safe edits" policies.
4. **Inline review.** Accept/reject hunks in a unified diff view.
5. **Richer context.** @-mention files/evidence and pin specific verifier checks
   beyond the current selected-context list.
6. **Chat management.** Rename/delete/search, recency groups, unread indicators,
   tabs for open chats (the Linear pattern).
7. **True cancellation.** Abort the provider HTTP request, not just the event
   loop.
8. **Cost meter.** Token usage is captured; add provider pricing and per-workspace
   cost.
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
| `graph_agent.py` | `create_agent` runtime, middleware, checkpoints, streaming, tools, message conversion. |
| `agent_state.py` | Typed `AuthorState` and working-memory bounds. |
| `agent_middleware.py` | Pinned context and tool-error middleware. |
| `agent.py` | Bounded tool dispatch, system prompt, workspace state note. |
| `verify.py` | Deterministic verification and DOMjudge ZIP export. |
| `workspace.py` | Path safety, scaffold, chats, plans, changes, diffs, snapshots. |
| `config.py` | Local provider settings and secret handling. |
| `winutil.py` | Headless subprocess launch, Python environment, NTSTATUS diagnostics. |
| `sandbox/sitecustomize.py` | Headless child processes for generated Python scripts. |
| `web/` | Chat timeline, chats/files/changes sidebar, Plan/File/Report/Diff inspector, highlighted code viewer and Run panel. |
| `web/vendor/` | Locally bundled highlight.js and theme. |
| `eval/` | Real-provider eval harness, fixtures and generated results. |
| `docs/` | Research/decision docs and LangGraph diagram. |
| `scripts/` | Reliable WSL Docker up/down wrappers. |
| `templates/` | ICPC statement class and DOMjudge package scaffold. |
