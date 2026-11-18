# Author Studio roadmap

The next item is **V4 · T35, counterexample replay and reduction**. T34 now
finds reproducible mismatches in weighted interval scheduling. T35 will let
the author rerun one against the exact source and shrink it into a case they
can inspect, discuss, and keep as a regression. Version gates below give the
delivery order. Calendar dates are open.

## Where we are

| Track | Status | Evidence |
| --- | --- | --- |
| Studio Releases 1–4 | Implemented across the 58-item experience plan | Draft recovery and naming, daily workspace navigation, evidence and manual release review, then qualification of the scripted sample and a local DOMjudge import. Broader platform and author qualification sit in V6. [Release records](docs/design/product-experience/README.md) |
| Engine V0–V3 | Implemented as a bounded collaborative slice | Baselines and contracts, scoped effects, durable chat and steering, proof and test collaboration, and reviewable stage results. [Implementation record](docs/implementation/v0-v3/README.md) |
| Engine V4 | In progress locally | T34 passed 20 focused checks, including three compiled Isolate journeys. Planning in those journeys was scripted. [T34 verification](docs/implementation/T34-WEIGHTED-CAMPAIGNS.md) |

## V4 · Correctness investigation

| Order | Item | Done when |
| --- | --- | --- |
| ✓ | **T34 · Differential campaigns** | Weighted scheduling has a validated generator, independent subset oracle, seeded samples, a bounded exhaustive grid, and a saved receipt. |
| 1 | **T35 · Replay and reduce counterexamples** | Replay the saved input against the recorded candidate and endpoint rule. Reduce it within an explicit budget while independently rechecking legality and the same failure. Keep both witnesses and make stale source and non-reproduction visible in chat. |
| 2 | **T36 · Test-by-mutant matrix** | Show which cases catch each deliberately wrong solution and which mutants survive. Keep compile, worker and judging failures distinct from valid kills. Include a correct alternative as a control. |
| 3 | **T37 · Validator audit** | Try legal boundary cases and malformed or relationally invalid inputs. Show where the validator disagrees with the stated constraints, crashes, or leaves a gap. |
| 4 | **T39 · Scheduling relations** | Add a small set of relevant metamorphic checks with explicit preconditions, such as input permutation. An applicable check has bounded receipts and an inapplicable one is rejected visibly. The general registry follows in V7. |

**Exit gate.** Start from chat and find, replay and minimize a legal mismatch.
A correct alternative must pass, an invalid input must be rejected, and the
author must be able to steer the investigation and inspect the evidence.

## V5 · Evidence, history, and delivery

The saved-workspace flow already verifies, reviews and exports a package with
human approval. V5 connects that workflow to the engine's specification and
evidence, so the author can see why a particular revision is ready to review.

1. **Evidence and readiness** — Link statements, proof obligations, candidate
   source, tests and receipts. Show stale or unknown results beside the check
   that can resolve them. Cover keyboard navigation of evidence and review.
2. **Engine-backed delivery** — Assemble delivery readiness for the supported
   exact-output batch profile using the existing saved-workspace controls.
   Tie approval and ZIP generation to the exact verified snapshot. Exercise
   legacy import, stable naming, and a DOMjudge import from a clean profile.
3. **History and restore** — Browse prior decisions, candidate revisions and
   receipts. Preview and apply a deliberate restore, with dependent evidence
   and approvals re-evaluated against the restored state.
4. **Portability of a handoff** — Produce a shareable evidence summary with the
   chosen audience, source revision, remaining work, and allowed artifacts.

**Exit gate.** The author can inspect the evidence, approve and export the
exact verified revision, then see the approval become historical after an edit.
A restore round trip preserves provenance and requires fresh approval for
the restored snapshot.

## V6 · Qualification and local distribution

1. **Provider and worker conformance** — Test structured-output failures,
   disconnects, cancellation, usage limits, and isolation. Keep offline,
   compiled-worker, provider and browser results independently visible.
2. **Supported installs and recovery** — Rehearse clean Linux and Windows/WSL2
   setups, legacy migration, backups, upgrade and rollback. Pin toolchains and
   transitive dependencies and settle licensing and third-party notices.
3. **Independent evaluation** — Freeze the held-out corpus and rubric before
   scoring. Compare with a simple loop using the same tools and measure what
   collaboration adds. Record false positives, missed defects, usage and
   timings. Keep evaluation fixtures separate from the public sample.
4. **Author pilot and portfolio evidence** — Observe independent setters,
   include real package round trips and accessibility checks, and publish a
   reproducible example and redacted trace with intervention and recovery shown.

**Exit gate.** A fresh local install and rollback pass with recorded evidence.
Public claims cite the specific model, worker, platform and human checks that
support them.

## V7 · Selective expansion

1. **New judging profiles** — Expand checker and package coverage, then qualify
   interactive tasks where there is demonstrated demand. Give each supported
   profile its own protocol, fixtures and import checks.
2. **More problem families** — Add a second domain method and independent
   oracle after the scheduling profile is evaluated. Extend the metamorphic
   registry and qualify each new family on held-out examples.
3. **Separate pilots** — Evaluate one formal proof workflow, an optional
   AgentDriver adapter, and shared-author work as separate proposals. Promote
   a pilot after a measurable benefit and its own verification.

**Exit gate.** Each expansion has its own scoped contract, evidence and
supported-platform statement.

See the [original C2 version plan](docs/research/agentic-engine-portfolio/07-ROADMAP-AND-PORTFOLIO.md)
and [engineering backlog](docs/plans/system-depth/04-BACKLOG.md) for design history,
task IDs and the original acceptance criteria.
