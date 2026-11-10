# Skills, prompts, tools and specialist depth

All entries below are planned. Keep registry metadata and runtime schemas
generated or checked against one source of truth. Do not confuse a name in a
catalog with an implemented, validated capability.

## 1. Minimum skill standard

Each skill needs applicability and prerequisites, a decision procedure, bounded
tool recipes, a worked success, a misleading failure, diagnostic branches,
required artifacts and completion/escalation conditions. Include licensing and
provenance for references, fixtures and adapted code.

Keep the entry procedure short enough to load. Retrieve additional examples
and references by typed resource ID with size limits. Version the skill and
resource manifest together. Never search arbitrary host files or automatically
retrieve private contest solutions as generic skill material.

## 2. Improve every existing skill

| Existing skill | Add / improve | Required artifact and meaningful acceptance case |
|---|---|---|
| `constraints` | Separate per-item vs aggregate bounds, operation counts, integer products, precision, recursion and output size. Map every bound to validator/reference checks. | Bound table and semantic IDs. Detect a sum-of-n constraint omitted from a validator and a 64-bit intermediate overflow. |
| `domain-taxonomy` | Move from tags to applicability tests, derivation, proof patterns, alternatives and unintended easier approaches. | Approach comparison and assumptions. Reject Dijkstra when a negative-weight condition is allowed. |
| `difficulty-calibration` | Separate insight, prerequisite knowledge, implementation burden and test sensitivity. Use attributed local calibration examples and human solve evidence. | Rubric with uncertainty. Revise a difficulty estimate when a simpler valid approach is found. No unsupported contest rating. |
| `test-coverage` | Requirement-to-test and defect-to-test coverage, independent oracle coverage, excluded cases and risks. | Coverage matrix with evidence links. A high test count must not conceal a missing connectedness or duplicate-value case. |
| `test-design` | Exhaustive-small, seeded-random, structural-adversarial and maximum-shape generation recipes. Define oracle independence and reproducibility. | Versioned generator manifest and campaign results. Find a known DP initialization error using a simple independent oracle. |
| `negative-solutions` | Mutants tied to a stated defect, valid witness, expected failure class, per-test verdicts and survivor investigation. | Mutation matrix. Distinguish an actually correct alternative from a wrong survivor without deleting either to hide a problem. |
| `validator-design` | Grammar, token/line/trailing-data semantics, relational constraints, valid-boundary and invalid-input fixtures. Separate validator crash from intended rejection. | Constraint/check/fixture matrix. Reject an out-of-range edge endpoint and accept an unusual valid boundary case. |
| `checker-design` | Feasibility vs optimality, multiple valid outputs, jury-answer assumptions, numeric tolerances, overflow, malformed output and checker failure handling. | Per-input expected-verdict fixtures. Accept two distinct valid constructions, reject a feasible suboptimal one where optimality is required. |
| `interactive-design` | State/transition protocol, query budgets, flush/EOF/deadlock handling, adaptive adversaries, per-case seeds and replay. | Protocol model and adversarial transcript matrix. Kill an early-exit solution and detect interactor crash as judge error. |
| `statement-quality` | Formal-to-natural-language correspondence, quantified semantics, indexing/ties, examples explained by hand, accessibility and editorial separation. | Requirement-linked findings. Catch a mismatch between “at most” in prose and “exactly” in the reference. |
| `performance-limits` | Adversarial input shapes, repeated measurements, CPU vs wall metrics, toolchain/hardware provenance, slow accepted and fast intended-TLE separation. | Measurement distribution and justified limits. Warn if measured cases do not realize the claimed worst-case shape. |
| `verifier-audit` | Audit the oracle/checker before assessing solver behavior, investigate suspicious passes, sample fixtures beyond the first, trace evidence freshness. | Structured audit findings. Detect an accepts-everything checker and a stale measurement instead of trusting a green aggregate. |
| `delivery` | Format profile, all three readiness facets, rights/source metadata, archive member audit, clean re-import and exact-revision approval. | Delivery manifest. Block export when an obligation remains open or archive dependencies are missing. |

## 3. Add missing skills

| New skill | Core procedure | First scope / acceptance |
|---|---|---|
| `problem-specification` | Translate idea into domain, predicate/objective, assumptions and unresolved semantics. | Half-open vs closed intervals and impossible-output behavior must be explicit. |
| `solution-correctness` | Build obligations for feasibility, optimality/completeness, termination and boundaries, then map to implementation. | A plausible editorial with a missing exchange step remains unresolved. |
| `complexity-analysis` | Derive time/storage bounds including amortization, recursion, language overhead and intermediate numeric sizes. | Detect a hidden nested traversal and avoid claiming measurements prove asymptotics. |
| `greedy-reasoning` | Derive candidate rule, establish exchange/stays-ahead/cut argument as applicable, search for counterexamples. | Interval scheduling: refute earliest-start, justify earliest-finish under stated assumptions. |
| `dp-reasoning` | Define state semantics, transitions, base cases, evaluation order and induction proof. | Detect an incomplete state and a zero/default initialization that admits impossible states. |
| `graph-reasoning` | Establish graph model/preconditions, invariant and edge-case semantics. | Shortest path, connectivity and traversal cases, including disconnected graphs and multiedges. |
| `oracle-design` | Prefer simple independently derived solvers, validate their own domain, compare multiple formulations and disclose shared assumptions. | A copied reference cannot be labelled independent merely because it is renamed. |
| `counterexample-search` | Choose bounded finite/seeded campaigns, validate every witness and preserve reproduction artifacts. | Reproduce a failure after restart with the same revision, seed and budget. |
| `counterexample-reduction` | Select domain-aware reductions and preserve validity and the original failure predicate. | A disconnected or out-of-range reduced input is rejected as an invalid reduction. |
| `metamorphic-testing` | State relation and applicability before transforming inputs. | A permutation relation must be rejected for an order-dependent task. |
| `implementation-audit` | Trace proof assumptions into code, check numeric types/indexing/ties and compiler behavior. | Correct pseudocode with a narrow integer product yields a concrete implementation finding. |
| `formal-proof` | Establish formal statement, trusted assumptions and toolchain, check proof and implementation connection. | One small bounded pilot, admitted/incorrect proof rejected under the chosen profile. |

Later domain packs: data structures, strings, number theory/combinatorics,
geometry/numerical reasoning, constructive algorithms, game theory, flows/matching
and advanced interactive strategies. Each must meet the same evidence standard.
Do not ship a large set of tag-only skills to imply broad expertise.

Problem originality, educational value and rights deserve an authoring review
procedure. Start with user-provided references and a provenance log. Any future
network literature/archive search must be explicitly scoped, respect contest
confidentiality and return similarity evidence rather than a plagiarism score.

## 4. Audit every prompt component

| Current prompt/source | Improve | Validation |
|---|---|---|
| `prompts/base.md` | Define authority, evidence labels, capability boundaries, uncertainty and goal/completion rules precisely. Avoid treating deterministic package checks as proof of semantics. | Agent cannot convert prose into a verified/proved/approved state. |
| `prompts/workflow.md` | Replace the linear stop-at-green recipe with stages and failure-directed return paths from the architecture. | A green package with an open correctness finding stays incomplete. |
| `prompts/tools.md` | Describe prerequisites, result states, budgets, artifact retrieval and error/retry rules for actual registered operations. | Unsupported capabilities are not invented and judge errors are not treated as negative kills. |
| `prompts/spec.md` | Bind instructions to selected format profile, distinguish product policy from official requirements, retrieve versioned details as needed. | Legacy/extended profile cases produce explicit differences without silent conversion. |
| `prompts/modes/author.md` | Require specification, obligations, implementation evidence and author-visible progress with bounded next steps. | Derivation is recorded before self-generated answers are trusted. |
| `prompts/modes/debug.md` | Diagnose source/input/oracle/checker/infrastructure defects, preserve the witness and rerun the affected dependency set. | No weakened validator/test/constraint as a shortcut to green. |
| `prompts/modes/review.md` | Restrict capabilities in code, provide a narrow review brief and structured finding contract. | A review-mode mutation attempt is rejected by policy independent of prompt adherence. |
| Role strings in `graph_agent.py` | Move to versioned role resources with relevant evidence, task-specific questions and call/time budgets. | A reviewer cites the actual revision and obligation rather than generic advice. |
| `agent.SYSTEM` fallback | Keep authority consistent or fail startup for an incomplete installation. | Missing base/workflow/spec components cannot silently produce a weaker partial prompt. |
| Eval kickoff/repair prompts | Separate authoring convenience from adversarial grading. Require evidence before reclassifying negatives. | A wrong surviving solution remains an investigated defect. |
| Dynamic pinned context | Include compact current readiness, assumptions, open findings, evidence IDs and staleness. | Compaction preserves the current semantic decisions and does not leak protected data. |

Version and hash complete prompt bundles. Evaluate prompt changes against
behavioral fixtures, including regressions and cost, rather than judging prose.

## 5. Audit every current tool family

The explicit `TOOLS` list and middleware-injected tools must be enumerated by
an automated registry check. Reviewer wrappers need the same shared policy.

| Current tool(s) | Improve / enhance |
|---|---|
| `list_files` | Canonical scoped listing, pagination, stable identities, no hidden-root traversal or symlink cycles. |
| `read_file` | Canonical visibility, byte/line bounds, revision/hash in result, clear binary and truncation status. |
| `search_workspace` | Shared visibility, bounded scan/cancel, meaningful continuation and source revision. |
| `list_tests` | Use package discovery rather than duplicated assumptions, summarize groups and permitted coverage without leaking protected content. |
| `write_file`, `delete_file` | Expected-revision transactions, atomic file/journal updates, reversible changes and uniform capability enforcement. |
| `run_command` | Retain a constrained developer primitive, require executor capabilities, bind inputs and side effects, return declared artifacts. Add typed domain operations so prompts need not author ad hoc harnesses for routine analysis. |
| `build_answers` | Validate inputs/oracles first, preserve disagreements, publish answers transactionally and record exact generator/reference dependencies. |
| `measure_limits` | Typed limits protocol, repeated representative runs, stale measurement detection and manual-policy rationale where necessary. |
| `verify_package` | Uniform lifecycle across modes, immutable revision, cancellation, full matrix, explicit skips and judge/infrastructure failures. |
| `read_report`, `report_summary` | Return report revision, freshness, scope, critical blockers and paged detail. A historical green status must not appear current. |
| `export_package` | Approval bound to exact revision and archive membership, reproducible transformation manifest, no mutable post-check reads. |
| `update_brief`, `record_decision`, `set_focus` | Stable IDs, provenance, supersession and bounded durable state. Keep specification/evidence entities separate from free text. |
| Middleware `write_todos` | Task dependencies and completion evidence references. Agent marking a todo complete cannot resolve an obligation automatically. |
| `ask_user` | Ask only consequential unresolved semantics, show affected work, persist answers with provenance and invalidate dependent assumptions when changed. |
| `list_skills`, `load_skill`, `unload_skill` | Typed metadata, compatibility, atomic active-set enforcement, resource retrieval and incomplete-bundle errors. |
| `review_package` | Structured package/specification findings with permitted artifacts and clear human resolution boundary. |
| `ask_test_designer` | Requirement/defect coverage and executable proposals, independent oracle plan and missing-case rationale. |
| `ask_verifier_auditor` | Validate trust in checkers/oracles, report freshness and result semantics before accepting aggregate success. |
| `reviewer_list_files`, `reviewer_read_file`, `reviewer_report` | Central policy, canonical file identity, shared revision and role-specific summaries. |
| MCP tools | Same policy and result contracts as internal read operations, strict consent-root handling, timeouts and protocol validation. |

## 6. New deterministic operations

Operation names are illustrative until schemas and compatibility are agreed.

| Operation | Required inputs | Result and failure handling |
|---|---|---|
| `audit_specification` | Requirement IDs, statement, validator/checker references | Explicit mismatches, unresolved semantics and checked coverage. Heuristic text mappings remain labelled proposals. |
| `record_obligation` / `link_evidence` | Claims, assumptions, revision and artifact refs | Typed records with validated dependencies. No tool lets the model label its claim machine-checked. |
| `run_differential` | Candidate, independent oracle, validated generator/domain, seed and budgets | Agreement within stated domain or a replayable witness; oracle/infrastructure errors stay distinct. |
| `reduce_counterexample` | Witness, validity predicate, failure predicate and budget | Valid reduced witness plus reduction trace and replay. |
| `run_mutation_matrix` | Defect-labelled sources, test manifest and judge contract | Per-mutant/test verdict matrix, survivors, invalid mutants and suspicious kills. |
| `run_metamorphic` | Stated relation, conditions and transformation manifest | Observed relation results, finite scope and invalid transformations. |
| `audit_validator` | Constraint map and bound/invalid fixtures | Expected/actual outcomes and crash/uncovered-constraint findings. |
| `audit_checker` | Per-input candidate/jury outputs with expected outcomes | Soundness/completeness evidence matrix and judge-error diagnostics. |
| `replay_evidence` | Recorded run ID and compatible environment | Reproduction result or explicit nonreproducibility with reason. |
| `check_formal_proof` | Formal spec/proof, allowlisted checker and assumption profile | Checked proposition, admissions/axioms, source hashes and trusted boundary. |
| `get_correctness_readiness` | Workspace revision and authoring profile | Computed facets and blockers, never a model-assigned badge. |
| `read_skill_resource` | Registered skill/resource ID, range/size bound | Attributed versioned content within the model-context budget. |

Require shared typed envelopes: run/revision IDs, outcome, evidence references,
metrics with units, redacted diagnostics, truncation and staleness. Tool schema,
API response and UI renderer must change together with contract tests.

## 7. Specialist roles

Use existing read-only reviewers where sufficient. Add a role only when a
distinct question, input set and evaluation justifies it:

- Specification critic: ambiguous semantics, satisfiability and output predicate.
- Algorithm/proof critic: unsupported lemmas and violated preconditions.
- Implementation auditor: code correspondence and language-level defects.
- Test/oracle designer: independent oracle, coverage and refutation campaigns.
- Judge/verifier auditor: checker/interactor behavior and evidence integrity.
- Difficulty/editorial reviewer: unintended approaches, explanation and solve burden.

Do not recursively delegate by default. Give roles task-wide budget shares and
record model/provider identity. Same-model reviewers may share a blind spot.
The author resolves findings through evidence, and the human retains approval.
