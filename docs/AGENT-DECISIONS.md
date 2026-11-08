# Agent Architecture Decisions — research memo

Status: **research complete; implementation not started**  
Date: 2026-11-08  
Pinned versions used for inspection and spikes: `langgraph 1.2.20`,
`langchain 1.4.9`, `langchain-core 1.7.6`, `langchain-openai 1.7.4`,
`langgraph-checkpoint-sqlite 3.1.3`.

This memo resolves the open decisions in
`docs/AGENT-IMPROVEMENT-PLAN.md`. It is based on official documentation, local
source inspection of the pinned packages, and small executable spikes. It does
not modify runtime code.

## 1. Executive decision

**Migrate the agent from `create_react_agent` to `langchain.agents.create_agent`
before implementing durable state.**

Why:

- `create_react_agent` is deprecated in LangGraph 1.0 and is scheduled for
  removal in 2.0.
- `create_agent` is the supported harness and ships built-in middleware for the
  exact concerns in the plan:
  - `HumanInTheLoopMiddleware` for approve/edit/reject before tools,
  - `SummarizationMiddleware` for token-aware compaction,
  - `TodoListMiddleware` for a structured task list,
  - `ModelCallLimitMiddleware` and `ToolRetryMiddleware` for limits.
- The HITL spike passed: an export tool was interrupted before execution,
  resumed with `Command(resume=...)`, and ran exactly once with valid history.
- The cost is a one-time refactor, a new `langchain` dependency, a rewritten
  streaming adapter, and a custom async tool-error middleware.

If the project deliberately stays on LangGraph 1.x for a short-lived prototype,
pinning `langgraph==1.2.20` and keeping `create_react_agent` is possible, but the
team would be building new architecture on a deprecated API and would have to
implement HITL/summarization themselves. That is not the recommended path for a
long-lived product.

## 2. Spike evidence

| Spike | Result | Evidence |
|---|---|---|
| S1 durable async checkpoint | **PASS** | `AsyncSqliteSaver` + `create_react_agent`; turn 1 stored 2 messages, turn 2 saw 4, reopening the DB still showed 4. `thread_id` is the persistent cursor. |
| S2 Command tool state update | **PASS** | A tool returning `Command(update={"plan": [...], "messages": [ToolMessage(..., tool_call_id=...)]})` updated state and produced roles `human/ai/tool/ai`. |
| S4 HITL middleware | **PASS (batched + per_call)** | `create_agent` + `HumanInTheLoopMiddleware(interrupt_on={"export_package": ...})`; `ainvoke` returned `GraphOutput.interrupts`. Batched resumes with `{"decisions":[...]}`; per-call resumes with `{interrupt.id: {"type":"approve"}}`. In both cases the side effect ran once and history stayed valid. |
| S7 tool-error middleware | **PASS** | `create_agent`'s internal ToolNode raises by default. A custom `AgentMiddleware` with both `wrap_tool_call` and `awrap_tool_call` catches the exception and returns an error `ToolMessage`; the model recovers and history remains valid. |
| S3 summarization | **SOURCE + pending runtime** | `SummarizationMiddleware` has token/message triggers and explicitly advances past ToolMessages to preserve AI/Tool pairs. A runtime spike with our `AuthorState` and pinned context is still required. |
| S5 usage metadata | **PENDING** | `AIMessage.usage_metadata` must be checked with the real provider; v3 message-finish usage is optional; absence must be labelled unknown. |
| S6 migration/concurrency | **PENDING** | Seeding an old chat and running two jobs on one workspace under `AsyncSqliteSaver` still needs a spike. |
| S8 event streaming + interrupts | **PASS via v2 + `aget_state`** | `astream_events(version="v2")` does not emit an `__interrupt__` event, but after the run `agent.aget_state(config).tasks[].interrupts` contains the HITL payload and `next` points at the paused node. Resume with `Command(resume={"decisions":[...]})` works and the side effect runs once. v3 `astream_events` is available but emits a **BetaWarning** in 1.2.20 and uses different async projection/resume shapes. |

Reproducible spike shape (S2/S4/S7):

```python
from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

class AuthorState(AgentState):
    plan: list[str]

@tool
def export_package(tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    # interrupt_on is handled by the middleware before this body runs
    return Command(update={"messages": [ToolMessage("exported", tool_call_id=tool_call_id)]})

agent = create_agent(
    model,
    tools=[export_package],
    state_schema=AuthorState,
    middleware=[HumanInTheLoopMiddleware(
        interrupt_on={"export_package": {"allowed_decisions": ["approve", "reject"]}},
        interrupt_mode="per_call",
    )],
    checkpointer=InMemorySaver(),  # AsyncSqliteSaver in production
)
```

## 3. Decisions

### D1. Use `create_agent`, not deprecated `create_react_agent`

**Options**

| Option | Assessment |
|---|---|
| A. Keep `create_react_agent` and pin LangGraph 1.x | Fastest short-term, but builds on a deprecated API; custom pre-model hook and HITL code required; removed in LangGraph 2.0. |
| B. Migrate to `create_agent` + middleware | **Recommended.** Supported path; built-in HITL, summarization, todo, call limits, retries; one-time refactor; new `langchain` dependency. |
| C. Hand-built `StateGraph` with custom nodes | Maximum control, but reimplements routing/tool/middleware behavior and increases maintenance. |

**Recommendation:** B.

**Consequences**

- Add `langchain==1.4.9` (pin) to `requirements.txt`.
- Replace `create_react_agent` with `create_agent`.
- Replace `pre_model_hook` with middleware:
  - a custom `PinnedContextMiddleware` for prompt sections,
  - the built-in `SummarizationMiddleware` for history compaction.
- Add a custom `ToolErrorMiddleware` with **both** sync and async hooks. This is
  mandatory: the spike showed `create_agent`'s internal ToolNode raises by
  default, and an async agent requires `awrap_tool_call`.
- Add `ModelCallLimitMiddleware` as a safety bound.
- Keep the v2 event adapter; add `aget_state`-based paused-task detection for
  HITL (see D7). v3 is beta and deferred.
- Keep the deterministic verifier and all review/export gates.

**Confidence:** high on API suitability; medium on migration effort.

### D2. Durable checkpointer is `AsyncSqliteSaver` per workspace

**Decision:** use `workspaces/<slug>/.agent/checkpoints.sqlite`,
`thread_id = chat_id`, with `AsyncSqliteSaver.from_conn_string(...)`,
`await saver.setup()`, and a new connection per server job. Keep per-workspace
job serialization. Use durability `"sync"` for export/approval work.

**Options**

| Option | Assessment |
|---|---|
| In-memory saver | No restart resilience; rejected. |
| One global SQLite DB | Thread IDs collide across workspaces; harder isolation; rejected. |
| Per-workspace SQLite | **Recommended.** Local, simple, isolated, easy backup. |
| Postgres saver | Right for multi-user hosted later; not needed now. |

**Evidence:** S1 passed across connection close/reopen. `delete_thread` and
`list` exist. There is no automatic retention policy; add pruning.

**Confidence:** high.

### D3. Checkpointer is the authoritative chat state

**Decision:** the checkpointer is authoritative for messages, plan/todos, brief,
decisions and verification state. `.agent/chats.json` remains the index/title/
active-chat record. Keep a JSON transcript mirror for backup/export only.

**Why:** two authoritative stores would drift. The spike proved the checkpointer
can supply both the conversation and the state across restarts.

**Migration:** seed a checkpoint thread from the existing `chats/<id>.json` once,
after backing it up. If seeding fails, keep the chat visible in legacy read-only
mode; never write a corrupted thread. Add a `delete_thread`/prune path for chat
deletion and retention.

**Confidence:** high.

### D4. HITL uses `HumanInTheLoopMiddleware`

**Decision:** use `create_agent` + `HumanInTheLoopMiddleware`:

```python
HumanInTheLoopMiddleware(
    interrupt_on={
        "export_package": {"allowed_decisions": ["approve", "reject"]},
        # Only when review mode is enabled:
        # "write_file": {"allowed_decisions": ["approve", "edit", "reject"]},
        # "delete_file": {"allowed_decisions": ["approve", "reject"]},
    },
    interrupt_mode="per_call",
)
```

**Why:** the built-in middleware handles approve/edit/reject, creates artificial
ToolMessages for rejected calls, validates decisions, and uses LangGraph
interrupts with a checkpointer. S4 passed.

**UI contract:** in `per_call` mode each paused call is a
`ToolApprovalRequest` (`type`, `tool_call_id`, `name`, `args`, `description`)
with its own interrupt ID; resume with
`Command(resume={interrupt.id: {"type": "approve"}})` (validated with v2).
In `batched` mode the payload is a `HITLRequest` with `action_requests` and
`review_configs`; resume with `Command(resume={"decisions":[...]})`.
Use `per_call` for clarity and future default behavior.

**Keep:** the deterministic export/snapshot/review gates. Approval is an
additional human checkpoint, not a replacement for evidence.

**Rejected alternative:** custom `interrupt()` inside each tool. It works but
duplicates the built-in implementation and must maintain its own approve/edit/
reject/reject-message logic.

**Confidence:** high.

### D5. Compaction uses `SummarizationMiddleware` + `PinnedContextMiddleware`

**Decision:**

- Use the built-in `SummarizationMiddleware` for long-history compaction. It
  supports `trigger` by tokens/messages/fraction, `keep`, a custom
  `token_counter`, and a summarizer model. Source inspection shows it advances
  past ToolMessages to avoid splitting AI/Tool pairs.
- Add a custom `PinnedContextMiddleware` with `wrap_model_call` and
  `awrap_model_call` that injects a `SystemMessage` containing:
  - role and invariants,
  - workspace facts and measured limits,
  - brief, requirements, decisions, open questions,
  - current todos/plan,
  - latest verification summary,
  - selected context manifest,
  - mode checklist.
  It must not mutate state; it only overrides the model request.
- Configure a conservative token trigger and keep count; use a cheap summarizer
  model or a configured model. Store summary provenance in the transcript; never
  let the summary replace the verifier report.

**Rejected alternative:** custom `pre_model_hook`. That hook is specific to the
deprecated `create_react_agent`. `create_agent` uses middleware instead. A custom
non-destructive compaction middleware is possible, but the built-in summary
already solves the hard ToolMessage-pair problem.

**Open spike:** validate SummarizationMiddleware with `AuthorState`, pinned
context, tool calls and the real provider. Check that the summary does not drop
the initial problem statement/constraints (they must be in the pinned brief).

**Confidence:** medium-high.

### D6. Agent plan uses `TodoListMiddleware`; the authoring pipeline stays derived

**Decision:** use `TodoListMiddleware` for the agent’s operational task list
(`write_todos`, state `todos` with `content`/`status`). Keep the authoring
pipeline in the UI as a deterministic projection of files/report/limits. Do not
keep a third “plan” sidecar.

**Why:** the built-in todo tool uses the exact `Command` + `ToolMessage` +
`InjectedToolCallId` pattern the plan proposed, and it is maintained. The UI can
map `todos` to the current Plan panel. The pipeline (statement, validator,
reference, tests, negative solutions, limits, verify) is derived from evidence,
not model text.

**Alternative:** keep the custom `update_plan` and sidecar. It works today, but
after `create_agent` migration it duplicates built-in behavior. A compatibility
adapter can display the old sidecar during migration, then retire it.

**Confidence:** medium-high.

### D7. Keep v2 event streaming; detect interrupts from `aget_state`

**Decision:** keep the existing `astream_events(version="v2")` adapter for
token/tool streaming. When the stream ends, call
`agent.aget_state(config)` and inspect:

- `state.next` — non-empty means the graph is paused,
- `state.tasks[*].interrupts` — the `HITLRequest`/approval payloads,
- `state.values` — the durable state so far.

Resume with `Command(resume=...)` using the middleware’s expected shape:
`{"decisions":[...]}` for `batched`, or a map keyed by interrupt ID for
`per_call`.

**Why not v3 now:** in the pinned `langgraph 1.2.20`, v3 event streaming emits a
`LangChainBetaWarning` (experimental). It also changes async projections to
methods and has a different resume shape. v2 already gives message/tool
streaming, and `aget_state` reliably exposes the paused task. This avoids
migrating the UI to a beta protocol while HITL is being introduced.

**Future:** revisit v3 when it is stable and if live interrupt-projection events
are needed. Do not run the graph twice to get both v2 and v3 streams.

**Confidence:** high for the v2 path; v3 is a later cleanup.

### D8. Usage is reported, not inferred

**Decision:** read `AIMessage.usage_metadata` / v3 message-finish usage when the
provider returns it. Store per-turn `input_tokens`, `output_tokens`,
`total_tokens`, `cached_tokens` if present, provider/model and a status of
`actual | estimated | unknown`. Do not derive billing from rate-limit deltas or
assume provider-wide usage.

**Confidence:** high.

### D9. Evaluation harness is part of Phase 1a

**Decision:** build the harness before broad refactoring:

- 3–5 synthetic/public problems with known packages.
- Metrics: verified rate, tool rounds, tokens, wall time, reference
  disagreements, negative survivors, stale/export correctness, tool failures.
- Mock-provider run in CI; a real-provider run manually with a configured budget.
- Store JSON results and compare to a baseline; fail CI on regressions.

**Confidence:** high.

### D10. Reviewer subgraph is deferred and constrained

**Decision:** defer the reviewer/test-designer subgraph until the durable session,
HITL and eval are stable. When added:

- proposal-only output (edge cases, ambiguity notes),
- no approve/export/rejudge authority,
- no hidden test access unless explicitly authorized,
- separate context and budget.

**Confidence:** high.

## 4. Recommended implementation order

1. **Phase 0 spikes** (complete the pending items): S3 summarization runtime,
   S5 usage, S6 migration/concurrency, plus the `create_agent` migration spike
   with our actual tools and `AsyncSqliteSaver`. S8 already passed with v2 +
   `aget_state`; v3 is deferred.
2. **Migration shell:** add `langchain==1.4.9`; replace the graph factory with
   `create_agent`; add `ToolErrorMiddleware` (sync + async), `ModelCallLimitMiddleware`,
   `PinnedContextMiddleware`, and the existing tools. Keep the current v2 event
   adapter; add `aget_state`-based paused-task detection for HITL.
3. **Phase 1a:** `AsyncSqliteSaver` per workspace, authoritative checkpoint,
   `AuthorState`, `TodoListMiddleware`, prompt composition, migration, eval
   harness.
4. **Phase 1b:** `SummarizationMiddleware`, usage events, UI usage panel.
5. **Phase 2:** `HumanInTheLoopMiddleware` for export and review-mode writes;
   approval UI; resume; idempotency tests.
6. **Phase 3:** context tools, @-mentions, prompt modes.
7. **Phase 4:** reviewer subgraph and expanded eval.

## 5. Risks and open questions

| Risk / question | Status / mitigation |
|---|---|
| `create_agent` migration changes graph behavior | Spike with actual tools, state, checkpointer before rewriting the app. Keep the old graph behind a flag for one release. |
| Tool errors abort `create_agent` | Mandatory `ToolErrorMiddleware` with both `wrap_tool_call` and `awrap_tool_call`; S7 passed. |
| Summarization drops constraints/tool pairs | Pinned brief/plan in the system prompt; source shows tool-pair-safe cutoffs; S3 runtime spike. |
| Interrupt UI needs the paused task | Use `aget_state(config).tasks[].interrupts` after the v2 stream; v3 is beta and deferred. |
| Checkpoint growth | Retention/prune; DB size metrics; backup/restore tests. |
| Migration corrupts chats | Backup, seed once, legacy fallback, explicit errors. |
| Hidden test leakage | Context manifest, no secret content in summaries/usage, reviewer scope. |
| Double resume/export | Durable pending action; idempotent approval; deterministic export gate. |
| Eval budget | Mock CI + manual real baseline with a configured cap. |

## 6. Decisions summary

| ID | Recommendation | Confidence |
|---|---|---|
| D1 | Migrate to `create_agent` + middleware | High / medium effort |
| D2 | `AsyncSqliteSaver` per workspace, `thread_id=chat_id` | High |
| D3 | Checkpointer authoritative; JSON index/mirror | High |
| D4 | Built-in HITL middleware; keep deterministic gates | High |
| D5 | Built-in summarization + custom pinned prompt middleware | Medium-high |
| D6 | Built-in todo list; pipeline remains derived | Medium-high |
| D7 | Keep v2 streaming; detect HITL via `aget_state`; defer v3 | High |
| D8 | Provider usage labelled actual/estimated/unknown | High |
| D9 | Eval harness in Phase 1a | High |
| D10 | Reviewer deferred, proposal-only | High |

## 7. References

- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)
- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [LangGraph event streaming](https://docs.langchain.com/oss/python/langgraph/event-streaming)
- [LangChain agents](https://docs.langchain.com/oss/python/langchain/agents)
- [LangChain middleware](https://docs.langchain.com/oss/python/langchain/middleware)
- [LangChain models / usage metadata](https://docs.langchain.com/oss/python/langchain/models)
- Local source: `langchain.agents.factory`, `langchain.agents.middleware.*`,
  `langgraph.prebuilt.chat_agent_executor`, `langgraph.prebuilt.tool_node`,
  `langgraph.checkpoint.sqlite.aio`.
