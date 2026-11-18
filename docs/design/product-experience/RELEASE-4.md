# Release 4 · Qualify and showcase

18 November 2026

Open **Canal Bookings sample** from Commands or **Try Canal Bookings sample**
on the empty conversation. It travels through the same chat, file editor,
runner, verification, review, and export routes as the rest of Studio. It uses
a dedicated conversation, scripted model, simulated conversation worker, and
local workspace. The setter chooses the endpoint rule, runs the weighted
counterexample, loads the fixed reference as a draft, and approves export.
**Start a fresh sample** creates a separate copy.

The context bar opens on demand. It shows the latest completed attempt for
each role, its model and time, and a category estimate based on serialized
text. If the provider reports input tokens, the total comes from the provider
and category attribution remains estimated. Capacity comes from an explicit
model entry in the optional `AUTHOR_AGENT_CONTEXT_WINDOWS` JSON map, or the
labelled reference scale in the scripted sample. Older conversations show an
empty state until there is a receipt. The payload contains counts, role,
model, time, and source labels. It does not carry prompt text or test bodies.

Long chats render the newest 100 messages and can retrieve earlier pages.
Request assembly also uses recent turns. File search builds its index once on
open, displays up to 50 matches, and still searches the full list. Interrupted
package jobs recover by request ID, checking the same server receipt on reload.
A missing receipt after a server restart or eviction is shown explicitly.

## Verified journeys

| Check | Observed result |
| --- | --- |
| Chat-led | Scripted choice and labelled witness. The real local reference returned 12, then returned the independent expectation 13 after Save & Run. The sample built answers, measured limits, verified, and generated its ZIP after approval. |
| Existing workspace | A manual setter ran and verified a separate package at 390px. Switching into the sample and back restored the unsent draft. |
| Offline, reload, stop and conflict | Chrome dropped the accepted Run response and reloaded. Studio recovered the same job ID. A queued verification stopped without changing the package. An editor conflict kept the local draft and the newer saved file from the other writer. |
| Accessibility | Chrome 157 ran native keyboard input through Commands, Verify, Open file and Run. Touch opened, selected and dismissed a context category. The accessibility tree exposed actionable buttons and status roles. Reflow passed at 320, 390, 640, 768, 1280 and 1440 CSS pixels, including forced colors, reduced motion, light and dark, and a 640 CSS pixel viewport at 2× pixel density. |
| DOMjudge import | DOMjudge **9.0.1** imported the browser-generated ZIP into a disposable contest. Readback showed both tests, the statement PDF and the 1-second limit. DOMjudge reported that the disposable admin needs a team to add jury submissions. |

The Chrome accessibility check used emulation and the native accessibility
tree. Screen-reader speech and hardware touch still need direct checks.
[Rendered journey](evidence/release-4/journey.json),
[accessibility record](evidence/release-4/accessibility.json), and
[DOMjudge readback](evidence/release-4/domjudge.json).

## Local performance

Thirty samples per local handler in Chrome 157. Fixtures included 100 and
500 messages, 50 and 300 added case files, and 120 and 1,200 verification rows.
Timing excludes provider requests. The large chat now reaches the latest turn;
the earlier rendering window stopped at turn 200. Composer focus, draft and
selection survived polling. These are local scripted measurements.

| Large fixture, ms | Release 3 p50 / p95 | Release 4 p50 / p95 |
| --- | ---: | ---: |
| File picker open handler | 9.7 / 18.9 | 7.0 / 8.4 |
| File filter handler | 1.2 / 2.6 | 0.3 / 0.5 |
| Composer input to next frame | 16.6 / 23.4 | 16.6 / 18.1 |
| Report group filter | 1.1 / 2.1 | 1.4 / 1.8 |

The small file picker's open p95 was 7.9 ms in the baseline, 15.8 ms in the
first Release 4 sample, and 9.1 ms in the rerun. The rerun also restored the
earlier chat page and the reading position after reload.
[Baseline timing](evidence/release-4/performance-baseline.json),
[release timing](evidence/release-4/performance.json), and
[history rerun](evidence/release-4/performance-history.json).

## Showcase and follow-up

[Local sample recording](evidence/release-4/canal-bookings-walkthrough.webp)
covers the author choice, witness, fixed execution and approved release. The
sample qualifies the product flow with scripted chat and a simulated conversation
worker. The local runner, verifier, archive generation and DOMjudge import ran
against the actual tools. Release 4 did not run a live provider or isolated
conversation worker. The recording is ready for review locally.

The [setter session guide](SETTER-SESSIONS.md) defines the tasks, consent and
measurements for three to five formative sessions. Participant sessions and
external publication await separate coordination.

The local refresh preserved the main instance's nine conversations and five
workspaces. The previously approved Canal Lock ZIP matched its original SHA-256.
The full engine regression suite passed **325 tests**. The classic Workbench
Chrome journey, UI contracts, state-machine checks, and draft storage tests
also passed.
