# Repository audit

Date: 2026-11-10. Baseline HEAD and hashes are in
[source-inventory.json](evidence/source-inventory.json). The earlier scope-document
changes were already present and were preserved. Production source was not edited.

## Method and coverage

Inventory: 316 tracked files, comprising 30 runtime/config entries, 39 documentation
entries, 11 operations files, 23 images, 3 evaluation files, 7 prompts, 54 QA entries,
13 agent skills, 8 templates and 121 vendor entries. The taxonomy treats
`templates/testlib.h` as vendor code. The untracked domain scope and this new plan
are additions beyond that baseline.

Review levels:

- **R:** selected owning logic inspected in source. This does not mean every
  line or possible execution path was verified.
- **P:** current behavior reproduced by an isolated synthetic or source probe.
- **T:** selected existing check rerun during this audit.
- **H:** existing documentation, screenshots or recorded results inspected as
  historical evidence, without replaying the corresponding live workflow.
- **I:** inventoried for ownership, hashes and future checks only.

Every tracked path is listed in the inventory. Private `.author-agent/` state,
real workspaces, credentials, caches and unrelated repositories were excluded.
Vendor internals were inventoried, not independently security-audited. A complete
dynamic security audit, formal code verification, all browser journeys and all
container/backend tests were not performed. This plan explicitly schedules them.

| Component / owning files | Level | Audit focus and next work |
|---|---|---|
| `agent.py` | R/P | Dispatch, command/read policy, mutation evidence, cancellation |
| `graph_agent.py` | R | Tool registry, reviewers, modes, history, approvals, streaming and usage |
| `agent_middleware.py` | R/T | Pinned context, trimming and error handling |
| `agent_state.py`, `schemas.py` | R/P/T | Reducers, state bounds, event contracts, missing evidence model |
| `prompt_loader.py`, `skill_registry.py` | R/P/T | Partial prompt loading, resource retrieval, active-skill invariant |
| All seven `prompts/*.md` and mode files | R | Completion policy, supported capabilities, specialist depth |
| All thirteen `skills/*/SKILL.md` | R/T | Actual procedures, artifacts, examples and evaluation gaps |
| `verify.py` | R/P | Standard/interactive paths, limits, statement and export lifecycle |
| `verification_modes.py` | R | Checker fixture binding, interactor coverage and failure semantics |
| `package_model.py`, `icpc_spec.py`, `scoring.py` | R | Discovery, dialects, parse errors, group/float validation |
| `workspace.py` | R/P | Canonical paths, revisions, changes, snapshots, restore and atomicity |
| `server.py` | R | HTTP policy, settings, route locks, jobs and MCP subprocess lifecycle |
| `config.py` | R | Settings validation, persistence, redaction and config drift |
| `winutil.py`, `sandbox/sitecustomize.py` | R/P; I for shim internals | Native fallback, remote protocol, cancellation, memory/output bounds |
| `isolate_worker.py`, `executor_server.py` | R/P | Parsed controls, staging/sync, privilege and output semantics |
| `isolate_client.py`, `judge0_adapter.py` | R/P | Backend contracts, status, settings and sensitive inputs |
| `mcp_server.py`, `mcp_consent.py` | R/P | Canonical read policy, default grants, root fallback, error recovery |
| `web/app.js` | R/P/T | Renderer collision, judging, async state, settings, evidence and size |
| `web/machines.js`, `dialogs.js`, `theme.js` | R/T | State ownership, restore escape hatch, dialog lifecycle and persistence |
| `web/index.html`, `style.css`, `monaco-worker.js` | R/I/H | Integration/layout assets, current screenshots, future rendered gates |
| `web/vendor/**`, `templates/testlib.h` | I, vendor README reviewed | Provenance, versions, licenses, hashes, upstream verification needed |
| Other `templates/**` | R/I | Scaffold and format contract, adversarial template tests needed |
| Both Dockerfiles and three compose files | R | Boundary/configuration, toolchain drift, images and local exposure |
| Six `scripts/*.ps1` | R for selected launch/stop/demo logic, I for remaining branches | Distro/port/PID handling, idempotency and fresh-machine validation |
| `.github/workflows/checks.yml` | R | CI grouping, skip visibility, backend prerequisites and pinning |
| QA Python/JS/PowerShell + fixtures | R for selected test logic, T for eight checks, I for remaining cases | Assertions vs behavioral coverage, hermetic/live split |
| `eval/run_eval.py`, both fixtures | R | Self-generated evaluation, timeout/cost controls and held-out gap |
| README, architecture, status, readiness and earlier plans | R/H | Contradictions, claim scope and canonical forward-plan navigation |
| Remaining docs/evidence/screenshots | I/H | Preserve history, bind future evidence to source/environment hashes |
| Ignore files, requirements, `.env.example`, project-local UI skill | R/I | Build context, secret exclusions, dependency and guidance provenance |

## Priorities

P0: repair before relying on the affected execution/integrity guarantee or building
new correctness automation on it. P1: core expanded-scope requirement or substantial
correctness/reliability issue. P2: operational quality, maintainability or breadth.
P3: later enhancement. These are local project priorities, not security scores.

## Findings

| ID | Priority / evidence | Owning source and observation | Required action |
|---|---|---|---|
| A01 | P0 / P | `winutil._require_local_or_executor` returns false without executor environment variables. Native `python server.py` can execute generated code locally. Compose sets the requirement, the generic native path does not. | Fail closed in supported authoring launches. Keep any developer override explicit and separate from normal operation. |
| A02 | P0 / P | `agent._dispatch(read_file)` checks before canonical normalization. `data/./secret/...` returns synthetic protected content. MCP `_safe_path` similarly accepts `./data/secret/...`. | One canonical file-identity policy shared by tools, MCP, context, backend routes and reviewers. Test Windows case aliases and links. |
| A03 | P0 / R/P | `verify.verify` returns early for interactive packages. `_verify_interactive` omits normal snapshot/report persistence, limits gate and statement build. `interactive_selftest` selects one test. The mocked dispatch probe returns `verified` with no snapshot or saved report. | A common verification lifecycle, full applicable test matrix and complete persisted report for every mode. |
| A04 | P0 / R | `verify.export_package` checks a hash then reads mutable files. Worker executions also use mutable workspace trees. Concurrent edits can race checks and produce mixed revisions. | Immutable staged inputs, revision-bound approvals and export from the exact checked revision. Validate artifact hashes before publishing. |
| A05 | P0 / R/P | `verify._run` uses a timeout but forwards no package memory limit. Isolate `/run` defaults to 1024 MiB. `_limits` ignores requested process/stack/open-file fields and `_isolate_args` hardcodes some controls. | One versioned resource contract, separate compile/run limits, capability negotiation and observed enforcement evidence. |
| A06 | P0 / R | `isolate_worker._sync_workspace` copies arbitrary sandbox outputs into the source workspace and replaces directories. The bwrap worker also stages/syncs files. This bypasses `workspace.write_text` review tracking and can overwrite newer files. | Publish only declared artifacts through a revision-checked transaction. Candidate execution inputs read-only, temporary writes disposable. |
| A07 | P1 / P | `workspace.tree` excludes `.out`; `snapshot_hash` uses that tree. Changing `data/valid_output/*.out`, which checker self-tests consume, leaves the snapshot unchanged. Export separately skips `.out`. | Artifact-aware inclusion rules and separate source/evidence/export manifests. Include every verification dependency. |
| A08 | P1 / P | `workspace.write_text` does not invalidate `limitsMeasured`. Reference edits leave old measurements usable. | Measurement dependencies on references, tests, compiler, worker configuration and metadata. |
| A09 | P1 / R | `server.do_POST` file save, review and revert routes do not all acquire `workspace_lock`; verify/export jobs do. Quick runs are synchronous and not serialized consistently. | Route all mutations and publication through one revision-aware workspace service. |
| A10 | P1 / R | `workspace._record` truncates changes to the most recent 400 records, regardless of review state. Rename/folder actions have different tracking behavior. | Durable journal, complete mutation coverage, explicit retention and preserved pending reviews. |
| A11 | P1 / R | Package text writes happen before change recording, `_read_json` silently returns defaults on corrupt state, `_write_json` falls back to a direct write, and config/consent use direct writes. | Crash-consistent transactions, surfaced corruption, backups and recovery with no silent loss. |
| A12 | P1 / P | `mcp_consent.state` recovers malformed consent as enabled with all tools. This is also inconsistent with its explicit-consent module description. | Preserve the intended fresh-workspace convenience policy, but never expand grants on corrupt/missing prior state. Distinguish new from damaged state. |
| A13 | P1 / R | `mcp_server._roots` falls back to the workspace root when all configured roots fail resolution; `_clean_roots` also substitutes `.` for an empty result. `server.mcp_probe` blocks on stdout without a request deadline. | Invalid restrictions deny rather than broaden. Add protocol/session validation, request deadlines and process-tree cleanup. |
| A14 | P1 / R | Review mode changes instructions, while `_graph` registers the same author tools. Approvals cover export and optionally file writes/deletes, but executable side effects can bypass file-write policy. | Enforce operation capabilities in code for each mode/role. Approvals describe and bind all actual effects. |
| A15 | P1 / R | State/schema/tool registry has no durable specification, proof obligations, argument review or implementation correspondence. | Add versioned correctness artifacts with explicit uncertainty and staleness. |
| A16 | P1 / R | All 13 agent skills are short instructions without substantive examples, diagnostic branching or behavioral acceptance tests. The loader reads only a single body. | Rebuild skills to the contract in the catalog and add bounded resource retrieval. |
| A17 | P1 / R | Workflow says stop at green verification. `prompt_loader._read` hides missing required files and accepts a partially composed system prompt. | Phase-aware completion policy and validated prompt bundles with explicit failure behavior. |
| A18 | P1 / R | Three specialist reviewers share a small read-only tool set, short role prompts and return prose findings. Their wrapper has no explicit per-role call/time budget, evidence manifest or finding-resolution contract. | Focused review briefs, bounded context/tools/usage and structured finding lifecycle. |
| A19 | P1 / R | Answer generation and verification can agree around the same mistaken reference/checker assumptions. Multiple accepted solutions need not be independently derived. | Independent simple oracles, assumption tracking, refutation search and counterexample evidence. |
| A20 | P1 / R | Eval has two visible authoring fixtures, judges self-authored material using the product verifier, and checks its timeout between large turns. | Separate end-to-end convenience eval from held-out correctness and defect-detection eval. Enforce global deadlines and usage budgets. |
| A21 | P1 / R | CI mixes static, mocked and backend-dependent tests. Some live tests skip when unconfigured, and some verifier tests can use native fallback. | Hermetic fast jobs and explicitly provisioned integration jobs. Report pass/fail/skip and required capabilities separately. |
| A22 | P2 / R/T | `test_verification_timing.py` validates committed historical JSON. It does not measure the current code or bind timings to source/image hashes. | Keep it as an artifact-integrity check. Add fresh performance runs and fingerprinted baselines. |
| A23 | P1 / R/P | `web/app.js` declares `renderToolResult` at lines 982 and 1137. The latter overrides specialized evidence rendering. Syntax and static UI checks pass. | One renderer registry and executed tests that assert visible specialized results. |
| A24 | P2 / R | `web/app.js` is 4,846 lines with shared mutable state, transport, rendering and workflow together. Machines mirror state and expose `.set`, which bypasses event transitions. | Extract by responsibility, clarify authoritative state and test stale responses/reconnects. Avoid a rewrite solely to adopt a framework. |
| A25 | P1 / R | `runSamples` compares normalized output in JavaScript, independently of custom checker/float/interactive semantics. Dirty-save handling starts before its main try/finally. | Server-backed sample judging using the selected package contract, with reliable error/cancel cleanup. |
| A26 | P2 / P | `judge0_adapter.quick_run` labels queued/running status IDs as `ok`. A mocked queued response reproduces success. | Distinguish pending from terminal completion and poll with a deadline. |
| A27 | P2 / R | UI sends `isolateUrl` and `judge0Token`, while the HTTP settings allowlist does not forward both. The config save allowlist also omits Isolate fields. Some clients use environment rather than saved configuration. | One typed configuration schema and consistent route/client propagation, including clear-token and range semantics. |
| A28 | P2 / R | Settings validation clamps only some values. Provider keys are local JSON, and redaction is not an enforced common boundary for all errors/events. | Validate finite ranges and endpoint policies, atomic secret persistence, consistent redaction and permission checks. Keep local scope explicit. |
| A29 | P1 / R, live validation pending | Isolate compose service is privileged, publishes a loopback port, uses optional tokens and joins the default network as well as the internal network. Child isolation and service privilege are different boundaries. | Minimize exposure, separate service and child network policies, enforce service authentication where appropriate and validate least privilege. No escape was demonstrated. |
| A30 | P2 / R/I | Direct Python dependencies are pinned without a full transitive hash lock. Container tags lack digests. Vendor README covers only part of vendored assets; project licensing is not declared by a root license file. | Reproducible dependency inventory, license/notice review, controlled updates and a user-chosen project license before distribution. |
| A31 | P1 / R | Jobs/events live in memory. Events are capped at 600 without a durable replay source, job retention is count-based and watchdog cancellation does not itself terminate every worker request. | Persist job state/events, detect gaps, propagate cancellation to workers and reconcile after restart. |
| A32 | P1 / R | `restore_history` restores JSON mirrors then deletes the checkpoint thread. It does not preserve the full selected typed state as a new branch. `snapshot_turn` prunes beyond 20 archives automatically. | Explicit conversation/file restore semantics, preserved branches and policy-driven snapshot retention. |
| A33 | P2 / R | Package parsing returns empty data on YAML errors, program discovery picks a candidate, float comparison supports a limited absolute tolerance, and group scoring needs strict malformed/nonfinite metadata handling. | Typed parse diagnostics, explicit program selection and dialect-specific judging/scoring contracts. |
| A34 | P1 / R + official reference | The model combines legacy/draft conventions and local extensions. Discovery/export roots are not identical; `GROUPS_FILES` includes names outside the export allowlist. `testlib.h` is supplied from global templates rather than a recorded package dependency. | Explicit format/export profiles and dependency manifests. Cross-check with reference tools and the selected DOMjudge target. |
| A35 | P2 / R/H | Master-plan baseline gaps and non-goals contradict implemented subgraphs, groups and local DOMjudge work. Readiness and other prose make broader claims than some current paths establish. | One current capability matrix and evidence index. Label historical claims and point to this audit. |
| A36 | P1 / R, integration test pending | Model events from all nested calls are emitted without explicit role/run routing. Usage is accumulated and priced at the primary configured rates, without a persisted per-model billing ledger. | Attribute events and reported usage to actual model/role/run, separate estimates and unknowns, and enforce task-wide budgets. |
| A37 | P2 / R | Launcher `$Distro` is used in some WSL calls but omitted in others. Stop logic trusts a saved PID, `$Port` health checks do not configure the compose mapping, and compose commands rely on shell quoting. | Consistent distro/project/port selection, PID identity verification, robust quoting and clean-machine install/stop/restore rehearsals. |

## Probe interpretation

[audit_probes.py](evidence/audit_probes.py) uses only synthetic temporary files,
real pure policy functions and mocked prerequisites. It spends no provider
tokens and does not execute submissions. Its interactive probe demonstrates
control-flow omissions, not a live successfully judged interactive package.
The skill-load probe composes two legal loads from the same prior state through
the real reducer: three active skills result despite a limit of two. Address
this in skill-state validation under A16.

Passing checks, captured in [selected-checks.json](evidence/selected-checks.json):
JavaScript syntax, state machines, skill loading, context budget, static UI
contracts, event ledger, adversarial-manifest validation and historical timing
artifact validation. Syntax parsing also passed for 58 first-party Python files.

## What remains uncertain

No current container image digest, kernel hardening result, active backend
configuration, live judging behavior, dependency vulnerability status, actual
provider billing or current browser accessibility result was established here.
Historical evidence remains useful but must be rerun against the repaired source
and recorded environment before making new readiness claims.
