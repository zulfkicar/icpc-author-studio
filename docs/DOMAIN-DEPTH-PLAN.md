# Domain depth and correctness scope

Date: 2026-11-10
Status: scoped follow-up, not implemented

> Expanded by the [full system audit and implementation plan](plans/system-depth/README.md)
> on 2026-11-10. Use that package for the current source findings, ordered
> backlog, validation, architecture and rollout. This document retains the
> original depth/correctness scope.

Build depth across skills, tools, prompts and evaluation. The framework should
help an author derive, challenge and justify a problem and its solutions, then
connect that reasoning to executable evidence and the delivered package.
Longer prompts or more reviewer calls alone do not meet this scope.

This extends the [master plan](MASTER-PLAN.md). Existing runtime and package
verification remain in place. New capabilities below are requirements, not
claims about current behavior. Historical implementation notes remain historical.

## 1. Source audit

The 2026-11-10 audit found useful infrastructure with limited domain procedures:

| Owning source | Observed behavior | Required depth |
|---|---|---|
| `skills/test-design/SKILL.md` | Five steps and a short output list | Executable coverage plan, independent oracles, reproducible counterexample search and failure diagnosis |
| `skills/validator-design/SKILL.md` | Five general checks | Constraint-to-check mapping, valid boundary fixtures, malformed fixtures and tests of relational constraints |
| `skills/domain-taxonomy/SKILL.md` | Tags, intended technique and alternatives | Applicability conditions, derivation, proof patterns and failed approaches for supported domains |
| `skills/negative-solutions/SKILL.md` | Defect families and expected killing test | A justified defect per mutant, a witnessed failure and a test-by-mutant verdict matrix |
| `prompts/workflow.md` | Linear workflow that stops when verification is green | Explicit correctness obligations, adversarial review and unresolved-finding handling |
| `graph_agent.py` reviewer prompts and `_run_review_subgraph` | Read-only specialist workers return a prose `review` | Bounded review tasks with structured findings, referenced artifacts and explicit dispositions |
| `agent.py` tool dispatch | File operations, execution and package actions | Reusable domain analyses with typed inputs, persisted results and reproducible runs |
| `skill_registry.py` | On-demand loading, two active skills, bounded pinned text | Short procedures plus selectively retrieved examples and references within the existing context budget |
| `qa/test_skills.py` | Registry, loading and prompt assembly checks | Behavioral evaluations of whether skills improve defect detection and authoring decisions |

These observations concern the procedure and evidence layers. They do not imply
that the runtime, isolation or existing deterministic tests are superficial.

## 2. Correctness artifacts

Each problem needs a linked set of artifacts:

1. **Specification:** input domain, output predicate or objective, edge-case
   semantics, numeric bounds and assumptions, each with a stable identifier.
2. **Algorithm derivation:** candidate approaches, why constraints permit or
   exclude them, the intended insight and known alternative solutions.
3. **Proof obligations:** claims, assumptions, dependencies, reasoning and open
   gaps. Include feasibility, completeness or optimality as applicable, plus
   termination and relevant boundary cases.
4. **Complexity analysis:** worst-case operation and storage bounds, recursion
   depth, numeric ranges and the relationship to measured limits.
5. **Implementation correspondence:** map each important obligation to the
   actual source revision and implementation details such as tie handling,
   initialization, overflow and indexing.
6. **Executable evidence:** oracle agreement, exhaustive or seeded search,
   metamorphic checks, validator/checker self-tests and negative-solution kills.
7. **Review findings:** claim challenged, evidence, severity, resolution and
   remaining uncertainty. An agent cannot mark its own work human-approved.

Use explicit evidence labels: `unresolved`, `counterexample-found`,
`tested-within-bounds`, `reasoning-reviewed` and `machine-checked`. These labels
describe different evidence, not one interchangeable ladder of certainty.
A bounded exhaustive check states its exact domain and does not claim an
unbounded proof. Model agreement does not create a machine-checked guarantee.

Artifacts must record input hashes, dependency IDs, producer/version, run ID,
parameters and bounded artifact references where applicable. Changing a
statement, algorithm, checker or implementation invalidates the evidence that
depends on it. Preserve previous evidence with a stale label rather than
silently replacing its history.

## 3. Skill contract

Every substantial skill must include:

- Trigger, prerequisites, supported problem families and limits of applicability.
- A decision procedure that explains which check to choose and why.
- Required inputs and outputs with a worked example.
- A failure example, misleading apparent success and recovery procedure.
- Relevant tools, bounded execution parameters and interpretation of results.
- Completion conditions, unresolved conditions and when to ask the author.
- Reference material with provenance and review/version information.

Keep `SKILL.md` focused on the procedure. Put detailed examples, domain notes
and fixtures in referenced resources. Add bounded, workspace-safe skill-resource
retrieval before relying on resources that the current loader cannot expose.
Do not raise the context budget simply to pin entire reference libraries.

Initial domain scope: greedy/exchange arguments, dynamic programming and graph
algorithms. Expand after these demonstrate depth. For each family, cover
recognition, derivation, proof obligations, alternative approaches, common
implementation defects and targeted tests. A domain tag alone is insufficient.

Example: for maximum-cardinality non-overlapping half-open intervals, an
earliest-start greedy candidate fails on `[0,10), [1,2), [3,4)`. A meaningful
greedy skill should derive the earliest-finish rule, state the exchange argument,
explain why the remaining subproblem is preserved, check endpoint semantics and
compare the implementation against subset enumeration on small instances.
The counterexample refutes earliest-start. Small-instance agreement does not
prove earliest-finish for every input.

## 4. Tool depth

The following are proposed capabilities, not registered tool names. Prefer
reusable deterministic primitives over a separate wrapper for every skill.

| Capability | Inputs | Required evidence |
|---|---|---|
| Specification audit | Requirement IDs, statement, validator and checker revisions | Covered requirements, mismatches and unresolved semantic questions |
| Differential/exhaustive search | Candidate, independently derived oracle, generator or finite domain, seed, budgets | Exact domain or seed, cases attempted, agreement/disagreement, source hashes and reproduction command |
| Counterexample reduction | Failing input, validity predicate, failure predicate, budget | Smaller valid witness preserving the failure, reduction trace and replay result |
| Mutation evaluation | Defect-labelled negative sources, test suite, judge contract | Per-test/per-mutant verdicts, survivors, compile failures and actual killing witnesses |
| Metamorphic evaluation | Stated relation, applicability conditions, generator, checker | Original/transformed case references, expected relation and observed violation or bounded agreement |
| Validator/checker audit | Requirement IDs and valid/invalid fixture matrix | Expected/actual outcomes, crashes, ambiguous cases and missing fixture classes |
| Correctness evidence tracking | Obligations, dependency hashes, findings and result references | Missing/stale evidence, unresolved findings and current readiness summary |
| Optional formal checking | Formal specification, proof sources, pinned checker and assumptions | Checker exit/result, exact checked proposition, assumptions and trusted boundary |

All runs use the existing executor boundary and explicit case/time/memory/output
budgets. Return `incomplete`, `cancelled` or `budget-exhausted` when appropriate,
never a success inferred from missing output. Do not run generated harnesses on
the application host. A reducer must preserve both input validity and failure.

Retain current secret-test/answer read restrictions. Perform comparisons in the
executor and return scoped summaries. Only expose concrete witnesses from
author-visible diagnostic inputs. Protected evaluation inputs and answers must
not become model context through logs, reducer output or tool errors.

An oracle needs its own justification. A renamed copy of the candidate is not
independent. Brute force is useful because it can implement a simpler, separately
derived specification on a smaller domain. Record common assumptions and any
remaining shared failure modes.

## 5. Prompt and orchestration depth

Prompts must specify an artifact contract and evidence-driven branches:

1. Resolve semantic ambiguity and establish the specification.
2. Derive candidate approaches and correctness obligations before generating
   answers from a reference implementation.
3. Implement and inspect correspondence with the argument.
4. Attempt refutation using an independent oracle, counterexamples, boundary
   cases and applicable metamorphic relations.
5. Review the validator, checker and test suite, including surviving mutants.
6. Repair the cause, preserve the failing witness and rerun affected checks.
7. Run package verification and reconcile all blocking review findings.
8. Present evidence and unresolved assumptions for human review and export.

Keep working notes concise. Persist editorial arguments, claims and evidence,
not a requirement to expose unrestricted internal reasoning.

Specialist reviews need narrow questions and sufficient read-only context.
For example, ask a reviewer to find a violation of a particular invariant or
an unsupported step in an exchange argument. Findings must identify the claim,
source revision, evidence and next check. Different roles on the same provider
are separate review attempts, not evidence of independent ground truth.

When a negative survives, distinguish an actually correct alternative, a weak
suite, a faulty checker and an invalid defect assumption. Require evidence
before reclassification. Do not delete a difficult-to-kill negative merely to
obtain a green report. No findings returned is not proof of correctness.

Package verification continues to describe the checks it actually performs.
Add a separate correctness-review readiness state. The new authoring completion
policy must require resolved blocking obligations and human review. Preserve
the existing verification, snapshot and approval gates, and provide an explicit
migration policy for older workspaces with missing correctness artifacts.
Formal verification remains selective, with no claim that every supported
problem or language has a machine-checked solution.

## 6. Delivery sequence and acceptance

| Milestone | Deliverable | Acceptance evidence |
|---|---|---|
| D1: evidence foundation | Typed obligations, dependencies, findings, artifact storage and staleness rules | Changed source/assumption invalidates dependent evidence, restart retains records, legacy workspaces stay readable |
| D2: first deep skills | Solution correctness, greedy, test design, validator design and negative solutions, plus bounded reference retrieval | Each includes a complete worked case and failure case, loaded material stays within context limits |
| D3: executable refutation | Differential/exhaustive runner, reducer, mutation matrix and reusable self-test records | Seed replay reproduces a witness, reducer preserves validity/failure, broken oracle is surfaced, budgets stop reliably |
| D4: workflow integration | Structured specialist findings, evidence-directed phase prompts and correctness-review UI | Green package verification cannot silently resolve an open proof gap, stale evidence is visible, approval remains human-controlled |
| D5: measured depth | Held-out behavioral evaluation and DP/graph skill expansion | Compare baseline and revised system using the same fixtures, provider configuration and explicit usage budget |
| D6: selective formal checking | One justified formalization pilot with pinned checker | Valid proof accepted, intentionally broken proof rejected, assumed specification and implementation connection disclosed |

D1–D5 are the core depth program. D6 is a scoped extension. Formalization must
not consume the whole project before the everyday authoring procedures improve.
No provider evaluation or additional service launch is authorized by this plan.

## 7. Evaluation that demonstrates depth

Keep held-out fixtures outside agent-visible skills and examples. Include:

- Wrong greedy choice with a plausible editorial and a small counterexample.
- DP recurrence with missing states or incorrect initialization.
- A graph algorithm used outside its preconditions.
- Correct pseudocode with overflow, indexing or tie-handling defects in code.
- A validator missing a relational constraint and a checker accepting invalid output.
- Candidate and reference sharing the same wrong assumption.
- A genuinely correct alternative labelled as a negative, and a genuinely wrong
  surviving mutant that must not be removed without investigation.
- Correct controls to measure false alarms and needless blocking.
- Changed statements or source after review, cancellation and budget exhaustion.

Score defect detection, valid witness rate, false positives, proof-gap detection,
oracle defects found, reproduction success, repair correctness on held-out cases,
human interventions, run latency and actual reported provider usage. Do not score
proof quality by prose length, skill count or agent self-assessment.

Define the rubric and acceptable regression thresholds before evaluating.
Use deterministic checks where feasible and blind human review for argument
quality. Real-provider runs require their own bounded authorization. Record
provider/model configuration and disclose uncertainty from a small sample.

## 8. Completion rule

This scope is complete when representative problems leave inspectable
specifications, correctness arguments, source correspondence, reproducible
refutation attempts and resolved review findings, and held-out evaluation shows
improvement over the current baseline. Documentation and tool registration alone
do not establish domain depth or general correctness.
