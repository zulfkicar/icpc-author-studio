# Implementation roadmap and portfolio evidence

Date: 2026-11-13. **Planning only.** No task below is implemented by writing this document. File names under `engine/`, `domain/`, `providers/` and proposed QA paths are target modules, not existing capabilities.


## 1. Smallest coherent flagship

Build a local collaborative batch-problem correctness investigator, with weighted interval scheduling as the public vertical slice and distinct held-out variants for evidence. The first slice is complete only when an author can shape the specification, contribute a lemma/test, challenge an approach, steer a running stage, see a failed hypothesis, replay a valid counterexample, inspect the argument/code relationship, interrupt/resume without duplicate effects, and receive the agreed diagnostic/proof/patch stage with remaining obligations visible. Full package export is V5, not a V3 completion requirement. A new schema or tool registry alone is not a release.

Retain `graph_agent.py` as a compatibility facade during extraction. Keep ordinary Python domain services independent of the graph. Do not rewrite the UI or import another full agent harness to make the architecture look sophisticated.

| Slice | Concrete source work | Dependencies | Required acceptance evidence |
|---|---|---|---|
| V0 — contracts, baseline and independent grader | Freeze baseline; `qa/engine_contracts/`, fake model/worker/input scheduler, stage-scoped C01–C12 fixtures and CR01–CR10 schedules, oracle/rubric; prototype decision/evidence/handoff wireframes | None | Preserved baseline, qualified tiny oracle, scripted author policies and event-order/failpoint matrix; graph signatures qualified before use |
| V1 — safe effects and collaboration ingress | `engine/policy.py`, `execution.py`, `state.py`, `interactions.py`; server input API; minimum active-job composer, typed decision/contribution/delegation cards in existing UI | V0 | Fail-closed worker boundary, canonical paths, runtime schema/actor validation; distinct received/applied UI; no redundant approval for explicit scoped instruction |
| V2 — durable joint session and experiment | `engine/revisions.py`, `store.py`, `operations.py`, `interactions.py`; SQLite inbox/publication barrier; adapt workers/verify; single-owner wake outbox and current-session recovery (restore mutations deferred) | V1 | C04/C06–C10 first-slice integrity schedules; touching witness receipt, duplicate response/unknown outcome, crash/restart preserves human originals and decisions; stale generation cannot publish |
| V3 — collaborative model-directed vertical slice | `engine/controller.py`, `budget.py`, minimal `providers/base.py` fake/single-request seam; parent+four scoped subgraphs; seven COL procedures plus scheduling/finite-oracle resources; minimum `domain/differential.py`, typed StageReturn gate and immutable patch review; focused explanation/diff/resume renderer; no delivery/export | V2 | Same-goal conditional routes, human false-claim challenge, reasonable rejected recommendation, code/lemma/test provenance, bounded delegated return and recovery; fake-model script then later authorized model qualification |
| V4 — broader domain depth | Expand `domain/differential.py`; add `reduce.py`, `mutation.py`; extend serial first-slice tools to reduction/mutation campaigns; registry/resource enforcement | V3 | Original/reduced witness, complete survivor classifications, shard/cache contracts if adopted, broader controls; no replacement of collaboration with tools |
| V5 — richer presentation and delivery | Delivery readiness/export service, explicit restore mutations, rich evidence/branch browsing, accessibility, legacy import; focused renderer extraction only where useful | V3/V4 | Clear restore modes, evidence lineage navigation, current/stale/unknown facets, immutable ZIP/exact approval; essential cards already available in V1–V3 |
| V6 — qualify and distribute | Provider conformance, install/migration/backup, independent held-out and author studies, documented licensing | V1–V5 | Original 432-attempt protocol plus separately budgeted collaboration ablation, independent pilot, supported OS recovery, truthful claims |
| V7 — earned extensions | Additional domain/checker/interactive support, optional AgentDriver/formal pilot, shared-author research | V6 evidence | Separate contracts, benefit measurement and requalification; no implicit entitlement/support claim |

V1 is essential, but avoid implementing every worker feature before any domain feedback. Scope the supported profile to batch/exact integer and **reject** unsupported controls/modes. If an existing interactive route remains available for legacy use, clearly label its unqualified status and do not let it satisfy flagship readiness. Repair common lifecycle defects before subsequently claiming that mode.

### First vertical slice acceptance script

1. Open a synthetic booking idea and an imported author solution with strict-endpoint bug. Author chooses half-open semantics and asks for brief explanations. Record the decision and original source contribution.
2. Author proposes earliest finish. Agent fairly derives a weighted discriminator, obtains a qualified receipt and explains why count and reward differ. Author reasonably declines a redundant third reference; continue with the independent subset oracle and explicit scope.
3. Author supplies a valid exclude-case lemma and a touching-jobs test. Agent preserves attribution, challenges a false compatible-prefix claim and jointly derives the DP obligation/code map.
4. Author delegates a bounded diagnostic stage with no file edits. While a worker runs, submit an endpoint correction. Verify durable received/applied status and that the old generation cannot publish applicable results. Restore intended half-open semantics explicitly as a new decision and rerun affected work.
5. Interrupt after receipt commit before graph consumption. Restart, show the same receipt, original contributions, open complexity question and current decision without asking it again. Stage returns at its agreed boundary.
6. Author authorizes a concrete repair scope, edits the proposed diff and sees hash revalidation. Apply under current generation, replay witness and finite-domain evidence. A package pass is separate from argument review.
7. Change the statement after patch review: the prior review and dependent evidence become stale. Return a stage handoff listing decisions, original contributions, current results and remaining work. Exercise stale approval rejection with a synthetic effect manifest, and assert that the V3 UI/API cannot export. V4 adds broad campaigns; V5 implements the full delivery predicate and approved export, followed by V6 qualification.

Run first with a scripted fake model and worker simulator to qualify state/effects, then qualify the isolated worker. Before any later authorized real-model V3 trial, pass the minimal single-endpoint malformed-call/disconnect/cancellation/usage/shared-budget contracts. Full provider breadth/install qualification stays in V6. The fake trace cannot be presented as an autonomous successful investigation.

## 2. Reconcile all 56 previous tasks

Previous [system-depth backlog](../../plans/system-depth/04-BACKLOG.md) remains valuable source history. The following is a recommendation, not an edit to that plan or a declaration of implementation completion.

| Prior IDs | Disposition and new location | Reason |
|---|---|---|
| T01–T03 | Retain in V0, add independent grader and scripted authors immediately | Baseline must precede both tuning and claims |
| T04–T08 | Retain, prioritize V1/V2 within batch profile | Unsafe execution or arbitrary publication undermines every later experiment |
| T09 | Retain common lifecycle in V2/V5 | Uniform receipts/freshness needed even when unsupported modes are gated |
| T10 | Defer full interactive matrix to V7 | Not necessary for first exact-output showcase; do not claim support meanwhile |
| T11 | Retain result semantics now; defer general checker fixture breadth to V7 | Judge errors must never be mutant kills, even in narrow profile |
| T12–T14 | Retain V1/V2/V5 | Immutable export, worker boundary and cancellation are core evidence engineering |
| T15–T16 | Retain V2, merge around operation journal plus typed input/response ledger | One coherent revision/publication contract instead of disconnected metadata tasks |
| T17 | Narrow V1 to strict policy/consent and disable unqualified external MCP use | Full external interoperability can follow a working local engine |
| T18 | Current-session/contribution continuity V2; branch restore mutations V5, platform qualification V6 | Conversation-only replay is insufficient for demo recovery |
| T19 | Narrow V6 to supported adapter/worker settings, defer unused provider knobs | Reduce configuration drift while preserving future extension seams |
| T20–T21 | Retain V1/V3/V4 | Role capabilities, exact approvals, skill merge and prompt validation are real control |
| T22–T24 | Retain V2/V3, implement minimum local durable jobs/events/budgets | No distributed queue or generic observability platform needed |
| T25–T27 | Retain V1–V3 state/interactions/subgraphs and bounded retrieval | Central agency improvement |
| T28 | Revise: seven COL procedures plus domain method in V3, then remaining skills | Rewriting all 13 before behavioral feedback delays learning |
| T29 | Retain needed joint spec/proof/complexity/oracle/code-map content in V3 | Can initially be one coherent pack, not five artificial agents |
| T30 | Revise: scheduling bridges greedy rejection + DP, graph pack after evaluation | Three domain labels are not evidence of depth |
| T31–T32 | Retain V3–V5, one optional challenge reviewer | Structured contract first, measured extra roles later |
| T33 | Narrow to provenance and uncertainty in V5/V6; broader calibration later | No fake originality/difficulty claim, no need for large calibration corpus to ship preview |
| T34–T37 | Minimum finite discriminator in V2/V3; full reduction/mutation depth V4 | These make the investigation visibly substantive |
| T38–T39 | Defer general custom/interactive and broad metamorphic registry to V7 | Add only the few applicable relations needed by the first pack |
| T40 | Defer broad frontend extraction; focused collaboration seams V1–V3 | UI cleanup should not dominate engine showcase |
| T41–T42 | Move minimum decision/contribution/progress/evidence/handoff UI to V1–V3; rich browsing V5 | Users must inspect actual evidence and staleness |
| T43 | Narrow V5 to supported exact-output server judging; richer modes later | Browser comparator cannot become authority |
| T44 | Retain pending/terminal correction if Judge0 exposed; otherwise disable optional route | Small correctness repair, not flagship dependency |
| T45 | Delivery/export begins V5/V6 with one explicit batch profile; V3 export disabled | Full format matrix is a separate interoperability program |
| T46–T47 | Retain V0/V6, tier and date all evidence | Avoid historical passes and skips masquerading as qualification |
| T48 | Move design/grader/scripted-author/ablation protocol to V0, compare in V6 | Evaluate architecture rather than merely documenting it |
| T49 | Retain focused current latency/cost measurements V6; broad perf program later | Trace bottlenecks from actual campaigns |
| T50 | Revise: independent local author pilot during V6 qualification, broader contest pilot later | First portfolio evidence need not imply contest-readiness |
| T51–T54 | Retain distribution-critical lock/license/install/migration work in V6 | Reproducibility and preservation are part of the engineering claim |
| T55 | Defer to V7 selective proof pilot | Valuable only with clear theorem/spec/code boundary |
| T56 | Defer until each pack earns behavioral evidence | Avoid generic framework/content expansion |

New first-class work mapped alongside T15–T16/T25–T28/T41–T42/T48: typed author interaction and contribution records, concurrent inbox/publication barrier, scope/return contracts, seven joint procedures, scripted and independent-author evaluation. Additional work missing or insufficiently explicit in old task sequencing: equal-tools simple-loop baseline; dual ModelAdapter/AgentDriver interface; per-version official subscription integration constraints; finite-domain proof-gap benchmark; short portfolio trace with failure and recovery; hard stop on same-action nonprogress. These are integrated above rather than added as another long backlog.

## 3. Install and release contract

Target Linux plus Windows/WSL2 local loopback use. User brings model access and chooses the supported profile. Fresh install must verify prompt bundle, schema compatibility, writable local storage, worker protocol/toolchain and generated-code isolation before enabling execution. Missing worker must leave inspection usable and execution visibly disabled.

Pin transitive dependencies and image/toolchain identities, review third-party notices and select a project license before distribution. These are release tasks, not accomplished by the current direct pins. Include an opt-in diagnostic command that reports capabilities and versions without reading or printing credentials. Do not package `.author-agent`, live workspaces, private contest data or authentication caches.

Migration: copy-on-upgrade backup, schema dry run, idempotent migration, validation and rollback rehearsal. Old verified reports keep their original scope; they never become correctness-reviewed. Approvals become historical when their revision/effect binding cannot be established. Keep imported workspaces readable and export an evidence bundle separate from private configuration.

## 4. Short truthful demo: approximately five minutes

| Time | What viewer sees | Claim substantiated |
|---|---|---|
| 0:00–0:40 | Incomplete idea becomes author-chosen half-open specification; brief mode | Bounded task ownership |
| 0:40–1:30 | Author's greedy claim tested fairly; declines extra reference with scope retained | Model-directed hypothesis testing |
| 1:30–2:30 | Human lemma/test, corrected false claim, DP/code map and endpoint explanation | Domain method, independent evidence, diagnosis |
| 2:30–3:20 | Mid-run steering blocks stale effect; restart retains decisions/contributions/receipt | Durable effects, no duplicate publication |
| 3:20–4:20 | Scoped stage return, edited patch, witness replay and open findings | Evidence-driven adaptation |
| 4:20–5:00 | Edit invalidates evidence; attributed handoff, explicit export-unavailable state | Honest completion and human authority |

This table is the V3 demonstration. After V5/V6 qualification a separate extended recording can add mutation evidence and exact-revision export; do not splice those into a purported V3 capability claim. If a recording is accelerated, disclose elapsed time and show full raw trace links. Keep a prerecorded successful demonstration for reliability, labelled with source/model/date and actual usage; provide a separate rerun path. Do not conceal retries or human corrections. A live failure with a truthful incomplete result may demonstrate the control boundary better than an edited success montage.

## 5. Deeper technical walkthrough: 15–20 minutes

Explain the problem and why self-generated answers are not an independent oracle. Walk through the current source-first diagnosis, the chosen graph boundaries and a rejected architecture alternative. Inspect one action envelope, capability check, immutable manifest, operation receipt, dependency invalidation and structured finding. Show a crash failpoint and the reconciliation code. Then compare B0/B1/B2 results, cost/latency and false positives, including a case where the simple loop is as good or better. Finish with what the system does not prove.

Be able to defend: why LangGraph remains; why the evidence DB is separate; why a receipt is not exactly-once execution; why model review is correlated; why finite agreement is not proof; why formalizing pseudocode does not verify C++; why subscription access is a distinct adapter; why a narrow local release is a deliberate scope choice.

## 6. Public repository evidence package

Release artifacts to create after qualification:

- `docs/engine/architecture.md` with actual graph and authority boundaries, linked to implemented source.
- `examples/scheduling-investigation/` with public starting/final packages, spec, editorial, oracle provenance, witnesses and replay instructions.
- `evidence/releases/<tag>/manifest.json` with source/prompt/skill/toolchain/image identities and capability matrix.
- `evidence/releases/<tag>/runs/` with redacted decisions, events, receipts, actual usage and human intervention logs. No hidden private reasoning or credentials needed.
- `eval/protocol.md`, frozen baseline definitions, grader controls, failure taxonomy, raw per-attempt scores, paired uncertainty and ablation reports.
- `docs/demo.md` for short and deep demonstrations; links to full unedited run records and known failures.
- `docs/install.md`, `docs/recovery.md` and clean-machine results for supported OS profiles, migration and rollback.
- `SECURITY.md` describing actual local trust boundary, residual worker privileges and disclosure route; license/notices and exact supported provider integrations.

Artifacts must exist and replay before advertising them. Keep a compact claims table with `implemented`, `offline-tested`, `worker-qualified`, `provider-qualified`, `human-reviewed`, `not-supported`. Do not use a single green badge for all dimensions.

## 7. Final recommendation

Build V0–V5 as one bounded vertical program, then qualify through V6 before expanding. The technically distinctive result is a partner that helps an author reason and selects and revises investigations while the host preserves the integrity of its evidence and effects. Its usefulness is concrete: catching plausible wrong solutions, explaining why tests missed them, and handing the author a reviewable package with reproducible supporting work.

We will know it works when independent graders confirm valid diagnoses/repairs, correct controls are not needlessly blocked, recovery canaries preserve committed effects, and matched baselines show which additions help. Until that evidence exists, the honest claim is a source-grounded design and a functioning but incompletely qualified current workbench, not a proven autonomous problem setter.


## 8. Showcase variants, tradeoffs and remaining decisions

The five-minute recording is an edited overview of actual qualified runs, not a claim that all investigations take five minutes. Label pauses, author contributions, interventions and recording cuts; link the full trace. The public scheduling case is a teaching example, excluded from evaluation. An independent curator supplies held-out variants changing objective/compatibility, tie structure, numeric risk and contribution type. At least one valid unconventional implementation must survive review; an out-of-profile setup-time variant must trigger honest scope discussion. Demonstrate a variant selected before seeing outcomes, including failures, rather than replaying the exact 12-vs-13 witness. Do not publish hidden grader answers as demo artifacts.

The first executable slice is V0–V3, with minimum oracle/diagnostic and UI work pulled forward from former V4/V5. Full reduction/mutation breadth, delivery/export, restore mutations, rich branch browsing and distribution qualification still follow. This preserves integrity prerequisites while ensuring the first working engine is a useful partner. Small shared schemas/services should precede extraction of the large facade; no speculative UI rewrite or multi-agent platform is required.

Tradeoffs: a durable inbox and generation checks cost more implementation effort than rejecting chat during jobs, but enable safe steering. Serial model control simplifies authority and recovery; it temporarily pauses autonomous work on blocking questions. Same-model collaboration/review reduces integration complexity but does not provide independent proof. Local SQLite and basic UI keep the product approachable; multi-author conflict resolution and persistent preference Store wait for evidence of need.

Settle SQLite platform durability, input actor identity, migration compatibility and cancellation/usage semantics during V0–V2. Calibrate default question/retrieval/call/time budgets with public pilots. Provider choices and paid evaluation require later explicit scope/budget; none is requested or exercised by this research. The acceptance gates and design are concrete enough to start implementation later without pretending these qualification questions are already resolved.


## 9. C2 scope discipline and exit gates

Do not split every proposed filename into a new package or create a service per node. The minimum implementation can be five cohesive seams inside the existing application: (1) validated policy/input service, (2) application ledger/revision/receipt storage, (3) owner/controller with fake or single-request model adapter, (4) one isolated diagnostic operation, (5) existing UI cards. Extract modules when ownership is clear; the roadmap names responsibilities, not a prescribed file count. Use one record store for interaction/goal/contribution truth, with graph projections, not competing event-sourced aggregates. The wake outbox is a table scanned on startup/boundaries, not a message broker.

| Exit gate | Required before next slice | Explicitly unnecessary here |
|---|---|---|
| V0 -> V1 | Frozen baseline, stage vs delivery schema, independent hand-checkable oracle fixtures, finite CR schedules, rough interaction views | Provider calls, full 48-task grading corpus implementation, dependency upgrade |
| V1 -> V2 | Canonical permission validation, bounded contribution/actor validation, one inbox/idempotency path and simulated received/applied UI; generated execution stays disabled | Distributed identity, worker pool, arbitrary author-file ingestion |
| V2 -> V3 | Single owner and restart reconciliation, wake race/duplicate controls, receipt vs current-publication distinction, steering/cancel fences and one shared reservation, managed/externally edited checkout scope | Three restore mutation modes, generic event replay platform, parallel campaigns |
| V3 stage preview | C01–C12 first-slice behaviors plus CR01–CR10 critical schedules, independent oracle/worker boundary, two meaningful routes, valid false-claim response and reasonable rejected suggestion; qualification status shown | Mutation/reduction breadth, full delivery/export, external AgentDriver, live provider evidence when using fake model |

No graph-size success criterion. If the same typed operation/result/authority contract can be implemented as a small function within a subgraph, do that. Keep explicit durable boundaries only where a call, worker, human wait or publication can be interrupted. Optional specialist review is not a prerequisite for answering a simple question. A scoped stage handoff is a useful first result, not a reduced claim of full correctness.
