# Research synthesis and architectural decision

Research date: 2026-11-13. Official pages are rolling documentation, not promises about the installed environment. Primary sources below were opened during this assignment. Mechanisms are borrowed as design ideas; none establishes improvement in this application without the evaluation in [06](06-EVALUATION.md).

## 1. Primary-source register

| ID | Source inspected | Mechanism and transfer limit |
|---|---|---|
| S1 | [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence), [checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers) | Distinguishes thread checkpoints from cross-thread data. Use SQLite for graph state, a separate application evidence store for durable facts. Neither makes external file/process effects atomic automatically. |
| S2 | [Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api), [interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) | Typed channels/reducers and explicit routing; interrupt resumes can rerun node code. Put effects behind stable operation receipts, bind human decisions to a revision. More nodes alone add no domain intelligence. |
| S3 | [LangChain structured output](https://docs.langchain.com/oss/python/langchain/structured-output) | ProviderStrategy/ToolStrategy can validate shape. Use explicit strategy after capability qualification. A valid JSON finding can still be false or cite nonexistent evidence. |
| S4 | [LangGraph streaming](https://docs.langchain.com/oss/python/langgraph/streaming) | Events/state/message streams can expose execution progress. Persist domain events separately and attribute nested calls. A token delta is not a committed artifact. |
| S5 | [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling) | Application executes structured tool requests and returns results. Validate complete arguments, correlate call IDs, enforce policy server-side. Strict schema adherence is not permission or semantic validation. |
| S6 | [Codex authentication](https://learn.chatgpt.com/docs/auth), [app-server](https://learn.chatgpt.com/docs/app-server), [SDK](https://learn.chatgpt.com/docs/codex-sdk) | Subscription sign-in and API key access are distinct. App-server provides an embedded agent protocol. Its local/open-source authentication guidance does not authorize commercial or hosted reuse. Dynamic tools remain experimental. |
| S7 | [Claude Agent SDK quickstart](https://code.claude.com/docs/en/agent-sdk/quickstart), [Python reference](https://code.claude.com/docs/en/agent-sdk/python), [headless CLI](https://code.claude.com/docs/en/headless) | API-authenticated programmable agent, tools, streamed messages, interrupt and usage surfaces. Third-party claude.ai login/rate-limit use requires prior approval. Personal CLI automation is not blanket distribution permission. |
| S8 | [mini-swe-agent DefaultAgent source](https://raw.githubusercontent.com/SWE-agent/mini-swe-agent/main/src/minisweagent/agents/default.py) | Minimal query/execute loop, explicit termination and trajectory persistence. A useful complexity baseline, not a ready-made ICPC authority model. |
| S9 | [Deep Agents graph implementation](https://raw.githubusercontent.com/langchain-ai/deepagents/master/libs/deepagents/deepagents/graph.py) | Explicit middleware assembly, backend injection and specialist configuration. Borrow coherent capability/context composition, not all its filesystem/subagent defaults. |
| S10 | [ReAct original paper](https://arxiv.org/abs/2210.03629) | Motivates alternating reasoning/action/observation. Does not prove a specific framework, number of agents, or hidden reasoning display is best here. Evaluate observable decisions and results. |
| S11 | [Zeller and Hildebrandt, Simplifying and Isolating Failure-Inducing Input](https://www.st.cs.uni-saarland.de/papers/tse2002/tse2002.pdf) | Failure-preserving reduction. Transfer requires domain validity, tri-state outcomes and a stable failure predicate. A locally irreducible witness need not be globally smallest. |
| S12 | [Lean axioms and computation](https://lean-lang.org/theorem_proving_in_lean4/Axioms-and-Computation/) | Formal claims have assumptions and a trusted boundary. Record theorem/axioms/checker identity. A checked abstract algorithm does not automatically verify C++ or the natural-language problem. |
| S13 | [Legacy ICPC package specification](httpC://Projects.io/problem-package-format/spec/legacy-icpc.html) | A concrete compatibility target. Package format compliance is separate from reference correctness and test quality. Pin the supported profile rather than mixing dialects. |

Primary URLs and research date identify the inspected rolling sources. Exemplar files were inspected through the web tool at `main`/`master`, not cloned or run. Their commits were not resolved in this assignment, so line observations below are dated snapshots, not reproducible upstream pins. Pin exact commits before adapting code or running an exemplar benchmark. No code was copied into production.

## 2. Exemplar implementation details

**mini-swe-agent:** `DefaultAgent.run` repeatedly calls `step`, handles format/control-flow errors and saves in a `finally` block. `step` composes `query` with `execute_actions`. `query` checks call/cost/time limits before issuing the next query; reported cost is accumulated afterward. The transferable ideas are a legible loop, explicit exit taxonomy and persistent trajectories. Its own cost configuration notes possible overshoot. Our budget reservation must therefore precede expensive calls. Use a comparably simple loop with the same safe ICPC tools as the baseline, not a bash-only environment. [S8](https://raw.githubusercontent.com/SWE-agent/mini-swe-agent/main/src/minisweagent/agents/default.py)

**Deep Agents:** `create_deep_agent` assembles filesystem, subagent, summarization and patching middleware, then optional skills/memory/approval controls. Specialist construction applies backend, model and permission configuration to its own middleware. Ordering affects what model and compacted context skills see. This supports central composition and explicit role boundaries, but importing the whole harness would duplicate much of this repository and still leave correctness evidence undefined. Inspecting this file did not establish security of every backend. [S9](https://raw.githubusercontent.com/langchain-ai/deepagents/master/libs/deepagents/deepagents/graph.py)

**Codex as integration exemplar:** the app-server source README and official protocol docs distinguish threads, turns, events and approvals. This informs an external-agent adapter with opaque session IDs and explicit completion, rather than parsing CLI prose. It is a whole agent runtime, not an interchangeable `ChatOpenAI` completion function. [Source README](https://raw.githubusercontent.com/openai/codex/main/codex-rs/app-server/README.md)

## 3. Three credible directions

Relative judgments below are engineering estimates, not benchmark results.

| Criterion | A: strengthen current LangGraph engine | B: small custom event-driven tool loop | C: embed Codex/Claude agent runtime |
|---|---|---|---|
| Task fit | Strong: retain CP tools, add evidence policy | Strong: all behavior explicit | Strong code work, CP evidence still custom |
| Control | Host graph + policy service, careful reducer semantics | Direct control with less framework indirection | Must constrain built-ins and translate permissions |
| Evaluation | Existing harness adaptable; fake model/replay | Excellent transparent baseline | Provider runtime changes confound comparisons |
| Recovery | Existing checkpoints useful; receipts still needed | Must build message/session/interrupt persistence | Runtime session recovery plus separate evidence recovery |
| Maintainability | Moderate framework/version burden | Small initially, grows with retries/interrupts/streaming | Less agent-loop code, more protocol/version coupling |
| Integration effort | Lowest migration risk | Medium/high: replace runtime and history semantics | Medium/high: approval/UI/tool bridging and auth qualification |
| Local distribution | Python + existing workers | Same workers, fewer agent dependencies | Native binary/SDK and user login/platform support |
| Main risk | Overengineering graph, mistaken checkpoint guarantees | Reimplementing a framework badly | Nested autonomous runtimes and unsupported auth promises |

**Choose A.** Retain reconciliation, choice, execution and assessment as responsibilities, not a four-node limit. The explicit parent and collaboration/investigation/editing/review subgraphs in [03](03-ENGINE-DESIGN.md) own typed author input, conditional investigation and recoverable effects. Domain tools remain framework-independent. The proposed decision and edit-drafting nodes use bounded model calls returning validated structured proposals. The existing `create_agent` remains a migration seam, not an additional unrestricted nested loop. Long experiments return control through durable jobs, and no child grants itself completion. Keep B as an equal-tools baseline and fallback implementation option if framework overhead demonstrably harms recovery/clarity. Offer C later as an alternative agent driver, not as a hidden model provider inside the main loop.

Reject a mandatory multi-agent committee, vector memory service, distributed scheduler and generic plugin framework in the first release. There is no measured need for them. Domain artifacts and operation contracts offer sufficient reuse for new CP families without generalizing away the application.

## 4. Consequential recommendation ledger

Each recommendation connects current code, mechanism, source, tradeoff and evidence requirement. Detailed contracts are in [03](03-ENGINE-DESIGN.md) and [04](04-SKILLS-AND-CORRECTNESS.md).

| Recommendation | Owning problem/reference | Support and mechanism | Tradeoff | Validation |
|---|---|---|---|---|
| R1 Keep framework, add investigation controller | E01, `graph_agent._graph` | S2/S10: structured choose/act/observe with explicit host routing | More state than current loop | Ablate controller against equal-tools loop |
| R2 Evidence store + operation receipts | E08/E12, workspace hash, jobs, checkpoint restore | S1/S2: separate application durability from graph cursor, idempotent operations | Migration/storage complexity | Crash before/after receipt, changed-file restart, duplicate submission |
| R3 Capability-enforced tools | E04–E07/E16, dispatch/mode/workers | S5/S9 plus local reproduced gaps: one canonical policy, immutable staging, declared effects | Less convenient arbitrary shell work | Denied mutations, alias/link canaries, no late publication |
| R4 Deep skill resources, no full harness switch | E02/E14, loaders | S9: coherent disclosure/config; methods and examples designed for CP | Content maintenance | Equal-token checklist vs procedure behavioral ablation |
| R5 Independent refutation before answer trust | E11, build_answers/eval | S11/S13: finite oracle domain, replay, reducer, test/judge qualification | Extra authoring and compute | Shared-wrong-reference fixture fails external grader |
| R6 One optional narrow reviewer | E03, review subgraph | S3: structured output plus host evidence validation | Correlated errors/cost remain | Net additional confirmed defects and false positives |
| R7 Separate API and external-agent adapters | E13, `_chat_model`, usage | S5–S7: capability-qualified model API vs whole-agent driver | Two integration shapes | Auth/tool/stream/cancel/usage conformance per version |
| R8 Honest evidence UI and independent eval | E11/E15, eval and renderer | S4 and source defects: domain event ledger, held-out assessor | More grading effort | All result claims resolve to current artifacts; full failures published |
| R9 Selective formal pilot later | E01, absent proof contracts | S12: checked proposition and assumptions, explicit code relation | High specialist/toolchain cost | Good/broken/wrong-spec proof controls, no C++ guarantee by implication |

## 5. Version compatibility and research limits

Local framework signatures and versions were inspected without making a model request. These support the proposed basic state, middleware, interrupt and structured-output seams. Live docs now show additional streaming forms and capabilities. Keep the current v2 event bridge until a pinned upgrade passes contract tests. Do not copy v3 stream examples, Deep Agents DeltaChannel state, or experimental Codex dynamic-tool fields into production solely because they appear in rolling docs.

Some documentation now advertises new sign-in/API-credit programs. This design does not assume eligibility, plan coverage or billing equivalence. Recheck the exact supported program before shipping it. No provider billing, cancellation refund, maximum model context, model quality or third-party endpoint compatibility was established by this research.


## 6. C1 framework investigation and revised tradeoff

The architecture now makes author contributions and steering first-class. A larger graph is justified only where it supplies a distinct checkpoint, authority boundary, scoped context or test seam. Collaboration uses the same model adapter by default, not an additional autonomous agent. The previous four-responsibility description was insufficient as an executable design.

Official sources consulted for this revision: [Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api), [subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs), [interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts), [persistence](https://docs.langchain.com/oss/python/langgraph/persistence), [Store](https://docs.langchain.com/oss/python/langgraph/stores), [fault tolerance](https://docs.langchain.com/oss/python/langgraph/fault-tolerance), and [streaming](https://docs.langchain.com/oss/python/langgraph/streaming), accessed 2026-11-13. These support routing, pause/resume, durable state and service boundaries; they do not guarantee application authorization, file rollback, exactly-once worker effects or useful explanations. The direct `/time-travel` and `/thinking-in-graph-api` retrievals did not yield usable pages in this session; history behavior was instead checked locally and against persistence documentation.

Seven isolated experiments passed against installed LangGraph 1.2.20, LangChain 1.4.9 and SQLite saver 3.1.3: scoped conditional route, durable interrupt/resume, historical checkpoint successor, bounded pure retry, Send fan-out/reducer, cache and stream/Store. [08](08-HUMAN-COLLABORATION-AND-GRAPH.md) maps those narrow observations to adoption decisions and future product tests. Signatures also expose timeout/error-handler/trace-policy hooks, but their integration is unvalidated. Do not copy a newer documentation streaming example without a pinned contract test. No upgrade, provider call or application execution was needed.

Adopt the framework for explicit state/control and recovery. Keep domain services and the durable input/effect ledger outside framework internals. Defer parallel model roles, semantic search, external tracing and replay UI breadth. These add cost/privacy/ordering complexity without establishing first-slice benefit. Rejection of generic transcript memory or cached approval is a correctness choice, not a missing framework feature.


## 7. C2 architecture review adjustment

The C1 framework capability evidence is unchanged. Reviewing the proposed contracts exposed design defects that those probes could not test: a double path in the diagram, no complete interrupt wake owner, unresolved-input head-of-line blocking, nested retry/reservation ambiguity and delivery dependencies deferred beyond V3. [03](03-ENGINE-DESIGN.md) now defines one conditional router per branch, stored child continuations, a single local owner with a durable wake outbox, one attempt ledger and explicit stage-vs-delivery gates. These are design corrections, not new observed runtime defects.

The smaller first slice returns an attributed explanation/diagnostic/patch with decisions and open work intact. Real export and restore mutations move to V5; AgentDriver, parallelism and generic caching are not dependencies. The graph remains justified by typed context/authority and durable pause boundaries, not node count. Keep one inference owner and one worker per workspace and ordinary helper functions within subgraphs. No new framework research claim, upgrade or provider experiment was made in C2. The detailed review and finite future acceptance schedules are linked from 08.
