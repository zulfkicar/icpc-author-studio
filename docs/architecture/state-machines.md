# State machines in the ICPC Author Agent

The ICPC Author Agent has two web interfaces, a chat-native LangGraph engine,
and a classic LangGraph agent. The highest-impact shared transitions are the
lifecycle of a background workspace job and the progression from saved files to
a verified, human-approved judge ZIP. Both now have one backend contract.

## Decision

**Adopt authoritative state at each boundary.** A job and a saved package
each have their own identity, owner and transition rules. The interfaces
render those rules. The agent and consent-gated MCP report tool can read the
same package decision. The LangGraph owners continue to drive conversations,
interrupts and investigations. The [classic UI tables](../STATE-MACHINES.md)
continue to expose state for browser tooling.

| Concern | What improves |
| --- | --- |
| User experience | The ZIP drawer explains whether to verify, review, generate, or download. Cancel and timeout distinguish a requested stop from a settled job. Studio can reconnect to a known job after losing its status. |
| Developer experience | The readiness decision lives in [package_workflow.py](../../author_studio/packages/package_workflow.py). Legal job transitions live in [job_lifecycle.py](../../author_studio/job_lifecycle.py). Both have regression coverage through their real callers. Existing summary fields, job states and routes are still available. |
| Agent experience | Package reports carry a structured `workflow` with a snapshot, blocker, and next action. The agent can tell authors what is needed. Human package approval stays with the author. The durable engine continues to distinguish receipts, evidence and applied effects. |

An all-app rewrite would migrate focus and editor logic, both graph runtimes,
persisted records and tooling at the same time. Its risk is out of proportion
to the two demonstrated defects. Additional frontend observers could improve
visibility, while a stale plain download URL and a late background worker
would still need backend rules. The local and single-writer lifecycles below
remain independently testable through their feature entry points.

## Inventory

This map covers behavior-bearing state in first-party runtime code. Related
presentation flags are grouped with the feature they control. Pure calculation,
static content, third-party internals and QA harness lifecycles are outside
this inventory. “Implicit” means a transition is reconstructed from fields,
records, control flow, or DOM state. Some lifecycles already have explicit
states and guards, and are listed to show where authority sits.

### Studio and shared conversation UI

| Lifecycle | States and transitions | Owner and form |
| --- | --- | --- |
| Conversation selection and draft title | Empty or named draft → create → selected. Switch or reload → hydrate saved run. Rename → save or retry. | [engine.js](../../web/engine.js) uses selection, storage, busy flags and refresh versions. [problem_titles.py](../../author_studio/packages/problem_titles.py) synchronizes title surfaces and compensates when the operation fails. |
| Provider and capabilities | Saved or draft-selected provider → locked to a run. Configured, unconfigured, and demo/worker capabilities are displayed. | Implicit browser selection. Backend run configuration is authoritative. |
| Sending, steering and resuming | Draft → sending → received/applied or retained for retry. Additional messages queue during send. Card answers or failed-input recovery reference specific records. Poll starts, is superseded on a switch, and stops on close. | Browser busy, queue, cursor and epoch. Durable acceptance belongs to [chat.py](../../engine/chat.py) and [input_service.py](../../engine/input_service.py). |
| Linked judge package | Loading → absent, loaded, or failed. Link/create makes a new choice. A superseded response cannot change a newer conversation's link. | [studio.js](../../web/studio.js) keeps loading/error state and a request version. [studio.py](../../author_studio/studio.py) checks the prior link and serializes package creation or rename. |
| Workspace files and tabs | Unopened → loading → read-only or editable. Save → saved, conflicted, or retry with draft. Tabs select, close or reopen. Asynchronous Monaco initialization upgrades the existing fallback editor. | Implicit records keyed by run/path and base hash. Optimistic save checks live in the backend. |
| Conversation artifacts and copy | Current → outdated on a new revision. Copy opens an unpublished destination draft so editing and saving remain distinct. | Browser and [context.py](../../engine/context.py) read artifact identity and revision validity from the ledger. |
| Markdown, display modes and preferences | Read, write or split preview. Chat, Together and Editor modes. Drawers and popovers open, move, close and return focus. Sizes and theme hydrate from local preferences. | Local mode values, native dialog and popover state, and CSS layout. Browser-owned. |
| Formatting, lint and diagnostics | Request on a particular draft → transformed text, diagnostics, unavailable tool, or stale response. | Implicit draft/request identity in [studio.js](../../web/studio.js) and one-shot results in [studio.py](../../author_studio/studio.py). |
| Saved workspace actions | Open Run, Build tests, Verify, Review, Limits, or Export → read current package → submit job or approval → render result in the matching drawer. Run history is per package. | Drawer mode and epochs belong to Studio. The shared job and package contracts govern server effects. |

### Classic workbench and agent

| Lifecycle | States and transitions | Owner and form |
| --- | --- | --- |
| Classic browser workflow | Connection, workspace session, turn, approval, editor, manual run, modal, file load, chat, verification, changes, MCP, settings, mentions, follow, tree, tests and restore. | 18 explicit observer tables in [machines.js](../../web/machines.js). [app.js](../../web/app.js) and the backend still own the actions. The existing DOM and observer API remain compatible. |
| Workbench presentation and queues | Inspector/tab/menu states, palette and onboarding, current or unread job notifications, job event stream, pending send, selected samples, compare view, browser preferences. | Implicit flags, IDs and DOM in [app.js](../../web/app.js). Job event observation now advances by sequence, including when the rolling buffer displaces older entries. |
| Dialog and focus | Closed → active with invoker → submit, reject, dismiss or nested dialog → restore focus. | [dialogs.js](../../web/dialogs.js) and the native dialog stack. |
| File and conversation persistence | Create, select, rename, remove or restore. File revisions create change entries, which may be open, reviewed, partly reverted or fully reverted. | [workspace.py](../../author_studio/packages/workspace.py), snapshot files and change records. Change-log review and snapshot approval are separate facts. |
| Classic agent turn and interruption | Start graph → stream provider and tools → persist turn, pause for clarification/tool approval, fail or cancel. Reply resumes a saved checkpoint and pending record. | [graph_agent.py](../../author_studio/classic/graph_agent.py) graph interrupts are explicit. Async task ownership, stream fallback, and legacy pending records use task handles and guards. |
| Classic context and planning | Assemble context → fit or compact → call/fallback → stream or fail. Plan items move through pending, in progress and done. Skill discovery, activation and tool permission gate applicability. | [agent.py](../../author_studio/classic/agent.py), [agent_state.py](../../author_studio/classic/agent_state.py), [agent_middleware.py](../../author_studio/classic/agent_middleware.py), and [skill_registry.py](../../author_studio/classic/skill_registry.py). Middleware and plan records already expose their own states. |
| Review and restoration | Proposal-only reviewer gives evidence. Applying edits, restoring chat or filesystem snapshots, and verifying restored files follow their own guards and storage. | [graph_agent.py](../../author_studio/classic/graph_agent.py) and [workspace.py](../../author_studio/packages/workspace.py). A checkpoint and a filesystem revision have independent lifetimes. |

### Durable chat engine

| Lifecycle | States and transitions | Owner and form |
| --- | --- | --- |
| Run, continuation and wake | Create → acquire owner epoch → advance, interrupt, wait, wake, reconcile or terminate. Lease changes fence obsolete owners. | Explicit parent and collaboration/investigation/editing/review graphs in [graph.py](../../engine/graph.py) and [graph_state.py](../../engine/graph_state.py), coordinated by [owner.py](../../engine/owner.py) and [lockfile.py](../../engine/lockfile.py). |
| Input sequencing and decision attempts | Receipt and idempotency → interpretation → applied, disambiguation, rejection or supersession. New author input can fence a pending continuation. Model decisions reserve budget, validate typed output and select a safe disposition. | [store.py](../../engine/store.py), [input_service.py](../../engine/input_service.py), [interpretation.py](../../engine/interpretation.py) and [decisions.py](../../engine/decisions.py). |
| Human collaboration | Compose a decision or clarification card → await a bound reply → apply, reject, cancel or supersede. Contributions and explanations carry author/revision provenance. | Explicit interaction and transcript records in [store.py](../../engine/store.py) and [chat.py](../../engine/chat.py), with bounded, revision-aware model context in [context.py](../../engine/context.py). |
| Grants, delegation and handoff | Admit a scoped grant → use, revoke, expire or supersede. Delegation tracks target, budget, return predicate, stage evidence and typed handoff result. | [policy.py](../../engine/policy.py), [input_service.py](../../engine/input_service.py), [stage.py](../../engine/stage.py) and ledger rows. An explanation or a proposed effect carries no grant of its own. |
| Investigation, candidate and evidence | Open claim → plan and dispatch a bounded check → observe pass, mismatch, failed, cancelled, unknown or stale. Findings and review dispositions attach to a revision. | [graph.py](../../engine/graph.py), [worker.py](../../engine/worker.py), [protocol.py](../../engine/protocol.py), and [store.py](../../engine/store.py). Worker status and proof evidence have separate meanings. |
| Model and tool resource use | Reserve → dispatch → measure and settle. Retries draw from bounded attempts, time and tokens. Procedures carry capability and evidence requirements. | [budget.py](../../engine/budget.py), [procedures.py](../../engine/procedures.py) and ledger reservations. |
| Drafted package and autonomous repair | Draft → validate schema and content → check solution against independent oracle → bounded repair or block → publish the current result. | [package_draft.py](../../engine/package_draft.py), [package_check.py](../../engine/package_check.py) and [graph.py](../../engine/graph.py). Proof, candidate evidence and release approval remain distinct. |
| Revision, artifact and projection | Proposal → authorization and generation check → revision event → projection intent → apply, reconcile or conflict. Artifacts become stale when dependencies change. | [store.py](../../engine/store.py) and [projection.py](../../engine/projection.py). Filesystem materialization and SQLite checkpoints have separate recovery rules. |

### Local service and judge boundaries

| Lifecycle | States and transitions | Owner and form |
| --- | --- | --- |
| Job admission and terminal result | Queued → executing → succeeded, paused or failed. Cancellation and deadline each have a pending state. A returned worker or elapsed grace settles a stop. A terminal result stays terminal. | Explicit [job_lifecycle.py](../../author_studio/job_lifecycle.py), synchronized in [server.py](../../author_studio/server.py). Workspace lock ownership can outlive a timeout result. |
| Package verification and human review | Unverified, failed or stale → verify current files → review required → ready to export. Changes invalidate the matching verification and eventually require a new review. | Shared [package_workflow.py](../../author_studio/packages/package_workflow.py) evaluation and snapshot in [workspace.py](../../author_studio/packages/workspace.py). New approvals bind to the saved snapshot. |
| Archive generation and download | Blocked, missing, ready, stale or invalid. A staged ZIP becomes current only after a source and approval check. Download checks eligibility and archive identity again. | [verify.py](../../author_studio/judging/verify.py), [workspace.py](../../author_studio/packages/workspace.py) and [server.py](../../author_studio/server.py). Both old and snapshot-qualified download URLs use the same gate. |
| Individual verification and scoring | Structure and limit evidence → compile statement, validate inputs, run references, check outputs, kill known bad solutions and score test groups. Build tests writes answers from references with disagreement handling. | [verify.py](../../author_studio/judging/verify.py), [package_model.py](../../author_studio/packages/package_model.py), [verification_modes.py](../../author_studio/judging/verification_modes.py), [scoring.py](../../author_studio/judging/scoring.py) and [icpc_spec.py](../../author_studio/packages/icpc_spec.py). Reports record evidence and fixture status separately from the archive. |
| Limits evidence and program execution | Proposed/configured limits → measurement attempt → success/failure; source admission → compile → run → exit, timeout or execution failure. | [verify.py](../../author_studio/judging/verify.py), [workspace.py](../../author_studio/packages/workspace.py), [winutil.py](../../author_studio/winutil.py), and [executor_server.py](../../workers/executor_server.py). |
| External execution adapters | Submit/query/cancel where supported. Normalize queued, compile, runtime, constraint, infrastructure and terminal outcomes without treating unqualified capability as proof. | [isolate_client.py](../../author_studio/judging/isolate_client.py), [isolate_worker.py](../../workers/isolate_worker.py), [judge0_adapter.py](../../author_studio/judging/judge0_adapter.py) and [protocol.py](../../engine/protocol.py). |
| Settings, consent, permission and protocol | Saved and runtime settings resolve provider capability. MCP settings toggle scopes/tools; a request is consented, validated and dispatched or refused. Event ledgers track order, cursor and de-duplication. | [config.py](../../author_studio/config.py), [mcp_consent.py](../../author_studio/mcp_consent.py), [mcp_server.py](../../author_studio/mcp_server.py), and [schemas.py](../../author_studio/schemas.py). |

## Transition contracts and limits

- Package readiness is derived from the saved files, verification receipt and
  review record. A package with an existing legacy review can retain that
  approval for its unchanged verified snapshot. Missing review and a new
  verification snapshot require a bound approval. The workbench shows the
  selected package's current status beside its picker. The picker itself lists
  names because its quick list only carries historical verifier results.
- Verification pins the saved revision after answer generation and statement
  compilation. The statement step itself checks for changes to its inputs.
  Snapshot fences detect changes at those boundaries. App-side writes share
  the workspace lock. Files written directly by another process have no
  shared lock.
- Package job `phase` adds detail to the existing `state` response. Terminal
  status and result are stable. `workerActive` can stay true while a
  cooperative worker is winding down, and the workspace lock still prevents
  another queued mutator from starting. Job lookup is process-local. The
  canonical chat engine has its own durable recovery.
- Package readiness reports the deterministic verifier's result for the
  saved bytes. The supported workflow still has profile-specific capability
  limits, including interactive verification and native V0–V3 delivery.
- The classic workbench mirrors and panel-local state remain separate. The
  backend contracts can be extended at their own boundaries as behavior
  changes, with browser state used for presentation and request ownership.

Regression coverage is in [the Studio API workflow](../../qa/engine_contracts/test_studio_routes.py),
[the workspace lifecycle tests](../../qa/engine_contracts/test_workspace_lifecycle.py),
and [the Author Studio browser record](../design/author-studio/VERIFICATION.md).
