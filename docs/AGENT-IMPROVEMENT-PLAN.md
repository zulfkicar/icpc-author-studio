# Agent Improvement Plan — durable memory, context, and human-in-the-loop

Status: **implemented 2026-11-08; remaining items listed below**
Pinned stack: `langchain 1.4.9`, `langgraph 1.2.20`, `langchain-core 1.7.6`,
`langchain-openai 1.7.4`, `langgraph-checkpoint-sqlite 3.1.3`.

> **Implementation update (2026-11-08):**
> - `create_agent` runtime, `AuthorState`, pinned context, todo middleware,
>   `AsyncSqliteSaver` per workspace, checkpoint migration/repair, durable
>   two-turn memory, HITL export approval, review-mode write approval, usage
>   events, context tools, mode selector, selected-file context, reviewer tool
>   and eval harness are implemented.
> - Real-provider smoke test and HTTP HITL test passed.
> - Sum eval authored a package; one repair turn removed a negative solution
>   that was actually correct for the constraints; verification is green.
> - Stress suite `qa/stress_agent.py` passes durability, HITL, review writes,
>   checkpoint repair, summarization trigger, concurrent workspaces,
>   same-workspace serialization, graph/server cancellation, cost and chat
>   management.
> - Remaining: reviewer is a nested read-only agent, not a separate subgraph;
>   v3 streaming deferred; restore-to-turn, inline hunk review, MCP, DOMjudge
>   integration and custom judging are not implemented.

> **Research update (2026-11-08):** read
> [`AGENT-DECISIONS.md`](AGENT-DECISIONS.md) first. `create_react_agent` is
> deprecated; the recommended implementation path is
> `langchain.agents.create_agent` with middleware. This supersedes the
> `pre_model_hook` and custom-interrupt details below:
> - prompt/context injection → custom `PinnedContextMiddleware`
> - history compaction → built-in `SummarizationMiddleware`
> - approval → built-in `HumanInTheLoopMiddleware`
> - plan → built-in `TodoListMiddleware`
> - tool errors → custom async `ToolErrorMiddleware`
> - event streaming → keep v2; detect paused HITL tasks via `aget_state`
>   (v3 is beta in the pinned version and deferred)
>
> Spikes S1 (async SQLite), S2 (`Command` tools), S4 (HITL), S7 (tool-error
> middleware) and S8 (v2 pause detection) already passed. S3/S5/S6 remain.

## 1. Purpose

The current agent is a solid tool loop with a deterministic verifier. The gap is
not “more LangChain”; it is **state, memory, context and human control**. This
plan turns the agent from a chat with tools into a durable authoring session
that keeps a coherent project state across days, survives restarts, can pause
for approval, and compacts context without losing the problem’s essential facts.

The deterministic verifier remains the authority. It is not replaced by model
memory or a reviewer.

## 2. Current baseline (source audit)

| Area | What exists now | Gap |
|---|---|---|
| Session transcript | `.agent/chats/<id>.json`; the UI loads/saves it | Graph state is rehydrated manually each turn; no durable LangGraph thread |
| Graph checkpoint | Per-turn `MemorySaver` used only to read final state | No cross-turn checkpoint, no resume, no time travel |
| Plan | `update_plan` writes `.agent/chats/<id>.plan.json`; UI reads it | Plan is **not in the system prompt** after trimming; separate source of truth |
| Working memory | Messages + a short workspace note | No structured brief, requirements, decisions, open questions, focus |
| Context | ~180k chars sent, ~120k saved, 8k tool results, 20k user message | Character-based trimming; no token budget, pinning, summary or retrieval |
| Prompt | One `SYSTEM` string + dynamic state note | No prompt sections/templates, no phase modes, no selected-context manifest |
| Human control | Reviewable changes, revert, snapshot/review export gate, stop | No LangGraph `interrupt`; no approve/reject/resume inside a run |
| Context tools | `list/read/write/delete`, `run_command`, answers, limits, verify, report, export, plan | No `search_workspace`, line-range read, `list_tests`, compact report summary |
| Observability | Streaming events in the UI | No token/cost events, no eval harness, no regression metrics |
| Determinism | Validator, references, negative solutions, statement, limits, snapshot/review gates | Strong; must stay the authority |

## 3. Research findings (official docs + pinned APIs)

### 3.1 Checkpointers and threads

Official: [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence),
[Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers),
[Memory](https://docs.langchain.com/oss/python/langgraph/memory).

- A checkpointer persists graph state at each super-step, organized by
  `thread_id`. It is required for memory, human-in-the-loop, time travel and
  fault tolerance.
- `thread_id` is the persistent cursor. Reusing it resumes a thread; a new value
  starts empty state. With an existing thread, `graph.invoke(input, config)`
  applies new input, `graph.invoke(None, config)` resumes unfinished work, and
  `graph.invoke(Command(resume=...), config)` answers an interrupt.
- `get_state(config)` returns the latest `StateSnapshot`; `get_state_history`
  returns checkpoints; `update_state(config, values, as_node=...)` creates a new
  checkpoint and applies reducers.
- `AsyncSqliteSaver` is the async SQLite implementation; `AsyncSqliteSaver.from_conn_string(path)`
  is an async context manager. Use it with `ainvoke`/`astream`/`astream_events`.
- The saver has `setup`, `get_tuple`, `list`, `put`, `delete_thread`,
  `delete_for_runs`, `get_next_version`. There is no automatic retention policy;
  prune deliberately (custom SQL/`delete_thread`/`delete_for_runs`) and keep
  delta-channel dependencies in mind for future use.
- Durability modes: `exit`, `async`, `sync`. Use `sync` for approvals and
  export-gated work; `exit`/`async` are performance tradeoffs.
- Stores are for **cross-thread, long-term** memory. This plan keeps the working
  brief per chat; a Store is not needed for Phase 1.

### 3.2 `create_react_agent`, state and `pre_model_hook`

Local source inspection of `langgraph.prebuilt.chat_agent_executor`:

- `create_react_agent(..., state_schema=..., prompt=..., pre_model_hook=...)`
  requires a state schema with `messages` and `remaining_steps`.
- When `pre_model_hook` is set, LangGraph creates an input schema with an extra
  `llm_input_messages` channel and adds a `pre_model_hook` node before `agent`.
- The hook should return `{"llm_input_messages": [...]}` plus any state updates.
  The model receives those messages; the durable `messages` channel remains the
  full history. This is exactly the compaction seam.
- The hook runs before every model call in the ReAct loop, including after tool
  results. Summaries/trimming must therefore be deterministic and must preserve
  complete tool-call pairs.

### 3.3 `Command` tools and state updates

Official: [Use the Graph API](https://docs.langchain.com/oss/python/langgraph/use-graph-api).

- `Command(update={...})` from a node or tool updates graph state. `ToolNode`
  supports `Command` outputs.
- A tool that wants to both update state and answer its tool call should return
  `Command(update={..., "messages": [ToolMessage(..., tool_call_id=...)]})`.
  `InjectedToolCallId` from `langchain_core.tools` supplies the id.
- This is the correct way for `update_plan`, `update_brief`, and
  `record_decision` to update real state rather than a sidecar file.
- `Command(resume=...)` is the only command form intended as `invoke`/
  `stream_events` input. Do not pass `Command(update=...)` as a new turn input.

### 3.4 Interrupts

Official: [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts),
[Event streaming](https://docs.langchain.com/oss/python/langgraph/event-streaming).

- `interrupt(value)` pauses the graph and requires a checkpointer plus
  `thread_id`. On resume, the node/tool restarts from the beginning; code before
  `interrupt()` re-executes, so side effects before it must be idempotent.
- Tool-level interrupts are supported and are the right fit for
  `export_package` and optional review-before-write.
- v3 event streaming exposes `stream.interrupted`/`stream.interrupts`, but it
  emits a **BetaWarning** in the pinned `langgraph 1.2.20` and changes the async
  projection/resume shapes. The current v2 adapter does not emit an interrupt
  event, but after the run `aget_state(config).tasks[].interrupts` exposes the
  paused HITL task. S8 passed with v2 + `aget_state`; v3 is deferred.
- Resume with `Command(resume=<value>)` on the same thread. Typed
  `response_schema` (Pydantic model) can validate the approval payload.
- Avoid non-idempotent work before `interrupt`; for export, the interrupt must
  come before building/writing the ZIP. Make resume idempotent (one export per
  approved revision) and store a pending-action record.

### 3.5 Prompts and usage

- `create_react_agent` accepts a prompt callable/Runnable. A callable can compose
  a `ChatPromptTemplate` with a `MessagesPlaceholder("messages")` and explicit
  sections: invariants, brief, plan, verification, selected context, modes.
- `AIMessage.usage_metadata` / streaming content blocks can expose token usage
  when the provider returns it. It is provider-dependent: label actual,
  estimated and unknown; never infer billing from token counts.
- Model profiles (`max_input_tokens`) are available but beta; do not rely on
  them for correctness. Keep a conservative configured token budget.

### 3.6 Event streaming and interrupts

- v3 `stream_events` returns typed projections (`messages`, `values`,
  `subgraphs`, `output`, `interrupts`, `interrupted`, `extensions`), but it is
  experimental in 1.2.20 (BetaWarning) and its async projections/resume shapes
  differ.
- The current UI adapter uses v2 event names (`on_chat_model_stream`,
  `on_tool_start`, `on_tool_end`). v2 does not emit an interrupt event, but after
  the stream ends `aget_state(config).tasks[].interrupts` gives the paused HITL
  payload and `state.next` identifies the paused node.
- S8 passed with v2 + `aget_state`; keep that path. Revisit v3 when stable.

## 4. Design decisions

### D1. Checkpointer is the authoritative session state

Per workspace, use `AsyncSqliteSaver` at:

```
workspaces/<slug>/.agent/checkpoints.sqlite
```

`thread_id = chat_id`. Keep `.agent/chats.json` only for the chat index
(title, timestamps, active chat). Keep a read-only JSON transcript mirror for
backup/export if desired; it is not the source of truth. On first load of an old
chat, seed the thread from the existing JSON once, then stop writing the
authoritative transcript there.

Why per-workspace DB: thread IDs are only unique inside a workspace; per-workspace
DBs simplify isolation, deletion, backup and future tenant separation.

### D2. Structured `AuthorState`

```python
class PlanStep(TypedDict):
    title: str
    status: Literal["pending", "in_progress", "completed"]

class Decision(TypedDict):
    question: str
    answer: str
    rationale: str | None
    source: str | None

class AuthorState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    slug: str
    chat_id: str
    plan: list[PlanStep]
    brief: str
    requirements: list[str]
    decisions: list[Decision]
    open_questions: list[str]
    verification: dict          # compact status/errors/counts/snapshot
    focus: str                  # current objective
    mode: Literal["author", "debug", "review"]
    pending_actions: list[dict]
    rolling_summary: str
    remaining_steps: int
```

Bounds: brief ≤ 4k chars; decisions ≤ 50; requirements ≤ 100; open questions
≤ 50; each item ≤ 500 chars. Validate every `Command` update server-side.

### D3. Tools update state via `Command`

- `update_plan(steps, tool_call_id, state) -> Command(update={"plan": ..., "messages": [...]})`
- `update_brief(brief, tool_call_id, state) -> Command(...)`
- `record_decision(question, answer, rationale, source, tool_call_id, state) -> Command(...)`
- `set_mode(mode, tool_call_id, state) -> Command(...)`
- Keep the existing sidecar plan as a compatibility mirror for the UI during
  migration; remove it when the UI reads state from the checkpointer.

### D4. Prompt composition

A prompt callable builds:

1. role and invariants (deterministic verifier, no invented evidence, no
   approve/export),
2. workspace facts (name, idea, file counts, measured limits),
3. working brief,
4. current plan,
5. latest verification summary and open blockers,
6. selected context manifest,
7. mode-specific checklist,
8. `MessagesPlaceholder("messages")`.

The prompt is built from **pinned state**, not from old messages that may have
been compacted away.

### D5. `pre_model_hook` compaction

- Pin system + brief + plan + latest verification + selected context.
- Keep the last N complete turns (tool call + all its ToolMessages).
- Keep a `rolling_summary` of older user/assistant text; never summarize away a
  tool result without its call, or a call without its result.
- Trigger summarization only above a token threshold; use a cheap model or a
  deterministic summary first. Store the summary in state.
- Return `{"llm_input_messages": [...], ...state updates}`; never mutate
  `messages`.
- Token budget: conservative configured limit; use `tiktoken` for estimation and
  provider usage for reporting, not as the primary budget authority.

### D6. Interrupts

- `interrupt` before export, and optionally inside `write_file`/`delete_file`
  when `mode == "review"`.
- Payload: action, exact paths, revision/snapshot hash, reason, tool call id.
- Resume: `Command(resume={"approved": True/False, "note": ...})`.
- Pending action is stored in state; resume is idempotent; export checks the
  deterministic report/snapshot/review gates again after approval.
- Keep v2 event streaming for tokens/tools; after the stream, read
  `aget_state(config).tasks[].interrupts` to detect the paused HITL task. Resume
  with `Command(resume=...)`. v3 is beta and deferred.

### D7. Context tools and modes

Add bounded tools:

- `search_workspace(query, glob=None, max_results=50)` — paths and snippets, no
  huge dumps.
- `read_file(path, start_line=None, end_line=None)` — e.g. max 400 lines.
- `list_tests()` — names/counts, not secret content by default.
- `report_summary()` — compact status/errors/counts.
- UI @-mentions/context chips; selected context becomes a manifest with
  path/sha256/size, included in the prompt and audit.
- Modes: `author`, `debug`, `review` initially. A mode changes the checklist and
  a few invariants, not the tool authority.

### D8. Evaluation comes before broad refactors

Build a small harness **with Phase 1a**:

- 3–5 synthetic/public problems with known packages.
- Metrics: verified rate, tool rounds, token usage, wall time, reference
  disagreements, negative survivors, stale/export correctness, tool failures.
- Mock-provider run for CI; real-provider run manually with a budget.
- Store JSON results and compare against a baseline; fail CI on regressions.
- Do not claim improvement without these numbers.

### D9. Reviewer subgraph is last and constrained

- Optional reviewer/test-designer subgraph.
- No approve/export authority; no hidden tests unless explicitly authorized.
- Output only proposals (questions, edge cases, ambiguity notes).
- The deterministic verifier remains the authority.

## 5. Phase 0 — required spikes (before implementation)

Each spike is a small script with a pass/fail result recorded in this document.

**S1. Durable async checkpoint**
- `AsyncSqliteSaver` + `create_react_agent` + fake model.
- Turn 1 writes a message; turn 2 with the same `thread_id` sees it.
- Verify `aget_state`/`get_state` behavior and that the DB persists after
  connection close.
- Verify `delete_thread` and a simple retention strategy.

**S2. Command state update**
- A tool returns `Command(update={"plan": ..., "messages": [ToolMessage(...)]})`
  using `InjectedToolCallId`.
- Verify state updated, tool call has a ToolMessage, and history remains valid.

**S3. `pre_model_hook` compaction**
- Hook returns `llm_input_messages`; fake model records what it received.
- Verify durable `messages` remain full, model input is trimmed, and tool pairs
  are never split.

**S4. Interrupt and resume** — **PASS (batched + per_call)**
- `HumanInTheLoopMiddleware` interrupted before export; v2 `astream_events`
  does not emit an interrupt event, but `aget_state(config).tasks[].interrupts`
  (or `GraphOutput.interrupts`) exposes it.
- Batched resume: `Command(resume={"decisions":[...]})`.
  Per-call resume: `Command(resume={interrupt.id: {"type":"approve"}})`.
  The side effect ran once and messages remained valid.

**S5. Usage metadata**
- Fake `AIMessage(usage_metadata=...)` through `on_chat_model_end`; v3 usage is
  optional.
- Verify actual/absent handling and the event shape sent to the UI.

**S6. SQLite concurrency and migration**
- Two jobs on one workspace are serialized by the server; SQLite writes do not
  corrupt.
- Seed a thread from an existing `chats/<id>.json`; verify UI can read state
  from the checkpointer and old chats still open.
- Verify a checkpoint DB backup/restore and `delete_thread`.

## 6. Phase 1a — durable session and working memory

### Dependencies
- Add `langgraph-checkpoint-sqlite==3.1.3` (and its `aiosqlite` dependency) to
  `requirements.txt`.
- Add `langchain==1.4.9` for `create_agent` and built-in middleware.
- No change to the deterministic verifier.

### Work items
1. Add `agent_state.py`: TypedDict/Pydantic models, bounds, validators.
2. Add `checkpoints.py`:
   - per-workspace DB path, `AsyncSqliteSaver` factory,
   - thread lifecycle: create/seed/list/delete/prune,
   - `aget_state` adapter, transcript projection.
3. Modify `graph_agent.py`:
   - replace `create_react_agent` with `create_agent` (see decision memo D1),
   - build graph with `state_schema=AuthorState` extending `AgentState`,
     durable checkpointer,
   - add `ToolErrorMiddleware` (both sync and async hooks),
   - add `ModelCallLimitMiddleware`,
   - add `PinnedContextMiddleware` with sync/async `wrap_model_call`,
   - use built-in `SummarizationMiddleware` (Phase 1b),
   - use built-in `TodoListMiddleware` for the operational plan,
   - remove per-turn `MemorySaver`.
4. New middleware/tools: `PinnedContextMiddleware`, `ToolErrorMiddleware`,
   `TodoListMiddleware` configuration, plus `update_brief`, `record_decision`,
   `set_mode` if the built-in todo list is not sufficient.
5. Server:
   - chat state/transcript reads from checkpoint,
   - migration endpoint/fallback,
   - keep `chats.json` for index/title/timestamps,
   - ensure per-workspace job serialization remains.
6. UI:
   - brief/decisions/requirements/plan display,
   - plan from state, not sidecar,
   - graceful legacy-chat migration state.
7. Eval harness (minimal) from Phase D8.
8. Tests: checkpoint persistence, migration, Command validity, history validity,
   concurrent job serialization, UI reads.

### Acceptance
- Restarting the server does not lose a chat or its plan.
- Turn 2 sees turn 1 without manually re-sending full history.
- `update_plan`/`update_brief`/`record_decision` update state and are visible in
  the UI.
- No chat can have an `AIMessage` tool call without a ToolMessage.
- Existing chats migrate or fail with an explicit, recoverable message.
- Eval baseline is recorded.

## 7. Phase 1b — compaction and usage

- Use the built-in `SummarizationMiddleware` for token/message triggered history
  compaction; it is documented and source-inspected to advance past ToolMessages
  so AI/Tool pairs are preserved.
- Use `PinnedContextMiddleware` to inject the brief, plan/todos, latest
  verification and selected context into the system message on every model call.
- Rolling summary with a conservative token threshold; never split tool pairs.
- Usage events from `on_chat_model_end` (or v3 when stable); label
  actual/estimated/unknown.
- UI usage/cost panel per turn.
- Tests: token budget, tool-pair integrity, summary fallback, usage absent.

## 8. Phase 2 — human-in-the-loop

- Use the built-in `HumanInTheLoopMiddleware` rather than custom `interrupt`
  calls. Configure `interrupt_on={"export_package": {"allowed_decisions": ["approve", "reject"]}}`
  and, in review mode, `write_file`/`delete_file`.
- Use `interrupt_mode="per_call"` (future default) for clear per-action approval.
- In `per_call` mode each paused action is a `ToolApprovalRequest` with its own
  interrupt ID; the UI resumes with
  `Command(resume={interrupt.id: {"type":"approve"}})`.
  In `batched` mode it resumes with `Command(resume={"decisions":[...]})`.
  Reject produces a ToolMessage.
- Keep snapshot/review/export gates deterministic.
- Tests: interrupt/resume, double-click, stale approval, revoked authority,
  malformed resume, rejection, cancellation. Spike S4 already passed for export.

## 9. Phase 3 — context tools and prompt modes

- `search_workspace`, line-range `read_file`, `list_tests`, `report_summary`.
- UI @-mentions/context chips and a hash manifest.
- Prompt sections + `author`/`debug`/`review` modes.
- Tests: path confinement, hidden-test exposure policy, context hashes,
  prompt-size bounds.

## 10. Phase 4 — reviewer and evaluation expansion

- Reviewer/test-designer subgraph with proposal-only output.
- Eval corpus expansion, regression thresholds, cost/latency tracking.
- No reviewer approval/export authority; no hidden tests by default.

## 11. Storage and migration

```
workspaces/<slug>/.agent/
  chats.json                 # index, title, timestamps, active chat
  chats/<id>.json            # legacy transcript / optional mirror
  chats/<id>.plan.json       # compatibility mirror during migration
  checkpoints.sqlite         # authoritative LangGraph state (new)
  report.json
  state.json
```

Migration rules:
1. On chat load, if the checkpoint thread has no state, seed it from
   `chats/<id>.json` once.
2. Do not use `update_state` blindly append a full history twice; test
   reducers and `as_node`. Prefer invoking with the history on a new thread
   before switching the index to checkpoint-backed mode.
3. Keep a backup copy of chat JSON before migration.
4. If migration fails, the chat remains readable in legacy mode and the agent
   refuses to continue until repaired, rather than writing a corrupted thread.
5. Add a retention job for checkpoints; document backup/restore of the SQLite DB.

## 12. Security and privacy

- Checkpoints can contain secret tests, answers, statements and tool output.
  Keep per-workspace DBs local; do not expose them through the public UI list.
- Context manifests must carry hashes and explicit selection; no hidden test
  content in summaries/usage events.
- Reviewer subgraph must not receive hidden tests unless authorized.
- Interrupt payloads contain paths and hashes, not file contents by default.
- No provider key in checkpoints; config remains outside graph state.
- For multi-user hosting, move checkpoints to a tenant-scoped Postgres saver and
  enforce authorization on every read/resume; do not share a thread ID namespace.

## 13. Risks and mitigations

| Risk | Mitigation |
|---|---|
| SQLite locking under concurrent jobs | Keep per-workspace job serialization; one saver connection per job; test concurrency |
| Checkpoint growth | Retention/prune; backup; measure DB size |
| v3 event streaming is beta | S8 passed with v2 + `aget_state`; defer v3 |
| Compaction splits tool pairs | Complete-turn retention tests; never trim inside a tool sequence |
| Summary hallucination | Summarize only message text; pinned verification comes from the report, not the summary |
| Migration corrupts chats | Backup, seed once, legacy fallback, explicit errors |
| Double resume/double export | Durable pending action, idempotent resume, deterministic export gate |
| Reviewer cost/false confidence | Reviewer last, proposal-only, no hidden tests, budgeted eval |
| Hidden test leakage | Context policy, manifest, no secret content in summary/usage, reviewer scope |

## 14. Testing and acceptance gates

- Unit: state bounds, Command updates, prompt sections, compaction, usage.
- Integration: durable two-turn memory, restart, SQLite backup/restore,
  migration, job serialization.
- HITL: interrupt detection, approve/reject, double resume, stale approval,
  cancellation, malformed resume.
- Regression: existing verifier, change/revert/export gates, limits, IDE run.
- Eval: mock-provider CI baseline; manual real-provider run with budget.
- All existing tests must remain green.

## 15. Effort estimate (relative)

- Phase 0 spikes: 1–2 days.
- Phase 1a: 3–5 days.
- Phase 1b: 2–3 days.
- Phase 2: 2–3 days.
- Phase 3: 3–4 days.
- Phase 4: 3–5 days.
- Eval and regression maintenance: ongoing.

Estimates assume one implementer and the existing deterministic verifier/UI.

## 16. Decisions needed before Phase 1a

1. Confirm the checkpointer is the authoritative chat state, with JSON as
   index/mirror.
2. Confirm per-workspace SQLite DBs (recommended) vs one global DB with
   workspace-prefixed thread IDs.
3. Confirm migration vs starting old chats fresh.
4. Confirm review mode default (off recommended) and whether export always
   interrupts.
5. Confirm v2 + `aget_state` pause detection vs a future v3 migration.
6. Confirm eval provider/budget for the real-provider baseline.

## 17. Definition of done

- A chat survives server restart and continues with full state.
- The agent sees the pinned brief, plan and latest verification in every turn.
- The plan/decisions/requirements are state, not stale messages or sidecars.
- Compaction never produces invalid tool-call history.
- Approval can pause and resume export (and optionally writes) durably.
- Usage is visible and labelled; eval metrics are recorded.
- The deterministic verifier remains the authority and all existing gates pass.
- Existing chats migrate or fail safely with a recoverable message.

## 18. References

- [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)
- [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [Use the Graph API / Command](https://docs.langchain.com/oss/python/langgraph/use-graph-api)
- [Event streaming](https://docs.langchain.com/oss/python/langgraph/event-streaming)
- [Streaming](https://docs.langchain.com/oss/python/langgraph/streaming)
- [Memory](https://docs.langchain.com/oss/python/langgraph/memory)
- [LangChain models / usage metadata](https://docs.langchain.com/oss/python/langchain/models)
- Pinned local APIs inspected:
  `create_react_agent`, `ToolNode`, `AsyncSqliteSaver`, `interrupt`, `Command`,
  `pre_model_hook`, `InjectedToolCallId`, `AIMessage.usage_metadata`.
