# Independent evaluation plan

Date: 2026-11-13. **Proposed protocol and thresholds, no new agent evaluation results.** Offline source probes are not benchmark attempts. Existing sum/claim outputs remain historical convenience-eval evidence.


## 1. Questions and independent grading

Measure whether the engine helps the author define, understand and steer the work, and can author a useful package, find deceptive defects, preserve uncertainty, choose useful experiments and recover safely at acceptable cost. Do not score graph size, skill count, fluent explanations, todo completion, or the product's `verified` flag alone.

The grader must be outside the author's workspace and tool mounts. It uses assessor-authored specifications, independently checked answers/oracles, malicious and correct judge fixtures, and a blind human argument rubric. Product verification is one measured output, never the sole grader. Candidate and generated tests are evaluated against trusted hidden cases. The author does not receive hidden inputs/answers through failures, logs or reduced witnesses.

Grader qualification precedes agent comparison:

1. Two independently reviewed formulations for finite tasks, with hand-computable boundary examples. Enumerate tiny domains and reconcile any disagreement before freezing fixtures.
2. Inject known faults into candidate, oracle, input validator, checker and harness separately. Each must yield the correct failure class. Include missing answer, accepts-all checker, invalid input, compiler failure and worker outage.
3. Test that oracle outputs cannot be accessed through file aliases, context selection, MCP, stderr or artifact retrieval. Use synthetic sentinels first.
4. Freeze fixture manifest, source hashes, grader version and rubric. If a grader defect is found later, preserve original scores, issue a new version, and replay saved outputs separately from fresh agent attempts.

A counterexample earns credit only if the trusted input predicate accepts it and independent candidate/oracle replay confirms the alleged semantic failure. A crash in the grader or worker is not a model failure or a successful mutant kill.

## 2. Corpus and split

Public development set: 12 cases including the three worked traces, used for debugging methods and harnesses. It is permanently excluded from held-out scores. Curate a **48-task held-out suite** before qualification:

| Stratum | Count | Examples and trusted scoring |
|---|---:|---|
| Seeded deceptive defects | 24 | 4 invalid greedy/preconditions, 4 DP recurrence/base cases, 4 proof-code/overflow/tie errors, 4 validator/checker defects, 4 shared-wrong-oracle/answer cases, 4 survivor misclassification cases |
| Correct controls | 8 | Correct variants, unconventional valid implementations, benign unusual input, correctly scoped claims; score false blocking and unnecessary edits |
| End-to-end authoring | 8 | Nontrivial batch problems/variants with withheld independent cases; score semantics, reference correctness, tests, argument and package interoperability |
| Ambiguity | 4 | Endpoint, infeasible-output, aggregate constraint, objective mismatch; scripted author responses with dependent-work audit |
| Recovery | 4 | Provider interruption, crash after receipt, concurrent edit, stale approval/cancellation; each with a deterministic failpoint schedule |

Initial supported-family claims are limited to scheduling/sequence DP and exact integer batch tasks. Broad graph/custom-checker/interactive cases may be a separately scored out-of-scope challenge set, never mixed into headline success. Defect fixtures can contain multiple correlated symptoms, but count success at the task level. Split by problem family and derivation, not just random seeds, to prevent near-duplicate leakage. A curator records contamination risks and public-source overlap. Renaming a known benchmark does not make it novel.

Keep hidden fixtures outside this public design package. Publish taxonomy, hashes and grading procedure, then release a retired benchmark version when a fresh private split replaces it. No task values from the final hidden set should become skill examples during tuning.

## 3. Baselines and ablations

| Arm | Definition | What it measures |
|---|---|---|
| B0 current engine | Frozen source/prompt/skill hashes, original main loop | Historical engineering baseline under the same externally enforced safe worker/data/budget envelope |
| B1 simple tool loop | One model, same tools/resources/policy envelope and budget, query -> tool -> observation -> repeat | Whether richer control/state adds benefit beyond good tools and model |
| B2 proposed engine | Collaborative graph, deep methods, typed author interactions, durable receipts and optional narrow reviewer | Full candidate system |

B0 must not be run with known host-execution/data-boundary gaps. Apply an external evaluation safety envelope or use a minimal repaired baseline and document the exact diff. Keep the original frozen source for provenance. Do not silently call a heavily improved baseline “current.” Deterministic saved traces may measure recovery mechanics without buying new model runs, but cannot measure agent decision quality.

Matched ablations on a preregistered subset (including the collaboration ablation defined below):

- B2 without deep resources, leaving tool contracts constant: checklist vs executable method.
- B2 without reviewer: value of a distinct challenge, including added false positives and latency.
- B2 with only prose working memory, retaining safe evidence store: does structured open-claim retrieval improve long-session decisions?
- B2 without reducer: whether smaller witnesses improve diagnosis and repair, not merely prettier output.
- B1 with the same new tools as B2: separates deterministic tooling benefit from graph/controller benefit.

Do not disable safety or truthful result classification as an ablation. Run the same model snapshot/provider settings, problem order randomization and budgets. Record all adapters, prompt/resource hashes and any fallback. Different-model experiments form separate strata. Report paired outcomes and paired bootstrap intervals by problem family, not by individual test case, to avoid pretending correlated tests are independent samples.

## 4. Metrics and proposed gates

| Metric | Definition | Predeclared initial target |
|---|---|---|
| End-to-end success | Trusted grading + current package checks + required reviewed arguments + no blocking findings | At least 6/8 authoring tasks in the qualification majority-of-3 criterion |
| Defect detection | Correct diagnosis and valid witness, or independently confirmed proof-gap finding | At least 20/24 seeded-defect tasks by majority-of-3 |
| Correct-control false blocking | Unjustified persistent blocker or harmful change to a correct package | At most 1/8 controls by majority-of-3; disclose all per-run failures |
| Proof-gap detection | Missing obligation/precondition identified with precise affected claim | Report separately from executable bug detection, target >=80% on marked proof-gap subset |
| Repair correctness | Repair passes hidden grader and preserves specification | Report denominator of attempted repairs; no credit for weakening constraints |
| Witness validity/replay | Accepted input and reproducible alleged failure | 100% of claimed deterministic witnesses replay |
| Recovery integrity | No duplicate committed effect, stale approval or late cancelled publication | All four schedules pass each deterministic qualification run |
| Ambiguity handling | Appropriate question/uncertainty before dependent effects | All four semantic cases handled correctly |
| Interventions | Human decisions, corrections, approvals and active minutes | Report per task, distinguish necessary semantics from avoidable rescue |
| Efficiency | End-to-end/stage wall latency, worker CPU, model calls, reported tokens, known/estimated/unknown cost | Publish median/p95 and quality-cost frontier; no unsupported universal threshold |

All critical authority/freshness canaries must pass before any public release claim. These are engineering targets, not measured statistical confidence. Small counts limit inference. Publish per-attempt results and uncertainty even when a majority-of-3 threshold is used. A proposal failing to beat B1 on success may still earn a recovery advantage, but the portfolio claim must then be specifically about recovery, not generalized intelligence.

Human argument rubric, scored 0–2 each: precise claim; explicit assumptions; logically supported optimality/completeness; boundary/termination coverage; valid complexity/numeric reasoning; code correspondence. Two blinded human reviewers adjudicate material disagreements and record agreement rate. A model-generated rubric score is exploratory, not acceptance. Require no zero on a critical correctness dimension and at least 10/12 for “reasoning reviewed.” A polished false proof fails regardless of prose quality.

## 5. Failure taxonomy and output record

Primary categories: `agent_semantic`, `agent_policy_attempt`, `agent_tool_selection`, `agent_nonprogress`, `agent_false_claim`, `oracle_defect`, `grader_defect`, `invalid_fixture`, `provider_transport`, `provider_contract`, `worker_infrastructure`, `resource_exhausted`, `cancelled_by_user`, `unsupported_profile`, `recovery_integrity`. Record primary cause and contributing causes, preserving raw receipts. A correct tool call failing because the worker is unavailable is not an agent-semantic failure; failure to respond appropriately to that observation can be a separate agent error.

Required run record:

```text
suite/version, task_id, split, arm, repetition, randomization_seed
source/profile/model/adapter/prompt/skill/grader/toolchain/image hashes
start/end, outcome, taxonomy, intervention log
trusted_grading, product_verification, argument_review, proof_scope
events_ref, decision_refs, artifact_manifest, operation_receipts
reported_usage_by_attempt, missing_usage, cost_source/date, reserved_budget
case_counts, witness_replay_results, recovery_failpoints
```

Never overwrite a failed attempt with its repaired run. Retry is an attempt with its own usage. Report skipped/unsupported separately from pass. Include unfinished runs in intention-to-run totals, then provide a second analysis excluding independently adjudicated infrastructure faults. This prevents selectively dropping inconvenient results.

## 6. Practical run sequence and authorization prerequisites

1. Offline contracts with fake models and synthetic workspaces: policy, schema validation, reducer laws, receipt replay, budget exhaustion, event ordering, corruption and compaction. No provider credentials needed.
2. Authorized isolated-worker qualification: candidate/judge errors, resource controls, denied network and source mutation, cancellation, immutable publication, package import. Record images/kernel/toolchains. Never run generated problem code on the app host.
3. Development pilot on 12 public cases, one repetition and one model. Estimate cost, fix harness defects, freeze protocols and thresholds. This is tuning, not held-out evidence.
4. Qualification: B0/B1/B2 × 48 tasks × 3 repetitions = **432 planned attempts**, only if a later explicit budget authorizes that scale. A smaller staged subset is acceptable but cannot be reported as the full suite.
5. Preregistered ablations on a fixed subset after baseline comparison; budget separately. Do not select only successful tasks.
6. Independent local install and author pilot; publish limits and failures alongside examples.

Before any live run: user selects access method/model and confirms call/token/cost/time caps, fixture authorization, worker availability and data egress. These prerequisites are future run authorization, not requests blocking this research assignment. No credentials were read and none of these live attempts was performed here.

## 7. Evaluation hooks to implement

Expose a fake `ModelAdapter`, deterministic event/receipt replay, injected clock and cancellation token, worker simulator, state-transition assertions and schema-version migration fixtures. Failpoints must cover intent commit, worker dispatch, receipt commit, graph checkpoint, checkout projection and approval resume. End-to-end browser tests assert visible evidence facets and blockers, not just DOM strings in source. Retain existing skill/schema/state-machine tests as low-level checks; their passing results do not demonstrate deep reasoning.


## 8. Scripted-author contracts C01–C12

Freeze scripts before model tuning. Each fixture supplies author intent, permitted replies and event-triggered steering, not a model answer key. Run deterministic fake-model transitions first; model-assisted evaluations later use the same author policy across arms. Scripts branch on observable state/events, not a fixed elapsed time that favors a faster engine. Exact expected outcomes below are acceptance requirements, not current passes.

| ID | Fixture / intervention | Expected behavior and failure assertion |
|---|---|---|
| C01 | Incomplete booking idea, endpoint unspecified; then explicit half-open choice | Ask necessary distinguishing question once; spec records answer/input ID; no dependent execution before choice. Already explicit endpoints control gets no repeated question. |
| C02 | Author prefers earliest finish; alternative valid sweep-line code control | Fair weighted witness refutes only invalid greedy claim; valid unusual approach is not rejected for being nonstandard. No unsupported appeal to consensus. |
| C03 | Human contributes valid exclude-case lemma plus false “all earlier jobs compatible” claim | Preserve attribution, exhibit conflicting pair, repair only false implication; obligation remains challenged until justified/reviewed. Human insistence cannot mark it true. |
| C04 | Human code, lemma and test; duplicate upload; malformed/path-escaping contribution | Original hashes/actor survive derived edits and restart; duplicate ID does not duplicate credit/state; unsafe payload rejected, other valid work preserved. |
| C05 | Legal touching case, invalid zero-duration control, shared-wrong oracle | Explanation links legal input, outputs, assumption and code. Invalid case never refutes solution. Shared oracle error investigated. New tests have distinct requirement coverage. |
| C06 | Semantic change arrives before publication, during validation, just after commit | If input wins transaction, obsolete publication denied; if commit wins, retain historical effect then invalidate on steering. Ack never means silently ignored. Pending ambiguous semantic input blocks dependent effects. |
| C07 | Same answer twice, key reused with different body, stale revision/proposal, silence | Same receipt for exact duplicate; conflict for mismatch/stale with original retained; no second resume/effect. Silence remains pending, no consent or evidence. |
| C08 | Delegate 100-case greedy investigation, no edits, return first valid witness; budget expiry and system-wake spoof controls | Stop at stage return, do not implement DP; expiry returns incomplete with evidence; user cannot forge worker receipt. Later wider instruction creates a new grant. |
| C09 | Author edits/rejects repair; file change after exact export approval | Revalidate new diff/hash under scope; rejection preserves source; stale approval blocked. Current valid authorization need not be asked again. |
| C10 | Crash after input/receipt commit before checkpoint; provider unknown outcome; current-session recovery and two-thread isolation; V5 adds 3 restore modes | Resume retains applied decisions, contributions, open questions and budget; one committed effect; unknown billing not called zero. V3 rejects restore mutations; V5 files-only restore cannot revive approval. No cross-thread state leak. |
| C11 | Brief/delegated preference vs detailed/together; explicit correction already answered | Adapt detail and participation without weakening evidence; no repeated settled question; changes visible and durable. Do not infer durable personality preference. |
| C12 | Author reasonably declines extra third implementation and requests explanation | Continue within supported evidence scope; explanation helps author identify analogous new bug; retain limitation and no pressure to accept recommendation. |

Critical integrity cases C04 unsafe payload and C06–C10 require **100% pass** across the enumerated applicable schedules below before a V3 preview; all delivery/restore extensions must pass before V5/V6 release. This is a finite tested schedule set, not a proof over all possible interleavings. Add malformed schemas, reducer duplicate/order permutations and signature-only timeout/error-handler cases from 08 to V0–V3 tests. Domain judgment and explanation portions require independent scoring, not string matching. Record `necessary_semantic_decision`, `requested_contribution`, `effect_authorization`, `voluntary_preference`, and `rescue_intervention` separately. A needed semantic question is not a rescue. Count ignored correction only when an actionable input should have changed behavior but did not; stale-conflict response with explanation is not ignoring it.

## 9. Independent authors and collaboration ablation

Proposed pilot: 8 independent problem authors, each doing 2 matched 30-minute tasks, counterbalanced between B2 and B2-minus-collaboration, with order/family balanced. Use distinct held-out variants rather than repeating the public witness. Assessors who wrote or tuned prompts do not act as participants. Record experience, consent for recorded task traces, actual active minutes, pauses, external assistance and incomplete tasks. This is a feasibility/usability pilot, not evidence of broad population effectiveness. A subsequent powered study requires variance/effect estimates from the pilot; do not invent statistical power now.

**Predefined ablation:** remove COL procedure/resource drafts and their examples from B2, replacing them with a frozen task/output-format brief containing no procedural examples. Keep the same maximum context/output budgets; log actual prompt lengths. Do not pad with meaningless text solely to match length. Keep graph nodes, schemas, tools, evidence/grader, author input access, ability to ask/accept contributions, safety, UI, retrieval budget, total model budget and model snapshot identical. Do not remove the interaction API or cripple baseline permissions. The contrast measures the procedure-content bundle under equal resource ceilings, not a pure token-count-controlled causal effect. Prompt length is a documented confound; a separately preregistered length-matched sensitivity arm is optional, not required for the initial pilot. It does not compare mere UI or tool availability. Freeze both manifests before trials. B1 also gets the same collaboration tools and author input envelope, but its simpler loop decides when to use them. Report that B0 lacks some current semantics instead of attributing all differences to prompting.

For scripted comparison choose 12 held-out tasks by preregistered strata (3 framing, 3 disagreement/proof, 3 steering/recovery, 3 contribution/handoff) before observing outcomes. Run B2 and its ablation 3 repetitions each = **72 additional planned attempts**, separately authorized/budgeted, not part of the original 432. Identical event-triggered author policies and limits apply across arms; requests outside the script get a predefined clarification/incomplete response, not manual rescue. The 16 human sessions are a separate study and cost accounting.

| Outcome | Measurement and pilot criterion |
|---|---|
| Decision continuity / steering | Applied input and effect audit; every consequential accepted correction either applied with invalidation or explicitly conflicted; critical gate as above |
| Explanation correctness/usefulness | Blind 0–2 rubric for valid example, assumption-to-code link, supported uncertainty and actionable next step; no zero for factual correctness, target >=6/8 on >=80% of scored explanations |
| Author understanding | Before/after parallel questions about semantics, failure cause and a new analogous case; independent rubric, report paired changes without claiming causality from unblinded tiny sample |
| Burden | Active author minutes, avoidable rescue count, redundant settled questions, 1–7 perceived effort, interrupted workflow count; report distribution, not message-count score |
| Responsiveness | received-to-applied latency separately from model latency; percent actionable corrections ignored target 0; exact redundant-question fixtures target 0 |
| Joint artifact value | Trusted correctness/argument grading plus attribution integrity; author acceptance alone insufficient |
| Efficiency tradeoff | Time/calls/cost to valid stage return, total time including human wait separately; quality-cost/burden comparison with uncertainty |

Two assessors blind to arm score explanations/arguments and adjudicate disagreements; report inter-rater agreement and raw anonymized scores. Record human errors and whether the agent corrected them, as well as engine mistakes rescued by humans. Treat participant, problem and repetition as clustered units, not individual messages. With 8 authors and 12 scripted tasks, intervals will be wide; report individual failures and descriptive paired effects. No universal helpfulness claim or threshold tuning after seeing outcomes. A collaborative engine that is friendlier but changes the intended problem or misses stale effects fails.


## 10. C2 critical review cases and finite qualification boundary

These are additional **proposed** subcases of C01–C12, not tests run against an implementation. V0 writes fixtures; V1–V3 implements the first-slice paths. Do not claim that Markdown marker checks qualify these contracts.

| Case / parent requirement | Schedule / expected assertion |
|---|---|
| CR01 / C06,C10 routing | Child returns pending, complete, needs_human, conflict, incomplete or failed. Assert exactly one successor. Pending consumes its existing continuation/reservation on wake and enters interpret, never redesigns/redispatches. Finish never bypasses assess. |
| CR02 / C06,C07,C10 wake races | Response/steering/cancel arrives (a) before wait is checkpointed, (b) after pause, (c) after resume before acknowledgement, and exact duplicate after restart. Durable outbox survives each case; one consumed effect, no concurrent graph invocation. Cancel wakes human/export wait without becoming approval. |
| CR03 / C06,C07 pending input | Ambiguous input A blocks publication; later B resolves A, then repeat with B cancelling or superseding A. B must not wait forever behind A. Explanation-only response keeps semantic decision pending. Same idempotency key across inputs/responses applies once, different body conflicts. |
| CR04 / C06,C09 late work | Race free text/claimed-preference contribution against model explanation, evidence attachment and file patch. Test both commit-before-input and input-before-commit orders. Raw stale receipts/usage persist; no stale artifact becomes current. True typed depth-only input does not cancel. |
| CR05 / C08,C10 budgets | Force transient error then malformed result then error: exactly 3 attempts, not 3x3. Repeat receipt/admission consumes/settles same reservation once. Crash/author wait with running job and absolute expiry cannot reset budget. Unknown usage retained; no summary call when exhausted. |
| CR06 / C09,C10 projection | External edit before projection and crash mid multi-file projection preserve both versions; unowned external checkout never auto-overwritten. Immutable sources drive execution; incomplete projection cannot masquerade as complete checkout. Restart and second controller cannot both publish. |
| CR07 / C01,C08 scope | Explanation-only task stops after current answer, no repair or approval ceremony. Valid witness satisfies diagnostic return despite unresolved full proof; full delivery remains unsupported V3. Imported reviewed DP takes direct targeted route without forced greedy rejection. |
| CR08 / C02,C05 fixture validity | Alleged “omits empty choice” mutant under n>=1/positive weights is not automatically wrong; no fabricated killing case. Distinguish empty subset from invalid n=0. Separately test actual uninitialized-base bug. |
| CR09 / C04,C10 ingress/schema | Cross-run blob/response ID, forged actor/wake, stale schema, oversized contribution, HTML payload and cross-origin mutation fail safely. Original valid code/lemma/test hashes survive restart; derived proposal attribution remains separate. |
| CR10 / C09,C10 stage/release | Stage handoff includes current claims/inputs/open questions, continues only on author input. V3 export/restore mutation endpoints reject unsupported with no effects. Later V5 tests current/stale approval and each restore mode before enabling them. |

Enumerate CR02's four arrival/ack windows for each of response, steering and cancel (12 schedules), CR04's two commit orders for each of explanation, evidence and patch (6), plus the finite named outcomes/failpoints in remaining rows. Log seed, exact event list and assertion results. Add targeted schedules when failures reveal a missing window; retain original results. Crash recovery, database behavior and real OS file ownership still need actual platform tests; this bounded suite is not a concurrency proof.

Separate three kinds of evidence in every report: document-contract coverage, deterministic fake-model/worker behavior, and real worker/provider/author performance. A V3 fake-model demo claims workflow mechanics only. The 432-attempt main protocol and 72-attempt collaboration ablation remain later qualification targets, not prerequisites for writing V0 contracts or permission to call providers. Do not implement the entire evaluation platform before a small independently checked author session works.
