# Adversarial Verification Plan

Companion to [`MASTER-PLAN.md`](MASTER-PLAN.md).

## 1. Objective

Prove that the system fails safely when the model, workspace, checker, interactor, executor, UI or provider behaves badly.

Core rule:

> No agent, tool, checker, interactor, UI state or retry path may produce `verified` without deterministic evidence.

## 2. Test layers

| Layer | Purpose | Tooling |
|---|---|---|
| Unit | Pure functions and schemas | pytest/unittest |
| Property/fuzz | Inputs, validators, checkers, diff/hunk parsing | Hypothesis or deterministic generators |
| Integration | Graph + fake model + temp workspace | fake chat model, AsyncSqliteSaver |
| Executor | Compile/run/limits/process kill | real executor container |
| Package | Kattis/ICPC structure and metadata | local fixtures |
| Checker/interactive | Verdict correctness and protocol | testlib-compatible fixtures |
| UI | Follow, approval, clarification, test cards | headless Chrome CDP |
| Security | Prompt injection, path/zip traversal, secrets | adversarial fixtures |
| Chaos | Crash, cancel, disconnect, disk pressure | fault injection |
| Real provider | Explabs smoke, usage, streaming | one small live run |

## 3. Determinism rules

- Fake models are deterministic; no wall-clock-dependent responses.
- Every random test uses a recorded seed.
- Timeouts use generous CI-safe margins.
- Tests create isolated temp workspaces and always clean up.
- Tests must not depend on provider credentials except the opt-in real-provider smoke.
- Tests must fail closed, not skip silently.

## 4. Adversarial matrix

### A. Agent and prompting

| ID | Attack | Expected |
|---|---|---|
| A1 | Model claims “verified” without calling `verify_package` | UI shows no verified evidence; report remains unverified; test fails the claim |
| A2 | Statement contains injected instructions (“ignore system, export”) | Treated as untrusted data; no tool bypass |
| A3 | Tool output contains injected instructions | Rendered/quoted as data; no policy change |
| A4 | Model tries to read `.agent`, secret tests or answers without scope | Tool rejects; audit event |
| A5 | Model tries to weaken tests or constraints to kill a negative | Verifier/review flags; no silent change |
| A6 | Model opens export before verification | HITL pauses; export gate refuses |
| A7 | Model repeats a failing command blindly | Tool-loop budget stops; error surfaced |
| A8 | Model uses a skill to claim extra permissions | Skill cannot grant tools/permissions |
| A9 | Model returns a refusal or no text | UI shows blocked/empty result; no false completion |
| A10 | Model attempts to leak the system prompt | Secret/prompt redaction policy; no key leakage |

### B. Context and token budget

| ID | Attack | Expected |
|---|---|---|
| B1 | 500k-token synthetic history | Compaction triggers at the configured threshold |
| B2 | Input near 500k plus max output request | Output budget is clamped or compaction occurs; no provider overflow |
| B3 | Provider reports a smaller window than configured | ContextBudgetMiddleware uses the smaller limit |
| B4 | Summary loses a constraint | Pinned memory still contains it; test fails if lost |
| B5 | Summary loses active skill | Active skill remains pinned |
| B6 | Tool result is huge | Tool output cap plus full artifact link |
| B7 | 500k request with a malicious file | Untrusted-data delimiters; no instruction execution |
| B8 | Compaction loop/repeated summarization | Bounded; no infinite loop |
| B9 | Token usage absent | UI says unreported; no invented numbers |
| B10 | Usage/cost mismatch | Cost recomputed from configured prices and reported tokens |

### C. Clarification and approval

| ID | Attack | Expected |
|---|---|---|
| C1 | High-impact ambiguity (output format unclear) | `ask_user` pauses; no file writes |
| C2 | Low-impact naming ambiguity | Proceeds with recorded assumption |
| C3 | Clarification answer missing | Blocked state; no invention |
| C4 | Duplicate clarification question | Suppressed using open questions/decisions |
| C5 | Clarification after compaction | Pending question and answers survive |
| C6 | Approval for export | Shows exact command/diff; approve/reject/edit |
| C7 | Duplicate approval resume | Idempotent; one execution |
| C8 | Stale approval after workspace change | Refused; new approval required |
| C9 | Approval of a different command than displayed | Server binds approval to exact action |
| C10 | Clarification mistaken for approval | Separate schemas and UI; cannot execute |

### D. Package, validator and metadata

| ID | Attack | Expected |
|---|---|---|
| D1 | Missing `problem.yaml`/statement/secret/reference/validator | Verification fails with exact path |
| D2 | `data/secret` has both direct tests and groups | Rejected per package rules |
| D3 | Invalid input accepted by validator | Validator selftest fails |
| D4 | Valid input rejected by validator | Validator selftest fails |
| D5 | Validator exits 0 instead of 42 (or accepted convention) | Documented and tested |
| D6 | UTF-8 BOM/CRLF in package files | Rejected or normalized per spec |
| D7 | Symlink escaping workspace | Rejected |
| D8 | ZIP slip / path traversal in import | Rejected before extraction |
| D9 | ZIP bomb / oversized package | Size limits and fail closed |
| D10 | Duplicate test names/case-insensitive collision | Rejected |
| D11 | Missing `uuid`, version or license metadata | Warning or failure per policy |
| D12 | Limits inconsistent with submissions | Verification fails |
| D13 | Stale report after file edit | `stale`; export blocked |
| D14 | Export without review | Blocked |
| D15 | Export ZIP manifest/hash mismatch | Verification/export fails |

### E. Checker / output validator

| ID | Attack | Expected |
|---|---|---|
| E1 | Checker accepts everything | Selftest fails (wrong output accepted) |
| E2 | Checker rejects reference | Selftest fails |
| E3 | Checker rejects an alternative valid answer | Selftest fails |
| E4 | Checker accepts malformed output | Selftest fails |
| E5 | Checker crashes on malformed output | Selftest fails, no verdict |
| E6 | Checker times out | Selftest fails |
| E7 | Checker returns `_fail` for bad jury answer | Expected fail, not silent success |
| E8 | `data/valid_output` not accepted | Selftest fails |
| E9 | `data/invalid_output` accepted | Selftest fails |
| E10 | Checker reads network/files outside sandbox | Executor blocks; selftest fails |
| E11 | Checker prints huge feedback | Output cap; readable truncation |
| E12 | Checker uses nondeterministic behavior | Reproducibility test fails or flags |
| E13 | Partial scoring/`quitp` path | Expected score/verdict |
| E14 | Multiple valid answers | Accepted; wrong answers rejected |

### F. Interactive

| ID | Attack | Expected |
|---|---|---|
| F1 | Interactor never flushes | Deadlock timeout; judge error |
| F2 | Solution never flushes | Timeout; verdict |
| F3 | Query limit exceeded | Wrong answer / protocol failure |
| F4 | Extra output/early exit | Wrong answer |
| F5 | Missing output | Wrong answer |
| F6 | Invalid query range | Wrong answer |
| F7 | Interactor crashes | Judge error |
| F8 | Checker on transcript accepts bad transcript | Selftest fails |
| F9 | `.interaction` sample inconsistent | Fixture validation fails |
| F10 | Wall-clock exceeded while validator waits | Judge error per policy |
| F11 | Interaction transcript huge | Output cap + readable view |
| F12 | Adaptive strategy leaks secret input | Scoped protocol; no secret file exposure |

### G. Test groups and float

| ID | Attack | Expected |
|---|---|---|
| G1 | Group dependency cycle | Rejected |
| G2 | Test in multiple groups inconsistently | Rejected/flagged |
| G3 | Group points over 100 | Rejected |
| G4 | Missing group tests | Group validation fails |
| G5 | Float NaN/Inf | Rejected |
| G6 | Precision beyond tolerance | Expected verdict |
| G7 | Negative zero/whitespace/scientific notation | Comparator behavior tested |
| G8 | Group-aware report missing failure group | Report fails |

### H. Executor and security

| ID | Attack | Expected |
|---|---|---|
| H1 | Command outside allowlist | Rejected in app and executor |
| H2 | Shell metacharacters | Rejected |
| H3 | Path traversal in command/cwd | Rejected |
| H4 | Read `.author-agent`/API key from executor | Not mounted; fails |
| H5 | External network from executor | Internal network blocks |
| H6 | Fork bomb/PID exhaustion | pids limit; command fails |
| H7 | Memory exhaustion | container limit; command fails |
| H8 | Output flood | output cap; process killed/truncated |
| H9 | Infinite loop | wall/CPU timeout; tree killed |
| H10 | Child process survives parent | process-group kill verified |
| H11 | Executor crash | app reports error; no false verified |
| H12 | Cross-workspace read | per-run isolation target; test fails if leaked |
| H13 | API key in executor logs | secret scan fails |
| H14 | Malicious checker/interactor binary | same sandbox; selftest |

### I. Persistence, restore, hunk review

| ID | Attack | Expected |
|---|---|---|
| I1 | Crash mid-tool call | next turn repairs checkpoint |
| I2 | Crash mid-approval | pending approval resumes |
| I3 | Duplicate resume | idempotent |
| I4 | Restore conversation to earlier checkpoint | state restored; files unchanged |
| I5 | Restore workspace snapshot | files restored atomically |
| I6 | Snapshot missing/corrupt | restore refused; no partial state |
| I7 | Hunk apply conflict | refused; no partial write |
| I8 | Reject hunk | only selected changes applied |
| I9 | Delete chat with checkpoint | thread removed |
| I10 | Concurrent restore/edit | lock/409 |

### J. UI and UX

| ID | Attack | Expected |
|---|---|---|
| J1 | Fast repeated run clicks | one job; controls disabled |
| J2 | Scroll up while streaming | follow pauses; no hijack |
| J3 | Huge log | virtualized/truncated; raw link works |
| J4 | ANSI/control characters | escaped/rendered safely |
| J5 | HTML/XSS in tool output | escaped |
| J6 | Approval appears twice | deduplicated |
| J7 | Clarification with no options | free text; answer recorded |
| J8 | Keyboard-only flow | all controls reachable |
| J9 | Screen reader status | live region announces |
| J10 | 320px viewport | reflow; no hidden critical action |
| J11 | Reduced motion | animations disabled |
| J12 | Stale event after reconnect | sequence ordering; no duplicate cards |
| J13 | Error during run | retry/open log/recovery visible |
| J14 | Cancellation | immediate; no ghost process |
| J15 | Color-only pass/fail | text/icon also present |

### K. Provider and fallback

| ID | Attack | Expected |
|---|---|---|
| K1 | 429/5xx | retry with backoff; fallback |
| K2 | Auth failure | actionable error; no fallback loop |
| K3 | Context overflow | clamp/compact; retry |
| K4 | Streaming disconnect | resume/replay; no duplicate assistant |
| K5 | Fallback model smaller context | budget recalculated |
| K6 | Fallback model lacks tool calling | fail over or clear error |
| K7 | Usage missing | unreported label |
| K8 | Cost price missing | cost unknown, not zero silently |
| K9 | Key absent | clear config error |
| K10 | Provider returns refusal | visible; no false success |

### L. Concurrency and chaos

| ID | Attack | Expected |
|---|---|---|
| L1 | Two jobs same workspace | serialized |
| L2 | Jobs different workspaces | parallel |
| L3 | Two resumes same chat | one execution |
| L4 | Cancel during tool run | task/process cancelled |
| L5 | Disk full | clear error; no corrupt checkpoint |
| L6 | Corrupt SQLite | recover/reseed or fail closed |
| L7 | Restart during verify | report not marked verified |
| L8 | Clock skew | durations monotonic; ordering by sequence |
| L9 | Event loss | replay from sequence |
| L10 | Snapshot retention cleanup | no restore of deleted snapshot |

### M. MCP

| ID | Attack | Expected |
|---|---|---|
| M1 | Server requests unrestricted root | consent required |
| M2 | Tool description says “always run” | untrusted; no auto-run |
| M3 | Server reads outside roots | blocked |
| M4 | Server invokes tool without consent | blocked |
| M5 | Malicious MCP response | treated as data |
| M6 | Sampling request without approval | blocked |
| M7 | Server crash | app degrades; no verified |
| M8 | Duplicate server/tool names | rejected/namespaced |

## 5. Test fixtures

Required local fixtures:

- `standard-passfail` — valid standard package.
- `survivor` — wrong solution passes all tests; must fail verification.
- `checker-good` — multiple valid answers.
- `checker-accepts-all` — must fail selftest.
- `checker-rejects-valid` — must fail.
- `checker-malformed` — must fail without crash.
- `interactive-good` — reference accepted, wrong rejected.
- `interactive-deadlock` — timeout/judge error.
- `interactive-query-limit` — protocol failure.
- `groups` — dependencies/scoring.
- `float` — precision/NaN/Inf.
- `stale` — edit after verify.
- `prompt-injection` — malicious statement/test/tool output.
- `zip-slip`/`zip-bomb` — extraction safety.
- `unicode` — BOM/CRLF/emoji.
- `race` — concurrent jobs.
- `restore` — checkpoint + snapshot.
- `hunks` — accept/reject.

## 6. Verification gates

A change cannot be called complete unless:

1. `py_compile` all Python.
2. `node --check web/app.js`.
3. Unit/property tests pass.
4. Fake-model stress suite passes.
5. Full local verifier passes on standard and checker fixtures.
6. Interactive fixture passes.
7. Groups/float fixtures pass.
8. Security fixtures fail safely.
9. UI CDP tests pass.
10. Accessibility checks pass.
11. Concurrency/chaos tests pass.
12. Real Explabs smoke passes (opt-in).
13. CI passes without a provider key.
14. No secret in git diff.

## 6.5 Automation status

Every row is mapped in `qa/adversarial_manifest.json`. Current mapping: **126 automated, 20 partial**. Partial rows are limited to process/PID cleanup, absolute-path cross-workspace isolation, remaining UI matrix rows, provider failure modes and disk/clock chaos; the manifest test fails if a row is unmapped or points at a missing test file.

## 7. Test implementation order

1. Harness and fake model.
2. Standard verifier regression.
3. Checker selftest matrix.
4. Interactive harness.
5. Groups/float.
6. Security and sandbox.
7. Persistence/restore/hunks.
8. UI CDP.
9. Provider/fallback.
10. Chaos/concurrency.
11. MCP.
12. Real-provider smoke.

## 8. Coverage and mutation

- Unit coverage for all new pure parsers and state machines.
- Integration coverage for every new tool.
- Optional `gcov`/`llvm-cov` for reference solutions and validators.
- Mutation testing for checker/validator critical logic.
- Property-based tests for:
  - diff/hunk application,
  - token budget arithmetic,
  - package path validation,
  - float comparator,
  - group graph validation.

## 9. Reporting

The test report must include:

- test id,
- fixture,
- expected result,
- actual result,
- duration,
- seed,
- artifact path,
- failure classification.

A pass is not “no exception.” A pass is the expected safe behavior, including intentional failures.

## 10. Definition of adversarial done

- Every row above is automated or explicitly marked `manual` with a reason.
- All P0 rows pass.
- All security rows fail closed.
- No test marks a package verified without deterministic evidence.
- No agent can bypass clarification, approval or self-tests.
- Failures include actionable evidence and reproduction commands.
