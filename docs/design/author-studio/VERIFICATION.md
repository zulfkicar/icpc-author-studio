# Author Studio verification

The new app shell was exercised at the root route against a disposable
loopback instance. The conversation used the scripted demo model and worker.
The package runner, formatters, compiler, verification jobs and ZIP were real.
The package was a small controlled sum problem, linked to a demo conversation
to exercise the author-facing handoff.

| Check | Observed result |
| --- | --- |
| Chat to workspace | Started from an idea, answered a decision, and pasted a C++ solution. Opened the resulting durable artifact in Files, linked a disposable judge package and copied the artifact into `submissions/accepted/sum.cpp`. |
| Editor and diagnostics | Monaco opened the draft. clang-format changed the layout, Save wrote the formatted C++ file, and GCC reported zero diagnostics for it. Ruff formatted a Python draft and reported F401 at line 1, column 8 for an unused import. |
| Manual Run | Compiled and ran the saved C++ solution with input `5 7`. It exited 0 and returned `12`. |
| Build tests and Verify | The answers job wrote two answer files. Measure limits succeeded. The verifier reported the package verified, with nonblocking statement/format notices. |
| Export ZIP | Reviewed the package changes, generated and downloaded a 16-entry archive, and checked the ZIP integrity, embedded snapshot and answers `5` and `9`. |
| Freshness | Saved a new Markdown file after verification. The report showed its outdated status and Export required current verification. The route regression also checks that the earlier snapshot's download is refused. |
| Concurrent editing | Opened the same Markdown file in two browser tabs. The second save identified the first tab's saved version and kept the second tab's unsaved draft. After reviewing the saved copy, applying the draft required a separate Save. |
| Reopen output | Ran the solution with input `8 9`. After closing and reopening Run, the output still showed `17` with its snapshot. |
| Reload and collaboration | Reload preserved the run-to-package link. Opened the real editorial artifact as Markdown and used Discuss in chat to send the report summary back through the conversation. |
| Layout | Checked dark theme, Markdown split, an adjustable divider using the keyboard and the context popover. At 390×844 the document stayed within the viewport. Escape returned focus to the context trigger. |

The production configuration's landing page was opened separately. It reports
that the chat engine currently has no model configured. This was a local
workflow check with an explicit demo conversation, not a live-provider test.
Build tests currently builds answers for existing cases. Runner isolation and
generator orchestration are separate capabilities.

The engine regression run passed 286 tests. A separate HTTP run covering the
engine boundary and the new Author Studio package routes passed all 12 tests.
The classic workbench's static UI contract also passed.

Screenshots: verification and
Monaco with Markdown.

## Live provider check

Author Studio loaded the saved `configured-model` model and sent a
synthetic weighted booking prompt from the browser. The saved endpoint
returned HTTP 429 with `insufficient_credits`. Before the handling fix, the
ledger recorded one rejected decision request and three rejected framing
requests. Token usage was unavailable. The browser showed the old host
fallback question and there were zero artifacts. The live workflow could
therefore only be verified through provider ingress.

The adapter now gives the engine a terminal credit error rather than a
retryable transport error. The offline regression replays the provider error
through the live adapter and chat service and asserts one request, a visible
credit explanation, no pending question and no artifacts. The saved live
preference is enabled, and the restarted local app displays the selected
model. A successful live response and the downstream workspace steps require
working provider access.

## OpenCode provider selection

The composer offers the saved provider, OpenCode Console, and OpenCode Go on
new conversations. The browser check switched through all three choices.
The OpenCode profiles use the documented Chat Completions routes for their
respective plans and send the same session ID for a conversation. The offline
test verified provider binding on reopen and the terminal HTTP 401 path.

Read-only OpenCode Console and Go model catalog requests with the supplied
key returned HTTP 401. A legacy Go usage check returned HTTP 401 as well.
The credential remains in the private local configuration so it can be
replaced through Provider settings. These checks sent no inference requests.

## OpenRouter credential correction

The user identified the supplied key as an OpenRouter key. OpenRouter's
authenticated key endpoint returned HTTP 200 and identified it as an inference
key. The public model catalog listed `deepseek/configured-model`. The
credential was moved into the private OpenRouter slot and removed from the
OpenCode slot because those values matched. The focused regression verified
separate credentials for the saved provider and OpenRouter, the fixed
OpenRouter endpoint, and omission of the secret from the public settings.
The read-only checks made no inference requests.

## Live DeepSeek Flash through OpenRouter

The complete browser journey reached a verified DOMjudge export using
`deepseek/deepseek-v4.1-flash` for chat. The live run report
records the provider defects and repairs, the author contribution, the four
independently checked case answers, the archived file manifest and the
separate limit of automated investigation.

The Canal Lock Windows rerun records the
`invalid_candidate` repair, live model generation of the C++ solution and
seven test inputs, a real before/after execution mismatch, and the verified
DOMjudge ZIP. This journey used the author-facing Studio actions to save,
run, verify and export the generated package.

The automatic oracle and repair rerun
used the real Isolate worker and DeepSeek Flash. A fresh draft passed on its
first try. Replaying the previously saved buggy draft exercised a real `7`
versus `12` mismatch, one live repair, the unchanged suite, and refusal to
export the verified package before author review.

## Shared job and package state

The loopback browser test used a disposable sum package linked to a demo
conversation. Build tests and Verify ran against the real package backend.

| Check | Observed result |
| --- | --- |
| Unverified → verify | Export ZIP explained the blocker and opened the Verify drawer. Build tests wrote two answer files. Verify compiled the statement PDFs and then reported the saved package verified. |
| Review → export | The drawer showed the saved changes and required human review. After review, Generate ZIP produced a 15-file package with a snapshot-qualified download link. |
| Reload | An immediate Export ZIP click after reload restored the conversation's linked package and showed the saved download. |
| Outside edit | After an outside edit, the classic Export button was disabled and Studio directed the author to Verify. After fresh verification, Studio offered **Approve saved snapshot** with no pending change-log entries. |
| Reconnect | A separate loopback fixture returned HTTP 503 for three consecutive job-status reads. Studio offered **Reconnect to job**. Reconnecting recovered the original Build tests result with two answers written. |

The automated workspace lifecycle tests exercise queued cancellation,
worker timeout and a late result. The real package HTTP test checks ZIP
contents, both download URL forms, and the package state read by the agent and
MCP tool.

The broad engine and HTTP run passed 312 tests. The final focused run passed
20 tests, including the additional check that an outside edit during ZIP
generation leaves the earlier archive intact. The classic UI, transition
table and event ledger checks passed. After refreshing both local app
instances, the main app still showed nine saved conversations in their
previous phases and five workspaces. Both download URLs returned the original
approved Canal Lock archive with the same SHA-256.
