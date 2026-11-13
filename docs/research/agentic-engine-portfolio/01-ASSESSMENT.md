# Independent assessment

Date: 2026-11-13. Labels used throughout: **O** observed in current source, **R** reproduced offline, **I** inference, **P** proposed, **U** unvalidated. A source observation is not a live security or reliability qualification.

## 1. What the engine actually does

`graph_agent.py:930` constructs a LangChain `create_agent` with 23 explicitly registered tools (`TOOLS`, line 469), plus middleware's todo tool. The resulting framework graph alternates model and tools until the model stops, an interrupt occurs, or a limit/error ends execution. There is no explicit authoring-stage graph enforcing the sequence in `prompts/workflow.md`. The three specialist tools invoke a read-only `create_agent` wrapped in a single-node StateGraph (`graph_agent.py:412`). This is genuine agent execution, but the extra wrapper does not create a deeper review method.

Source-derived path for “author this idea” (not an observed model run):

1. `server.py:482` launches a workspace-locked job. `graph_agent.py:771` opens a SQLite checkpointer keyed by chat, snapshots package files, and supplies the user message and mode.
2. `PinnedContextMiddleware` adds brief, decisions, todo state, selected files and skill bodies. The model decides whether to inspect, ask a question, load a skill, write a plan or immediately call a tool.
3. File/execution/package tools dispatch to `agent.py:117`. A model-selected `verify_package` invokes a deterministic battery of package checks. Tool errors return observations through `ToolErrorMiddleware`; the model chooses a repair or another experiment.
4. `ask_user` uses a real `interrupt` and `Command(resume=...)`. Export always interrupts in the main graph; individual writes/deletes interrupt only if configured. The verifier/export functions also perform their own gates.
5. Model text can end the turn without verification. Todo completion and prose “done” are model assertions. The prompt says to stop when green, but no host completion policy binds that stop to mathematical obligations.

For “debug the surviving negative,” the tool loop can read code, run a command, ask a specialist, and repeat verification. The engine does not encode whether the survivor is actually correct, the oracle is wrong, the test suite is weak, or the checker is broken. The distinction must currently be invented and remembered by the model. For “resume after failure,” SQLite state and message repair exist, but the process's job/event registry and filesystem effects are separate. Restoring a conversation is not a transactionally restored authoring session.

| Decision | Actual owner | Consequence |
|---|---|---|
| Next tool, skill, reviewer, hypothesis, repair | Model | Real flexible agency, variable quality |
| Stage sequence, proof depth, no weakening, review-mode nonmutation | Mainly prompts | No enforceable domain completion invariant |
| Tool arguments | Framework typed input schemas | Useful syntax boundary, not semantic correctness |
| Paths, writes, execution requests | Application functions | Some boundaries are inconsistent across routes |
| Package verdict | Deterministic verifier | Authority over its implemented checks, not independent semantic truth |
| Clarification and configured approvals | Graph interrupts + human | Real pause/resume, effect scope needs revision binding |
| Chat state | SQLite plus JSON mirrors | Persistence exists, broader recovery incomplete |
| UI workflow labels | `web/machines.js`, `web/app.js` | Not authoritative engine state |

## 2. Strengths worth retaining

The runtime uses supported framework primitives rather than hand-parsing model prose as tool calls. Injected workspace state avoids letting ordinary tool arguments choose another workspace. SQLite checkpoints, tool-call history repair, interrupt preservation, refusal handling, stream integrity checks, restricted read-tool retries and context compaction show engineering work beyond a minimal demo. The independent reviewer has a genuinely smaller tool set, even though its conclusions are not an oracle.

The application has package-level deterministic checks, tracked text changes, a human export gate, worker adapters, UI evidence views and a broad QA inventory. Its local distribution scope is appropriate. A portfolio reviewer can inspect real behavior and ordinary Python functions instead of needing access to a public SaaS. Existing direct dependencies are pinned. Do not throw these assets away merely to claim a new architecture.

## 3. Current findings and implications

These IDs are new research findings, not replacements for historical A01–A37. Source locations refer to the inventory captured with this package.

| ID / evidence | Current reference and actual problem | Implication and proposed response | Validation |
|---|---|---|---|
| E01 O/I | `graph_agent.py:930`, `agent_state.py:23`: tool loop has prose memory, no hypothesis/obligation/experiment/finding lifecycle | Keep agent choice, add typed investigation state and host completion gate | Green package + open proof gap must remain incomplete |
| E02 O | All 13 skill bodies and 7 prompts: short checklists without worked diagnostics or executable artifact contracts | Three deep domain procedures composed with seven collaboration procedures, bounded retrieval and behavioral tests | Held-out greedy/DP failure and correct-control comparison |
| E03 O | `graph_agent.py:412–449`: same configured model, fresh review messages, three read-only tools, final `{review: text}` | Separate review context is useful but not independent ground truth; structured narrow challenges with budgets | Specific claim/revision, false positives, useful additional defects per call |
| E04 O/R P4 | `winutil.py:_require_local_or_executor` permits host execution absent explicit requirement; `agent.py:70` allows interpreters | Allowlist is not sandboxing; default fail closed, no generated code on app host | Mock all spawn points, then authorized worker boundary canaries |
| E05 R P1/O | `agent.py:124`, `workspace.py:43`, `agent_middleware.py:99`, `mcp_server.py:_safe_path`: deny checks precede canonical identity | Canonical `data/secret` blocks, `data/./secret` exposes synthetic sentinel | Shared policy across read/search/context/MCP/run, case/link tests on Windows/Linux |
| E06 O | `graph_agent.py:930` always supplies author tools; `prompts/modes/review.md` is the restraint | Review mode is not read-only authority; executable writes also evade write-only approval policy | Reject every mutation/publication path under review capability |
| E07 O/I | `executor_server.py:101`, `isolate_worker.py:157` sync directories from staging | Arbitrary worker outputs can bypass change journal or overwrite newer source | Immutable inputs, declared artifact publication, stale-result conflict test |
| E08 R P2/P3 | `workspace.py:291,378,923`: `.out` omitted from tree-derived hash; source edit leaves `limitsMeasured` true | Evidence freshness incomplete even though export has a real hash gate | Explicit dependency manifest including checker fixtures, compiler and measurements |
| E09 O | `verify.py:468,521`: interactive early return omits batch snapshot/report lifecycle; `verification_modes.py:interactive_selftest` selects one test | Interactive “verified” has narrower evidence than batch status suggests | Disable showcase claim; later common lifecycle + second-case failure canary |
| E10 O | `verify.py:40,646`, `winutil.py:_remote_run`: timeout forwarded without package memory; result collapses worker detail | Cannot infer configured resource enforcement from report wording | Versioned worker contract, reject unsupported controls, measure actual enforcement |
| E11 O/I | `verify.py:287,635`: reference-generated answers are later checked against references; `eval/run_eval.py:main` grades with same verifier | Consistency can hide common semantic defects; two visible fixtures are not independent evaluation | Independent finite oracle and hidden assessor, shared-wrong-reference canary |
| E12 O | `server.py:84`, `graph_agent.py:745,1031,1062`, `workspace.py:884`: process jobs, checkpoints, mirrors and files have separate lifecycles | Durable chat is not exactly-once work or coherent revision restore | Operation receipts, persistent events, recovery reconciliation and forked restore |
| E13 O/I | `graph_agent.py:756,833,908,982`: aggregate events/rates, main model-call limit; nested reviewer has no comparable explicit budget | Cost attribution and task-wide bounded autonomy incomplete | Reservation ledger across retries, summaries, specialists, tools and deadlines |
| E14 R P5/P7 | `agent_state.py:11`, `skill_registry.py:activate`, `prompt_loader.py:_read`: merge can yield 3 skills; partial prompt bundle silently accepted | Validate invariants after merge, reject incomplete required bundles | Concurrent loads, missing file, replayed updates |
| E15 O/R P6 | `judge0_adapter.py:quick_run` treats status 1/2 as ok; `web/app.js:1178` has useful export predicate but duplicate renderers at 982/1137 | Visible state can mislead despite syntax tests | Pending != terminal; executed renderer assertions; preserve existing shell |
| E16 O | `agent_middleware.py:57,140`: selected workspace text placed in system message; trimming can truncate that message | Untrusted content gets high-priority placement; safeguards should not depend on truncatable data | Keep immutable policy separate, retrieve revision-tagged data at lower trust, injection canaries |

E16 is a boundary concern, not a demonstrated prompt-injection exploit. E07/E10/E12 require authorized integration fault tests before runtime outcome claims. P1–P7 are reproduced observations, not proof that all aliases, races or deployment modes behave identically.

The specialist evidence surface is also narrower than its prompt language: `reviewer_read_file` rejects every `.in` and `.ans`, while the test-designer prompt asks it to assess current tests. A count/summary can support a coverage proposal but not inspection of actual test content. Give a role-specific authorized diagnostic manifest and label what the reviewer could actually inspect, while retaining protected-test restrictions.

## 4. Version and inspection coverage

Host `importlib.metadata` reports LangChain **1.4.9**, LangGraph **1.2.20**, langchain-openai **1.7.4**, SQLite checkpointer **3.1.3**, core **1.7.6**, checkpoint **4.3.1**. The four direct framework pins match `requirements.txt`. Local inspection confirms `create_agent` supports state/context schemas, response format, checkpointer and middleware, and HITL supports `interrupt_mode`. No upgrade is necessary merely to start this design. Transitive lock/image identity and container runtime were not established.

Read in full: assignment, all seven prompt files, all thirteen skill files, state/schema/loader modules and agent dispatch. Selected owning sections examined in the larger graph, middleware, workspace, server, verifier, verification modes, package model, execution workers, clients, config and MCP modules. UI integration was traced through job/cancellation, evidence/export, review and renderer code. Evaluation runner/fixtures, CI, requirements and primary compose/Dockerfiles were examined. README/architecture/status/readiness were treated as historical claims. Previous plan bodies were consulted only after the saved initial diagnosis, then compared against current source.

The inventory hashes 316 tracked files. **Inventory is not line-by-line review.** Remaining QA cases, browser assets, vendor internals, most launch-script branches and full `icpc_spec.py`/`scoring.py` behavior were not exhaustively audited. Selected QA source was reviewed before running safe checks. No private `.author-agent`, live workspace, `.env`, authentication files or generated contest submissions were read.

Fresh checks: skill registry tests, event ledger tests, JS state-machine tests and UI syntax check passed. Seven custom probes reproduced current gaps. No current provider quality, sandbox security, full package judging, browser accessibility, installation, performance or CI-green result is claimed. Historical 500k-context and sum/claim successes were not replayed.

## 5. Comparison with the earlier plans

The initial diagnosis independently identified the central agency/evidence gap and several boundary defects. The previous system-depth audit's detailed observations agree on the major owning paths. Its source references were useful for expanding coverage, but its probe outputs were not counted as new reproductions.

Retain the previous integrity priorities and correctness distinctions. Revise the delivery strategy: do not require all 13 skill rewrites, all three domain packs, a large frontend extraction and the full package-profile matrix before evaluating a useful investigation. Narrow unsupported modes, implement one complete slice, establish an independent baseline immediately, then earn extensions. The explicit [roadmap mapping](07-ROADMAP-AND-PORTFOLIO.md) accounts for all T01–T56.


## 6. C1 collaboration assessment (new source inspection, not retrospective evidence)

Current `graph_agent.py:330` exposes `ask_user` and resumes an untyped answer payload, while `resume_turn` at line 1125 passes clarification into `Command`. `agent_state.py` retains decisions, clarifications and questions but lacks typed contribution provenance, goal generations and delegation contracts. `server.py:463–525` rejects chat/resume while a workspace is in `ACTIVE_CHATS`. `web/app.js:2999,3551,3559,4282` disables or buffers messages and renders clarification. These are useful existing interaction seams, not a concurrent steering inbox or a joint reasoning protocol. This conclusion is source inspection; no running application was exercised.

**E17 — collaborative ownership is underspecified.** The author can answer a question, but source does not establish an atomic contract between an arriving semantic correction and an in-flight publication. An untyped answer also cannot reliably distinguish a chosen definition, a claim about mathematics and authorization for an effect. Preserve the current clarification affordance while introducing typed inputs, provenance and the generation barrier described in [03](03-ENGINE-DESIGN.md). Do not solve this by asking for approval on every step: bounded grants and explicit stage returns are central to usefulness.

The revised recommendation remains LangGraph, now with explicit parent nodes and scoped subgraphs rather than treating four logical responsibilities as a node limit. Human understanding and useful joint decisions are separate outcomes from package validity. The original source-first diagnosis, seven original probes and earlier-plan comparison remain unchanged; this is a subsequent product requirement and additional inspection.
