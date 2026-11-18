# Delivery plan and polish backlog

18 November 2026

Each release improves a complete author journey. The rows are implementation
tasks or grouped micro-interactions with observable completion conditions.
**P0** protects work, authority or version identity. **P1** removes common
friction. **P2** improves depth once the critical paths work. Release
numbers express dependency order. Effort depends on what the initial
contracts and usability sessions uncover.

## Release 1 · Keep my work

Start with the reproduced failures in [the audit](EXPERIENCE-MAP.md).
The first change should be a small end-to-end slice through a named problem
with a draft, a decision and a linked package. Use existing browser and
backend routes through that slice before expanding view state.

| ID | Priority | Change | Done when |
| --- | --- | --- | --- |
| 01 | P0 | Separate the message text, decision reply and composer draft. Do the same for Retry and example insertion. | With typed text in the composer, using a choice or Retry keeps the text and caret. Inserting an example into an occupied composer appends or explicitly replaces it. |
| 02 | P0 | Persist unsent composer drafts per problem, including the unstarted problem. | Normal reload, navigation to settings/back, and switching restore the right draft. A newly started problem gets a separate draft. Restore never submits. |
| 03 | P0 | Persist unsaved file drafts with package, path, source, base hash, and edit generation. Start with local browser storage suitable for text buffers, such as IndexedDB. | Refresh or close/reopen restores exact bytes as unsaved. Two problems with the same path stay separate. A tab shows a durable recovery failure when storage is unavailable. |
| 04 | P0 | Compare recovered drafts to the current saved base before Save. | An outside edit or second tab produces an explicit base comparison. Copy, keep draft, load saved and review-then-save preserve the user's text until their choice takes effect. |
| 05 | P0 | Retain submitted text and client request ID until acceptance can be reconciled. Keep a visible per-problem queue. | A response lost after commit resumes at the existing receipt. An unaccepted draft can retry explicitly with the same identity. Reload never replays ambiguous writes or sends. |
| 06 | P0 | Bind status and receipts to the actual sent input or decision. | The resolved endpoint shows “Choice saved” and associated effect. Superseded or refused text is attached to the turn involved. A later turn's completion leaves earlier receipts correct. |
| 07 | P1 | One discoverable title action in the header, with a matching command and accessible label. | Title text or recognizable edit action works by pointer and keyboard. New names are optional before first send. Enter saves valid text, Escape cancels, and the full current title is available on narrow screens. |
| 08 | P0 | Preview and explain a linked rename. | Before saving a delivered package title, show where it appears and that fresh verification and approval will be needed. After saving, the receipt names the new title and the next step. A no-op rename produces zero release changes. |
| 09 | P0 | Split package linking from renaming an existing package. | Show its current title and the proposed title. Default to linking without rewriting existing bytes unless the setter explicitly chooses to match the names. A new package uses the current problem title. |
| 10 | P0 | Preserve ownership, stable IDs and existing conflict semantics. | Two similarly named problems keep separate IDs and slugs. A stale linking preview or concurrent rename opens a conflict with both titles. One earlier receipt remains inspectable. |
| 11 | P1 | Validate title edge cases and report partial adaptation of imported statements. | Blank, long, duplicate, Unicode and TeX-special names have useful feedback. The real ZIP filename preview matches response headers. A PDF-only or title-less TeX import reports what needs manual review. |
| 12 | P1 | Keep current file and pending action through package setup. | Copy → Link → Copy destination returns to the same artifact. Cancel returns to the artifact with its source and selection. A superseded artifact is held for historical inspection or explicit copying. |
| 13 | P1 | Preserve handoff between manual package entry and chat. | Starting a conversation while working in a package offers to link that exact package. Declining leaves the manual package in Recent. No title or files change implicitly. |
| 14 | P1 | Restore the last useful location. | Refresh returns to problem, pane, chosen file, tab set, cursor/scroll and most recent relevant output. Stale targets name their source and provide a fallback. Layout preference stays independent of authority. |
| 15 | P1 | Add small feedback to naming, recovery and clipboard actions. | Show Saved, Draft recovered, Copied, Unable to persist, and appropriate next steps. A screen reader hears each meaningful update once. Focus returns predictably. |

**Build boundary.** Frontend owns presentation, draft storage and selections.
The host binds title, link and revision effects. Retain legacy reads and
write contracts during rollout. A new preview/bind path can carry expected
title, link, package snapshot, and the explicit synchronization choice.
Reevaluate under the workspace lock at commit. Persist recovery state
independently of tools, exports and the LangGraph ledger.

### Title and link behavior to implement

| Starting point | Author action | Outcome |
| --- | --- | --- |
| Unstarted idea | Set title or start writing | Title stays a local draft until first send. One create binds it to the conversation. |
| Conversation with no package | Create package | Use the saved problem title. If none exists, ask for a name once and use the chosen result. |
| Conversation linking an existing package | Keep existing title or explicitly match titles | The preview identifies the target. Keeping the existing title leaves a distinct package label visible. Matching titles lists specific edits, conflicts and verification impact. |
| Linked, title-managed package | Rename problem | Show the new displayed name, affected surfaces, expected ZIP name and any release check to repeat. Keep the stable link. |
| Imported package whose title is separate | Rename conversation | Keep the package title as chosen. If the author wants one title, offer the same explicit matching operation from package settings. |
| Pending edit or another tab modifies the target | Confirm from an earlier view | Show the current title or file and refresh the preview. Keep the author's typed title. |

Use the lowest-friction interaction for the first two rows and show the scope
within the edit form for later rows. Confirm the exact saved effect through
the host's receipt so the author can trust the heading and release drawer.

## Release 2 · Make it easy to work

Build on draft recovery and reliable actions. Design around the time an author
spends reading a proof, adjusting code and running a case. Prototype the
problem header, a narrow workspace and a 100-message conversation in the
real app with representative text before applying the whole spacing system.

| ID | Priority | Change | Done when |
| --- | --- | --- | --- |
| 16 | P1 | Replace the long native-only problem listing with a searchable recent picker when the list requires it. | Names lead, statuses and last activity are separate, and two 70-character names with identical prefixes can be distinguished with pointer, keyboard and speech output. |
| 17 | P1 | Add local navigation commands for open problem, open file, rename, run, verify and bring a result into chat. | A visible command entry and documented shortcuts use the same actions. Monaco, browser and OS key conflicts fall back to reachable controls. |
| 18 | P1 | Make Chat, Together and Editor honest view names at each width. | A narrow view shows Chat or Workspace clearly. Wide collapse/resize/reset preserve current scroll and draft. At 320px, a drawer exposes files without a permanent 105px tree. |
| 19 | P1 | Give run/test/review controls predictable homes and reduce header crowding. | Full title and one status remain discoverable. At phone width, theme/text preferences and secondary actions have a labelled home. All manual actions stay reachable without chat. |
| 20 | P1 | Make pinning, opening, closing and reopening files predictable. | Dirty files retain stable models and have visible actions when closed. Preview tabs become pinned on edit. Nearest surviving tab gets focus. Duplicate basenames show their differing folders. |
| 21 | P1 | Scope tree navigation to the task. | Collapsible Statement, Proof, Solutions, Validators and Cases groups retain selection. Search can show real paths. Sample/secret groups and conversation/package origin are distinguishable. |
| 22 | P1 | Provide locally shareable navigation targets within Studio. | Open same problem/file or historical revision through an opaque local reference, with correct breadcrumbs and a Back path. A missing or stale target falls back to its problem. Private contents stay out of URLs. |
| 23 | P1 | Improve save feedback and toolkit errors. | Show saved time or clear recovery where needed. Format is undoable. Missing tools say which file types they affect and how to proceed. An edit after a check clears or marks prior diagnostics stale. |
| 24 | P2 | Add useful file preview modes. | Markdown Edit/Preview/Split obey size and theme. Generated PDF is previewable from a real authorized file source and can open separately. Missing/stale PDF explains which step produces it. |
| 25 | P1 | Make code, statements, and evidence readable with one coherent scale. | Long words, TeX, tables, paths, code lines and split views work at target sizes and 200% zoom. Only two-dimensional content needs its own scroll. 18px reading and 15px code defaults are tested with realistic content. |
| 26 | P1 | Preserve transcript position while results arrive. | Reading old messages, selecting text, typing, and operating an inline choice do not jump focus. A New activity/Jump to latest affordance appears when appropriate. |
| 27 | P1 | Compress routine transcript updates into a useful artifact summary. | One result lists changed material and why. History exposes all individual records. Proof draft, evidence and missing proof remain clearly labelled. |
| 28 | P1 | Make provider states legible at the point of use. | First screen shows supported scope and configured/demo/unconfigured choices. A settings link returns to the draft. A provider bound to an existing run has an explanation and safe path for a new run if needed. |
| 29 | P1 | Make action verbs and tooltips reflect actual behavior. | “Build expected answers” says it uses existing inputs. “Run saved source” explains saved bytes. A Proof action with no artifact explains how to request one. |
| 30 | P1 | Standardize interaction feedback and focus behavior. | Visible, labelled focus for popup, dialog, tab, splitter and drawer. Descriptive close controls. Escape closes the active surface and restores focus. IME composition can enter multiline text without accidental send or rename. |
| 31 | P2 | Keep theme, size and density independent where they help. | Theme follows light/dark or system choice. Reading preference reaches preview and transcript, and code size can be restored independently. New focused surfaces visibly adopt the same tokens. |
| 32 | P1 | Keep the original error/recovery experience on the current task. | Inline error includes action, target and retry conditions. Standard transient feedback avoids obscuring the main canvas or jumping to an unrelated pane. |

**Build boundary.** Extract reusable dialog, status, and source-target rendering
where real duplication exists. Keep the native controls and installed editor
as foundations. Routes and state ownership are documented in the
[state-machine inventory](../../architecture/state-machines.md).
Maintain the classic workbench path while Studio's presentation evolves.

## Release 3 · Make it easy to judge

Connect the mathematical conversation to the saved files and the package
workflow. Exercise an actual oracle mismatch and a stale approval scenario.
Start with the existing evidence records and shared export state.

| ID | Priority | Change | Done when |
| --- | --- | --- | --- |
| 33 | P1 | Put a counterexample into a compact evidence result. | Show the claim, legal input, expected, actual and effect. Copy input or Run this case puts that case into the right workspace or asks for a target. Raw diagnostics remain available. |
| 34 | P1 | Explain what raising a correction will affect. | A proposed rule or constraint change explains which spec, proof, tests and drafts need rechecking. The applied decision becomes visible with its provenance. |
| 35 | P1 | Let the setter compare candidate solutions and proof obligations. | Compare approach, complexity, invariants and unproven assumptions. A result can cite the exact supporting run or source, and a pending proof obligation has a next action. |
| 36 | P0 | Respect approval and recovery boundaries in chat-to-file actions. | Discuss file inserts a version-bound preview or excerpt. Apply uses host-resolved scope and current authority. Retrying a rejected or stale proposal cannot recreate authorization. |
| 37 | P1 | Change “Copy to package” into a continuous inspectable flow. | Show origin, artifact revision, destination and selected package. Explain stale or colliding source. Preserve a preview and base; Save remains the explicit package change. |
| 38 | P1 | Improve the Run loop. | Persist recent stdin, active source, and case choice per problem. Rerun uses the displayed inputs. Save & Run checks the draft base and confirms the saved source only once. A saved run on older bytes is marked earlier evidence. |
| 39 | P1 | Link errors to precise files and inputs. | A compile issue opens its line. A test mismatch opens case and solution. A diagnostic for an old file cannot jump into lines presented as current evidence. |
| 40 | P1 | Add a structured tests and evidence view sourced by the verifier. | Filter by group and status. Display counts, validation and known-bad solution results. Show which file produced the expected answer and offer a scoped copy action. |
| 41 | P1 | Explain generated answer changes. | Preview sample/secret case counts, reference agreement and affected outputs. Keep execution and verification as separate actions with separate receipts. |
| 42 | P1 | Make verification outcome useful on first read. | Failed checks show the first actionable issue with Open file, Open case, Build answers, Measure limits or retry as applicable. Current and historical reports are visibly distinct. |
| 43 | P1 | Show the exact release checklist and its origin. | Shared workflow drives current Verify → Review → Generate/Download. Add filename, review and verification dates, format and snapshot details. Retain exact matching in the download path including old URLs. |
| 44 | P0 | Make approval's scope inspectable. | Group changes by file and purpose, with viewed state and cumulative diff against an available approved baseline. For out-of-band edits, offer an actual file review or clearly label a missing comparison baseline. Approval still binds the exact saved bytes. |
| 45 | P1 | Make the release view survive a later edit. | Prior artifact and report have a historical state. New export points to the precise missing prerequisite. A failed staging or network loss shows a safe recovery based on the existing job identity. |
| 46 | P1 | Improve job and agent status in place. | Distinguish waiting for workspace, working, awaiting choice, stopping, ended and disconnected. Add an elapsed duration only when it helps. Reconnect observes the same job. Sender may continue writing. |
| 47 | P0 | Keep model capability, user authority and evidence source explicit. | Label simulated worker, real process evidence, local execution, unsupported profile and any provider limit separately. “Verified” refers to a particular saved package and deterministic checks. |
| 48 | P2 | Add a concise handoff summary for another setter. | Show problem/rule decisions, evidence carried, unresolved items, and archive revision. A local copy/export action follows audience-aware visibility and secret-scope policy. |

**Build boundary.** Reuse package hashes, the release workflow, and the
LangGraph run and ledger contracts. Agent-authored drafts, editor buffers and
the saved judge package continue to have separate state. A host-approved
write or deliberate copy bridges them. Approval stays human and current.
Expand snapshot history for reviewed diffs only after confirming the storage
and package policy work for real author fixtures.

## Release 4 · Qualify and showcase

| ID | Priority | Change | Done when |
| --- | --- | --- | --- |
| 49 | P2 | Use a measured or explicitly estimated request context breakdown. | Context accounts for role/model, request time, reported or estimated source, user-visible category totals, capacity and unknown/unallocated tokens. Use safe metadata, with no raw hidden prompts or private test contents. |
| 50 | P2 | Keep the bar and map compact and optional. | A small bar beside the composer opens the map. Category focus works by keyboard and touch. Escape/outside closes it. Unknown data uses a text explanation. No percentage is drawn from lifetime usage or stored-item counts. |
| 51 | P1 | Add a safe, repeatable sample experience. | A named demo opens or creates its own labelled synthetic problem and can demonstrate a choice, counterexample, fix, verification and human export without replacing the operator's current work. |
| 52 | P1 | Qualify the two core product paths. | A new setter can complete chat-led authoring and an existing setter can run/verify from the workspace. Each can switch layouts mid-task and return to the same place. |
| 53 | P1 | Baseline long-session response and polish hot paths. | Use repeatable 100/500-message, 50/300-file and big-report fixtures. Capture p50/p95 for local interactions and isolate provider time. Keypresses and caret stay responsive during polling. Act on measured hot paths. |
| 54 | P1 | Check accessible use beyond DOM assertions. | Manually test keyboard-only, screen-reader status and composite controls, high contrast, reduced motion, 200% zoom and narrow reflow. Record browser/device/version, failures and fixes. |
| 55 | P1 | Test recovery and real import compatibility. | Synthetic offline and delayed updates exercise reload, stop and conflict. Verify ZIP contents and perform an approved disposable DOMjudge import against the stated version before claiming import qualification. |
| 56 | P1 | Run formative author sessions and establish a lightweight polish routine. | Observe three to five setters across the jobs in the experience map. Record errors and time lost with permission. Triage common delays using the same acceptance criteria and preserve a small recurring polish budget. |
| 57 | P2 | Publish a verified portfolio narrative when authorized. | A short recorded run explains the author’s choice, the independent check, the correction and approved release. Describe tested capabilities with dates and separate scripted, real-model and real-worker evidence. |
| 58 | P2 | Maintain a small component and wording inventory. | Shared actions and state labels have usage examples for desktop, narrow, error, stale and loading. Review intentional differences across Studio and classic. |

## Cross-release acceptance

These are proposed gates for implementation. Each must be tied to a fixture
and an observed outcome. Use current checked-in tests where they already cover
the contract.

| Gate | Script for verification | Required outcome |
| --- | --- | --- |
| A · Naming | Start unnamed, name it before send, link a different existing package, rename after approved generation, retry after a conflict. Include duplicate prefixes, Unicode and TeX-special characters. | One explicit name change reaches correct title surfaces. Stable IDs survive. Imported bytes change only after the explicit matching choice. The old approval never authorizes new bytes. |
| B · Continuity | Draft a message, click a choice, switch problem, reload, edit one file, simulate storage denial, then reopen two tabs with a changed base. | Unsent and unsaved work recovers within its scope or visibly reports unavailability. Exact selection recovers where supported. Editor remains usable. No hidden send or save. |
| C · Onboarding | Open an empty instance with configured, unconfigured and demo modes. Enter an unsupported idea, then work manually on a local package. | The setter knows what can be attempted and finds useful manual tools. Returning from settings preserves the draft. |
| D · Evidence | Inspect a genuine expected/actual mismatch, run the case again, submit a correction and verify its effect on dependent artifacts. | A reader can reach the case and relevant code without hand-copying paths. Evidence shows whether it is current and records the author’s decision. |
| E · Review and release | Change a package on disk after export, re-verify, review the actual change, approve and generate. Interrupt a generation attempt once and open the drawer after reload. | New approval and revision are enforced by the server. Download resolves to the intended title and archive. Historical output and recoverable errors are inspectable. |
| F · Keyboard and narrow | Complete a named problem → decision → file → Run/Verify → review with keyboard. Inspect 320/390, 768, 1280 and 1440 widths, both themes and 200% zoom. | Names and controls remain reachable, focus returns after dismissal, editor has space, exceptions scroll inside their own region, and meaningful statuses are announced. |
| G · Stress and recovery | 100/500-turn transcript and 50/300-file workspaces. Drop status reads, reload mid-job, emit a late result, and stage the same save from two tabs. | No cross-problem action, lost draft, wrong receipt or false success. Trace local delays separately from queue/worker/provider time. |
| H · Regression compatibility | Run engine/API contracts, classic UI/transition tests, title/export tests, and preview archives. | Existing valid approved ZIPs open, shared package rules agree across entry points, and prior command/route compatibility passes. |

### Measurement and rollout

1. Record task completion, avoidable mistakes, time to recover, and the number
   of steps to resume, rename, find a failure and export. Use scripted fixtures
   for direct before/after counts and observed authors for interpretation.
2. Treat **zero silent loss**, **zero wrong-target effects**, and **zero stale
   export approvals** as the hard acceptance outcomes for the scripted cases.
   Aim for one obvious entry point for rename, and no retyping after a normal
   reload. Set latency thresholds relative to the first comparable local
   baseline. Use no remote analytics requirement.
3. Test contract changes with synthetic storage and fixtures. Capture browser
   notes on the local release route. Roll out in bounded slices using stored
   data from prior versions in a disposable copy. A compatibility read or
   additive migration should preserve historical records and approvals.
4. Treat a failed work-preservation, consent or snapshot gate as a release
   blocker for the affected slice. A visual regression can be isolated by
   using the existing route and component contract while correcting the
   design change. Record what passed, what needs review, and the test mode.
5. Use a small human study without assuming impact. Give each participant a
   realistic task, observe silently, then ask how they chose the next action
   and what they believed was saved. Feed results into prioritization.

### Example wording for the first slice

| Moment | Proposed wording |
| --- | --- |
| Saving a linked title after export | “This updates the problem title in judge metadata and supported statement files. Verify and approve again before downloading a new ZIP.” |
| Existing package with a different title | “This package is named Workshop Sum. Link it with that name or update it to Canal Relays.” |
| Decision preserves another draft | “Choice saved. Your unsent message is still in the composer.” |
| Restored code | “Draft recovered. Compare it with the saved file before replacing it.” |
| Connection loss during a job | “The job may still be running. Reconnect to check its result.” |
| Ready to deliver | “Canal Relays is verified and approved for this version. Generate the DOMjudge ZIP.” |

Use this wording as behavior guidance. Verify it in context with long
problem names, errors and repeated actions.
