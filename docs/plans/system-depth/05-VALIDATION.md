# Validation and evaluation plan

## 1. Evidence from this audit

[selected-checks.json](evidence/selected-checks.json) records eight command checks
and a Python syntax-parsing pass across 58 files. All passed. The timing command
checks historical JSON, not fresh performance. These checks are a selected
subset of the existing QA suite, not a full regression run.

[audit-probes.json](evidence/audit-probes.json) records eleven isolated probes:
canonical-path filter gaps in two interfaces, omitted `.out` dependencies, stale
measurement flag, permissive corrupt consent, interactive report omissions,
duplicate renderer declarations, native execution default, ignored worker
controls, pending Judge0 success and a concurrent skill-limit invariant violation.
These observed defects are retained as baseline evidence. Desired tests must
assert repaired behavior rather than merely freeze these observations.

No new real-provider, live container, rendered-browser, formal-checker or DOMjudge
run was performed for this audit. Existing historical results are not discarded,
but they cannot certify the new architecture or current deployed behavior.

## 2. Test tiers

| Tier | Purpose and representative tests | Gate |
|---|---|---|
| Static/contracts | Syntax, typed schemas, duplicate declarations, tool/prompt/resource registry compatibility, documentation links | Every change |
| Pure domain | Comparison rules, group dependencies/nonfinite values, obligation/invalidation graph, role capabilities | Every affected change |
| Workspace/persistence | Revision conflicts, transactional writes, journal retention, corrupt metadata, backup/migration/restore | Every affected change |
| Agent with fake model | Tool selection, interrupted/resumed approvals, evidence-directed stages, retry/cancel/budget, compaction and mode policy | Every runtime/prompt change |
| Worker integration | Real sandbox limits, stdout/resource exhaustion, artifact confinement, no network/credentials, process cleanup | Required before execution changes land |
| API integration | Mutation ordering, settings round-trip, jobs/reconnect, canonical policy, structured errors | Every API/contract change |
| Browser behavior | Real result renderers, sample semantics, dirty-save failures, approval/evidence UI, stale responses, keyboard/AX | Required for affected UI changes |
| Package interoperability | Reference validation and DOMjudge import/judging for declared profiles | Required for packaging/judging changes |
| Provider behavior | Bounded authoring, proof critique, defect detection, malformed outputs, fallback and reported usage | Explicitly authorized evaluation runs |
| Independent-author pilot | Real author reasoning/workflow burden, package review and recovery | Developer-beta promotion |
| Formal-checker pilot | Known valid, invalid, admitted and mismatched-spec proof artifacts | Only formal feature promotion |

Do not add tests that merely compare copied implementation text. Test the
observable guarantee and include at least one case that would distinguish a
plausible wrong implementation. Do not install/run all integrations implicitly
from a fast local test command.

## 3. Required adversarial test matrix

| ID | Behavior | Required expected result |
|---|---|---|
| V01 | Path aliases with dots/separators/Windows case plus escaping links | Shared policy denies protected or escaping identity across all surfaces |
| V02 | Missing worker and explicit native launch | No generated code executes on app host |
| V03 | Candidate tries to write inputs or publish arbitrary files | Source unchanged, operation denied or disposable output discarded |
| V04 | Concurrent user edit during verify/export/worker publication | Conflict or exact immutable old revision, never mixed evidence/archive |
| V05 | Modify `.out`, checker, template header, reference, test or semantic assumption | Dependent evidence stale, unaffected evidence preserved |
| V06 | Interactive defect only on second/later input | Verification fails and saves full case evidence |
| V07 | Interactive successful run | Complete report, snapshot, statement and required limit evidence persisted |
| V08 | Package memory below worker default; custom process/stack/open-file/output controls | Actual limits enforced or request rejected as unsupported |
| V09 | Checker accepts everything/rejects valid output, crashes or invalid jury answer | Judge defect, never solver success/negative kill |
| V10 | Two inputs with different valid outputs and checker fixtures | Fixtures bind to intended inputs and verdicts are correct |
| V11 | More than 400 pending changes, rename/delete and executable side effects | Complete reviewable journal, no dropped pending obligation |
| V12 | Failure between file/journal writes, disk full, malformed JSON/SQLite | Explicit error/recoverable intent, original data preserved |
| V13 | Damaged consent, invalid/empty configured roots, hung MCP child | No grant expansion, bounded failure and reaped subprocess |
| V14 | Restore files, conversation and full session separately | Preview matches effect, pre-restore history retained, invalid approvals not resurrected |
| V15 | Review mode tries mutation or indirect execution | Code-level capability denial |
| V16 | Concurrent skill loads and missing required prompt component | Atomic active-limit enforcement and visible installation error |
| V17 | Stop queued/running/compiling/interacting/reviewing work | Terminal cancellation, no late writes and truthful UI |
| V18 | More than 600 events and server/browser restart | Gap detection and durable replay or explicit recoverable missing-evidence status |
| V19 | Nested reviews, retry, summary and fallback models | Role-aware event routing and per-model reported usage, enforced total budget |
| V20 | Specialized file/search/verification/reviewer tool output | Executed renderer shows meaningful evidence, not only raw JSON |
| V21 | Checker/float/interactive sample case, save failure and backend timeout | Server judging semantics, no stuck busy state, pending is not success |
| V22 | All settings fields plus clear token, invalid/nonfinite numbers | Consistent round-trip, validation and redaction |
| V23 | Reference and oracle share an incorrect assumption | Independent diagnostic witness or explicit unresolved evidence, no false proof label |
| V24 | Wrong surviving mutant and correct alternative labelled negative | Investigate correctly, preserve provenance and never weaken tests to obtain green |
| V25 | Correct proof idea but implementation overflow/indexing error | Separate implementation finding with code/witness evidence |
| V26 | Plausible proof missing a lemma or using an invalid precondition | Open blocking obligation, not auto-approved prose |
| V27 | Differential run with invalid input/broken oracle/budget exhaustion | Distinct incomplete/error classifications with reproducible diagnostic record |
| V28 | Reduction breaks input validity or loses the failure | Reduction rejected, original witness retained |
| V29 | Inapplicable metamorphic relation | Relation rejected or marked unestablished, no false defect report |
| V30 | Formal proof contains admissions/unapproved assumptions, or proves wrong spec | Fails selected proof profile or exposes mismatch explicitly |
| V31 | Extended-profile package exported to a narrower target | Explicit incompatibility or declared conversion, no silent data loss |
| V32 | Non-default WSL distro/port, spaced path, recycled PID, failed build | Correct project targeted, safe stop behavior and actionable failure |

## 4. Held-out behavioral benchmark

Proposed initial benchmark: 60 frozen cases, consisting of 36 seeded-defect
cases, 12 correct controls and 12 legitimately ambiguous/insufficient-evidence
cases. Cover the first three algorithm families plus specification, validator,
checker, interactive, implementation, stale-evidence and oracle failure cases.
Balance easy and subtle failures and include multiple outputs and grouped data.

Fixtures need a human-audited specification, expected defect/decision, minimal
witness where applicable, acceptable alternative explanations and a scoring
rubric. Keep grader/oracle artifacts outside the model-visible checkout.
Training examples, skill examples and demonstrations use a separate development
split. A benchmark case seen during tuning moves to development or requires a
new independently authored held-out replacement.

Compare baseline and revised system using matched model/provider configuration,
tool capabilities, seeds where supported and explicit budgets. Freeze baseline
results before tuning. Repeat runs to quantify model variability when the
authorized usage budget allows. Preserve failed/incomplete runs.

Metrics:

- Defect detection by category and severity, plus valid-witness rate.
- Correct-control false findings and unnecessary blocking.
- Proof-gap detection, argument quality under blind human review and
  distinction between mathematical and implementation correctness.
- Oracle/checker defects detected before solver conclusions.
- Repair correctness on untouched follow-up cases, not only the witness.
- Reproduction success, invalid reductions and stale-evidence mistakes.
- Human interventions, task completion and unresolved assumptions.
- Reported tokens, estimated/known/unknown cost, tool CPU/wall use and latency.

Proposed promotion thresholds, fixed before the evaluation rather than chosen
afterward: all critical integrity canaries pass, at least 33/36 seeded defects
detected, no more than 1/12 correct controls wrongly blocked, and at least 10/12
ambiguous cases handled with an appropriate clarification or uncertainty state.
All claimed deterministic reproduction results must replay. Every claimed
machine-checked proof must have a successful approved checker result and explicit
assumptions. These are initial targets, not measured achievements or statistical
claims of general reliability. Publish counts, uncertainty and category failures.

Human argument review uses a rubric for claim precision, assumption coverage,
logical support, boundary cases, code correspondence and clarity. Reviewer
identity is recorded as human or model. A model cannot grade its own proof as
the sole acceptance signal.

## 5. Performance and reliability

Measure fresh code on fingerprinted environments. Include cold/warm compile,
statement build, flat/grouped datasets, large inputs, custom checker,
interactive protocol, multiple references and mutation campaigns. Record
stage breakdowns and distinguish CPU from scheduling/staging overhead.

Retain the current 900-second verification budget only as a starting policy.
Do not assert a new budget from one historical 834-second run. Evaluate
representative sizes and negotiate long jobs as explicit bounded campaigns.

Browser gates cover first load, editor load, long chat, evidence matrices,
large-file fallback, layout stability and bounded memory. Test light/dark,
reduced motion, keyboard-only operation and narrow/wide viewports. Run automated
AX checks plus an actual screen-reader session with a human sign-off.

Reliability gates include provider outages/rate limits, malformed tool output,
worker crash, disk exhaustion, corrupted state, interrupted migration, duplicate
requests, retries and cancellation during publication. Results must be
idempotent or explicitly conflict, never silently applied twice.

## 6. CI and release gates

Separate required jobs for fast contracts, Windows policy, real worker,
rendered browser and selected-format judging. Pin environments and attach raw
logs/manifests. Skip is not pass. The live-provider tier is opt-in with its own
authorization and hard spend/call/time limits.

Developer-beta promotion requires F1 integrity tests, migration/restore evidence,
the benchmark thresholds, current rendered accessibility checks and an
independent-author pilot. Proposed pilot: three authors and twelve nontrivial
problems spanning the initial domains and custom judging, with intervention
counts, defects and final package round trips. Expand later toward real contest
use and broader author coverage before making a battle-tested claim.
