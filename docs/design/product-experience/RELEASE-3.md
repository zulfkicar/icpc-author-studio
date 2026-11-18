# Release 3 · Make it easy to judge

18 November 2026

Author Studio connects an investigation in chat to the saved judge package.
Counterexample cards show the claim, case, expected and actual output, source,
and effect. The setter can copy the input or stage it in Run. The supported
weighted-interval profile explains how the endpoint decision affects the
proof and cases. Compare solutions puts the algorithm obligations beside
source paths and actual verification receipts.

| Workflow | Behavior |
| --- | --- |
| Chat to file | Discuss drafts a versioned excerpt without sending it. Private case contents are omitted. Artifact copies show their origin and destination. Saving checks both the current artifact revision and the destination hash. |
| Run | The last source and input selection are saved per problem and package. Save & Run confirms the saved source hash. Case replays display the tagged expectation and distinguish a local process from earlier agent evidence. Diagnostic jumps check the current file hash. |
| Build and verify | Preview sample and secret counts, reference solutions, and output paths. Disagreements leave the corresponding answer untouched. Verify summarizes validator results, expected-answer sources, known-bad solutions, and verdicts. Test filters narrow the report to a group or status. |
| Review and export | A checklist follows the saved package state. Grouped review records viewed files and compares saved text against an approved baseline where available. Out-of-band edits appear in the comparison. Human approval is bound to the saved snapshot. |
| Recover and hand off | Reconnect observes the original job ID. Earlier verification and archive metadata remain visible after edits. The clipboard handoff carries decision and receipt IDs, outstanding work and archive revision. |

The existing [reference research](RESEARCH.md) guided the hierarchy of the
reading surface and the grouped review. The implementation reuses the native
controls, typography, workspace drawer, and existing release workflow. It
adds no frontend dependency.

## Test path

The [rendered Chrome test](../../../qa/engine_contracts/browser_studio_release_three.mjs)
starts an interval problem in a disposable demo conversation and chooses the
endpoint rule. The simulated witness stages an input whose independent
expected answer is 13. A real local Python process returns 12. The browser
opens a diagnostic line, repairs the reference in Monaco, and sees 13 after
Save & Run. Three dropped job-status reads exercise reconnect and confirm a
single run request and the original job ID. Build, limit measurement,
verification and archive generation run
through the real package backend. The test downloads after explicit approval,
edits the statement outside Studio, and observes the historical archive,
blocked download routes, the grouped cumulative diff, and the handoff at
390px. Reload restores the case and source. The browser checks the exact case
and handoff clipboard payloads with an in-memory clipboard.
[Browser result](evidence/release-3-browser.json) and
[390px handoff](evidence/release-3-handoff-390.png).

The [HTTP regressions](../../../qa/engine_contracts/test_studio_release_three.py)
inspect the ZIP and manifest, test stale inputs and source revisions, and
check that both an outdated artifact and a destination collision refuse Save.
The shutdown regression pauses an active graph read and checks that a close
request keeps the SQLite checkpoint and OS lease alive until the graph returns.
The conversation model and conversation worker are simulated in these tests.
Saved source execution, answer generation, verification, review and archive
download use the actual local backend.

The full engine suite passed **321 tests**. Studio and classic Workbench Chrome
journeys, UI contracts, state-machine checks, and draft storage tests passed.
After the local refresh, the main instance still listed nine conversations and
five workspaces. The approved Canal Lock replay downloaded with its original
SHA-256 `2560fc1690d457a7350ea90f0fae509805ddc65e295bb15b0321e61584230f1e`.

Review keeps file identities and up to 48 KiB of text per file, within a
768 KiB text budget per approved baseline. Older approvals without a stored
baseline show the saved files for inspection. Large or binary changes can be
opened in the workspace. Manual Run compares text tokens, while Verify uses
the package's checker. The verification describes the saved package and its
checked cases. The mathematical proof remains available for independent review.
