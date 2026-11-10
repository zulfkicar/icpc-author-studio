# Ordered implementation backlog

All tasks are planned unless later evidence explicitly changes their status.
The audit artifacts already exist, but do not establish completion of the
implementation tasks below. Sizes: S bounded, M several contracts, L subsystem
or multi-environment work. Owner names identify responsibilities, not people.

Every task must attach: affected requirement/finding IDs, source revision,
implementation diff, meaningful validation output, remaining limitations and
rollback notes when persistence or execution changes. Preserve originals.

## F0 — Baseline and invariants

| ID / size / owner | Task and source scope | Dependencies | Acceptance evidence |
|---|---|---|---|
| T01 / S / integration | Capture an implementation baseline using this inventory, local test taxonomy and selected known-good packages. A21/A35. | None | Source/prompt/template hashes, toolchain/image identities, test pass/fail/skip list and immutable sample packages recorded. Any unavailable backend explicitly unknown. |
| T02 / M / architecture | Define shared revision, policy, execution-result and evidence invariants. Spike storage compatibility with checkpoints. A04/A05/A11/A15. | T01 | Versioned schemas and migration decision, rejected malformed/unsupported inputs, crash/recovery strategy and no ambiguous source of truth. |
| T03 / M / QA | Convert audit probes into desired-behavior regression cases in isolated fixtures, preserving the original observation artifact. A01–A14/A23/A26. | T01 | Tests fail for the recorded defects before fixes, with no provider calls or access to private workspaces. |

## F1 — Execution and package integrity

| ID / size / owner | Task and source scope | Dependencies | Acceptance evidence |
|---|---|---|---|
| T04 / S / runtime | Fail closed for generated-code execution in native and compose launches. `winutil.py`, server/startup. A01. | T02/T03 | Missing/unhealthy worker prevents execution. Explicit developer-only override is tested and never silently selected. |
| T05 / M / policy | Centralize canonical path/visibility checks. Tools, context, MCP, backend routes and archive paths. A02/A13. | T02/T03 | Dot/separator/case/link aliases cannot expose protected sentinels or escape roots on Windows/Linux. Valid authorized paths still work. |
| T06 / L / execution | Introduce versioned worker request/result and resource-capability contracts. Clients and both workers. A05/A33. | T02 | Package memory and all declared controls reach workers. Unsupported controls reject. CPU/wall/memory/output/judge/infrastructure outcomes are distinct in live tests. |
| T07 / L / execution | Immutable input staging and per-operation readable resources. Both workers. A04/A06/A29. | T05/T06 | A candidate cannot change source inputs, read unrelated package resources or publish undeclared artifacts. Concurrent runs have separate staging/build areas. |
| T08 / M / workspace | Replace arbitrary workspace synchronization with transactional artifact publication and complete mutation recording. A06/A09/A10. | T07 | Outdated worker results cannot overwrite newer files. Answers/build outputs follow declared destinations, review rules and hashes. |
| T09 / M / verifier | Unify verification setup, deadlines, error aggregation, snapshot and report persistence across modes. `verify.py`. A03. | T06/T07 | Standard/interactive/checker failures all create complete revision-bound reports, and cancellation produces no new verified state. |
| T10 / L / verifier | Run interactive references/negatives across the full applicable corpus, validate inputs and limits, compile statements, and audit protocol behaviors. A03/A19. | T09 | A defect in the second test fails verification. Wrong-query/EOF/deadlock/interactor-crash cases have correct verdicts and persisted evidence. |
| T11 / M / judge | Repair checker fixture binding and judge-error semantics. `verification_modes.py`. A19/A33. | T06/T09 | Fixtures bind to specific input/answer pairs. Invalid jury answers and checker crashes are judge errors. Multiple valid outputs are accepted where allowed. |
| T12 / M / packaging | Freeze verified/approved export revision and reconcile archive/dependency membership. `verify.py`, manifests. A04/A07/A34. | T08/T09 | Editing during export cannot produce a mixed archive. ZIP hashes match the approved staged manifest, including required groups/checker dependencies. |
| T13 / M / operations-security | Review worker ports/tokens/networks/privileges and fresh-install defaults. Compose and service handlers. A29. | T06/T07 | Service access, child network denial, credential separation and required privileges documented and live-tested. Residual privileged-container risk remains explicit. |
| T14 / M / runtime | Propagate one deadline and cancellation token through model calls, tools and workers. A20/A31. | T06/T09 | Cancel before queue/start/during compile/run/protocol waits stops work, reaps child processes and rejects late artifact publication. |

F1 gate: affected integrity guarantees pass fresh adversarial checks. No new
correctness badge or autonomous campaign depends on unfixed F1 contracts.

## F2 — Persistence, state and controls

| ID / size / owner | Task and source scope | Dependencies | Acceptance evidence |
|---|---|---|---|
| T15 / M / evidence | Manifest dependencies and invalidation for reports, measurements, checker fixtures, global templates and toolchains. A07/A08/A34. | T02/T09 | Every consumed input has an identity/hash. Editing `.out`, a reference, template or assumption stales exactly the dependent evidence. |
| T16 / L / persistence | Durable change journal and crash-consistent file/state writes. Quarantine corrupt state, retain unreviewed records and journal rename/folder actions. A10/A11. | T02/T08 | Failure between file and journal updates recovers deterministically. More than 400 pending changes remain reviewable. No corruption silently becomes empty state. |
| T17 / M / policy | Correct consent initialization/recovery and strict roots, add MCP deadlines and cleanup. A12/A13. | T05/T16 | New-workspace defaults remain deliberate, corrupt previous consent does not broaden grants, invalid roots deny, hung protocol requests terminate. |
| T18 / M / persistence | Separate conversation, file and full-session restore. Preserve old checkpoint branches and snapshot history. A32. | T16 | Restore preview matches actual changes. Selected decisions/mode/skills/approvals are restored or explicitly excluded, and pre-restore history remains recoverable. |
| T19 / M / configuration | One settings schema across UI/API/storage/env/client propagation. A27/A28. | T02/T16 | Every setting round-trips or is explicitly environment-only. Isolate URL and Judge0 token work as advertised. Invalid/nonfinite values rejected and secrets cleared/redacted safely. |
| T20 / M / runtime-policy | Enforce author/debug/review and reviewer capabilities plus revision-bound approval effects. A14. | T05/T08/T15 | Review cannot mutate through write, execute or publication paths. Approval cannot be reused for a changed revision or expanded effect. |
| T21 / M / context | Enforce active-skill invariants after concurrent updates, validate prompt bundles and preserve evidence IDs through compaction. A16/A17. | T02/T05 | Concurrent loads cannot exceed the configured active limit. Missing required prompt files fail visibly. Dense context remains bounded and protected data excluded. |
| T22 / L / runtime | Durable jobs/events, queue state, retention and restart reconciliation. A31. | T14/T16 | Reconnect recovers ordered events, detects cursor gaps, distinguishes queued/running states and records interrupted jobs after restart without rerunning side effects. |
| T23 / M / observability | Role/run/model-aware events and reported-usage ledger. A36. | T22 | Reviewer output does not masquerade as the final author response. Retry/fallback/summary/specialist usage is attributable, estimates and missing usage labelled. |
| T24 / M / runtime | Task-wide model/tool/elapsed-time/cost budgets including nested reviews and evals. A18/A20/A36. | T14/T19/T23 | All call paths consume one budget. Unknown billing does not silently imply zero cost. Budget exhaustion saves a resumable incomplete result. |

## F3 — Deep authoring knowledge

| ID / size / owner | Task and source scope | Dependencies | Acceptance evidence |
|---|---|---|---|
| T25 / L / domain-evidence | Implement specification, approach, obligation, implementation-map, finding and review entities. A15. | T15/T16 | Records survive restart, validate dependencies and preserve reviewed vs tested vs machine-checked evidence distinctions. |
| T26 / M / orchestration | Evidence-directed authoring stages with re-open and incomplete paths. A17/A19. | T20/T24/T25 | Counterexamples reopen affected claims, green package checks cannot resolve open proof gaps, task closure references required evidence. |
| T27 / M / skills | Versioned skill/resource schema and bounded retrieval. A16. | T21 | A complete worked example can be retrieved without dumping the whole library, with provenance and budget enforcement. |
| T28 / L / CP-content | Rewrite all 13 existing skills to the catalog standard. A16. | T25/T27 | Each has concrete procedure, success/failure examples, required artifacts and at least one behaviorally graded fixture. |
| T29 / L / CP-content | Add specification, correctness, complexity, oracle and implementation-audit skills. A15/A19. | T25/T27 | Plausible but unsupported arguments remain unresolved. Actual code's numeric/semantic assumptions are mapped explicitly. |
| T30 / L / CP-content | Deep initial greedy, DP and graph packs with derivations and adversarial examples. A16. | T28/T29 | Each pack handles a correct case, invalid precondition and deceptive wrong solution, with an attributed reference/example manifest. |
| T31 / M / prompts | Rebuild base/stage/mode/spec/tool/role/eval prompt bundles around actual contracts. A17/A18/A34. | T26/T28/T29 | All catalog prompt components have behavioral acceptance cases, version hashes and no capability/format overclaims. |
| T32 / M / reviewers | Structured specialist review briefs/findings and evidence-based resolution workflow. A18/A19. | T24/T25/T31 | A reviewer identifies a particular unsupported claim, cites its revision, proposes a test, and cannot approve its own finding resolution. |
| T33 / M / CP-content | Difficulty, originality/rights and editorial review procedures with human judgment boundaries. A16/A30. | T28/T30 | Difficulty range responds to unintended solutions. Sources/rights are recorded, unsupported originality claims remain unknown. |

## F4 — Executable adversarial investigation

| ID / size / owner | Task and source scope | Dependencies | Acceptance evidence |
|---|---|---|---|
| T34 / L / domain-tools | Differential/exhaustive campaigns with independent-oracle manifest, generator validation, seeds and exact budgets. A19/A20. | T07/T14/T24/T25/T29 | Known defects yield valid replayable witnesses. Broken oracle, invalid generator and exhausted domain are distinguishable. |
| T35 / M / domain-tools | Counterexample replay and domain-aware reduction with validity/failure predicates. A19. | T34 | Reduction preserves the original failure and valid input. Protected fixtures cannot leak as reduced witnesses. |
| T36 / M / domain-tools | Test-by-mutant verdict matrix and survivor adjudication. A19. | T11/T25/T34 | Compile/judge/infrastructure failures do not count as valid kills. Correct alternatives cannot be discarded as failed mutants without evidence. |
| T37 / M / domain-tools | Validator grammar/constraint fixture audit. A16/A19. | T25/T34 | Valid edge cases accepted, malformed and relational violations rejected, validator crashes and coverage gaps surfaced. |
| T38 / M / domain-tools | Checker soundness/completeness fixture audit and interactive protocol campaigns. A03/A19. | T10/T11/T25 | Alternative valid outputs pass, semantic wrong/suboptimal outputs fail, protocol limits are exercised across cases. |
| T39 / M / domain-tools | Metamorphic relation registration, applicability checking and bounded execution. A19. | T34 | An inapplicable relation is rejected, valid relations detect a seeded defect and carry exact finite-scope evidence. |

## F5 — Integrated workbench and interoperability

| ID / size / owner | Task and source scope | Dependencies | Acceptance evidence |
|---|---|---|---|
| T40 / L / frontend | Extract transport/jobs/editor/chat/evidence/settings responsibilities and clarify state authority. A24. | T19/T22 | Existing journeys remain functional with tested stale-response suppression, workspace switching, dirty guards and reconnect. No broad cosmetic rewrite. |
| T41 / S / frontend | Remove duplicate result renderer and establish typed renderer registry. A23. | T02/T03 | Executed DOM tests show specialized file/search/verification/reviewer cards. Duplicate declarations/unknown result types are caught. |
| T42 / L / frontend | Specification, obligations, evidence, findings and separate readiness facets. A15/A18. | T25/T26/T32/T40/T41 | Author can trace a claim to code/evidence, see a stale dependency, resolve a finding and inspect exact approval scope using keyboard. |
| T43 / M / judge-frontend | Server-backed sample judging and robust save/run/cancel cleanup. A25. | T09/T11/T14/T40 | Custom checker/float/interactive cases use correct semantics. Save failures and cancellation restore usable UI state. |
| T44 / S / adapters | Pending/terminal Judge0 result handling and normalized backend capability/status display. A26/A27. | T06/T19 | Queued response remains pending, deadline expiry is not success, backend changes do not change verification authority. |
| T45 / L / packaging | Explicit legacy/DOMjudge/extended format profiles, typed metadata/program selection and reference-tool compatibility matrix. A33/A34. | T11/T12/T15 | Each supported profile validates/imports or reports precise unsupported features. Group files, validator dependencies and tolerances survive export correctly. |
| T46 / M / documentation | Current capability/evidence matrix and historical-doc reconciliation. A35. | T09/T20/T42/T45 | Every advertised capability links to applicable source/test evidence. Outdated plans remain labelled history and direct readers to the current plan. |

## F6 — Evaluation and operational beta

| ID / size / owner | Task and source scope | Dependencies | Acceptance evidence |
|---|---|---|---|
| T47 / L / QA-integration | Split fast, worker, browser, DOMjudge, recovery and provider test tiers. Add Windows/Linux policy coverage. A21. | T03/T09/T22/T43/T45 | Required integration jobs actually provision their backends. Skips are reported and cannot satisfy a required gate. Test data is isolated from private state. |
| T48 / L / evaluation | Frozen held-out benchmark, baseline/revised comparison, error taxonomy and blind human argument review. A20. | T30/T32/T34–T39/T47 | Predefined rubric, fixture/answer isolation, reproducible runs, false positives and usage reported. No tuning on held-out results without a new split. |
| T49 / M / performance | Fresh verification/UI/campaign benchmarks with environment fingerprints. A22/A24. | T40/T47 | Current source measured, including cold/warm runs and representative problem sizes. Historical JSON guard is not mislabelled a regression measurement. |
| T50 / L / product-QA | Independent-author pilot and real contest-package round trips. A20/A35. | T42/T45/T48/T49/T54 | Pilot checklist, human interventions, defect/repair evidence and author feedback recorded. Promotion criteria evaluated, not inferred from demos. |
| T51 / M / release | Install/use/backup/troubleshooting guides and explicit local-preview capability reporting. A35. | T46/T52/T53/T54 | A fresh user follows the guide without undocumented machine assumptions. No claim of hosted/multi-user support. |
| T52 / M / supply-chain | Transitive dependency/hash lock, container/vendor inventory, notices, root license decision and update policy. A30. | T01 | Reproducible clean build, component hashes and licenses recorded. A current vulnerability scan is separately dated and triaged, not implied by pinned versions. |
| T53 / M / operations | Harden WSL launch/stop/demo scripts for distro/project/port/PID and failure cleanup. A37. | T13/T19 | Non-default distro and path with spaces work. Stop verifies process identity and never terminates a reused unrelated PID. Failure leaves diagnostic state. |
| T54 / L / persistence-QA | Versioned migrations, backup/restore/upgrade rehearsals and rollback tooling. A11/A18/A32. | T16/T18/T22/T25 | Legacy workspaces migrate without automatic approval or lost history. Failed migration restores original data and reproduces hashes. |

## F7 — Selective expansion

| ID / size / owner | Task and source scope | Dependencies | Acceptance evidence |
|---|---|---|---|
| T55 / L / formal-methods | One formally specified/checked algorithm pilot, toolchain decision and proof artifact integration. A15. | T25/T29/T32/T48/T52 | Correct proof accepted, changed/unfinished proof rejected under policy, theorem assumptions and code correspondence disclosed. Separate bounded installation/run approval if needed. |
| T56 / L per pack / CP-content | Additional domain packs and calibrated editorial/originality workflows. A16. | T30/T48/T50 | Each new pack meets the same examples, failure cases and held-out behavioral gates before advertising support. |

## Dependency and scheduling rules

Critical path: T01/T02 → execution and revision integrity → T15/T16/T25 → deep
skills and domain tools → readiness UI → held-out evaluation → author pilot.
T41 is a small independently reviewable UI repair after its contract test exists.
Content curation and fixture design may proceed while runtime work is underway,
but runtime acceptance cannot be substituted with prose-only checks.

Do not batch all 56 tasks into one change. Prefer one cohesive contract or
vertical slice per review. Each slice must leave the existing application usable
or be disabled behind an explicit capability gate. Re-estimate after baseline
and schema spikes. Calendar scheduling and provider/compute budgets are future
execution decisions, not silently granted by this plan.

## Future work outside the core gate

Shared hosting/auth/RBAC, collaborative editing, managed credential vaults,
contest-wide operations, public deployments and a multi-agent engineering
organization are separate product decisions. Keep extension points, but do not
make this local author's correctness program depend on building those systems.
