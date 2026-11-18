# Author Studio

Author Studio is the default application at `/`. The classic workspace and
settings are at `/workbench`. The approved interaction and reference source
material is in the Author Studio design proposal.

## Product experience refinement

The [product experience plan](docs/design/product-experience/README.md) is the
design handoff for the Studio releases. Release 1 implements naming and
continuity. Release 2 implements searchable navigation, keyboard commands,
file tabs, and layouts for narrow work. The release gates still use the saved
package workflow. Release 3 connects chat evidence to those gates through
case replay, verification reports, and human review of saved files. Release 4
adds a context receipt, a separate sample, and recovery for interrupted jobs.

| Region | Wide layout | Narrow layout |
| --- | --- | --- |
| Problem navigation | Searchable recent picker and New problem. The title and its edit action anchor the header. | The problem button opens the same picker, with full titles and search. |
| Conversation | Readable transcript, current decision or result, stable composer with small context bar. | Full-width working view with a clearly labelled switch to workspace. |
| Workspace | A collapsible grouped file tree, resizable work areas, preview and pinned tabs. | Open file brings up a searchable picker. The editor uses the full width, and output temporarily covers it. Closing output returns focus to the workspace. |
| Release | Export ZIP leads to Verify, Review or ZIP for the saved version. | Open the same actions from Commands. |

Defaults are 14px controls, 18px reading and 15px code, with independent reading
size, code size, and workspace spacing in **Appearance**. Keep the 4px spacing scale and existing neutral and teal
roles. Use colour with text, short motion with a reduced-motion fallback, and
local assets. The context field stays inside its anchored popup. Its display
depends on role-specific request data.

Title, package and work-in-progress each need a distinct save signal. A linked
rename previews the consequence for the release. An imported package presents
its title and a deliberate choice about matching names. Draft recovery returns
the author's work in an unsaved state. See the [Release 1 verification](docs/design/product-experience/RELEASE-1.md)
and the [remaining acceptance gates](docs/design/product-experience/DELIVERY.md#cross-release-acceptance).

## Evidence and release

Chat presents a receipt in the same reading column as the claim. Put expected
and actual output together, keep case text selectable, and tuck implementation
details under a disclosure. Run this case opens the workspace with the input
ready and asks the setter to confirm the saved source. Label a simulated
worker, a manual local process, and package verification at the point of use.
Use the existing code type and teal action role.

Verification leads with a primary recovery action, then exposes filters,
individual cases, and the saved sources that support the conclusions. The
release panel follows the saved workflow in order. Review groups files by
purpose and uses a cumulative diff when comparable approved text exists.
Viewed state helps the setter resume. Approval covers the entire displayed
snapshot. Earlier results and archives remain visible with their revision;
Generate and Download follow the current package's gates.

Use native disclosures, buttons and selects inside the existing workspace
output panel. The same information and controls fit its narrow layout. A
handoff contains receipt references and open decisions, with private content
kept in the local files. See [Release 3 verification](docs/design/product-experience/RELEASE-3.md).

## Request context and sample

The composer shows a small capacity bar only when the selected request has a
known capacity. The native popover contains the role, model, request time,
number source, and a compact category map. Category buttons work with keyboard
or touch and announce their estimates. Narration distinguishes provider totals
from estimated allocations. An unconfigured model or a missing capacity uses
plain text. Keep categories visible next to their labels in forced colors.

The Canal Bookings sample uses its own chat and workspace. The starter code is
deliberately wrong on the weighted case. The setter can load a fix as a draft,
confirm it with Save & Run, and export after the usual human review. Keep the
sample label visible across layouts. Long chats open on the newest page and
older pages load on request. When a package operation loses its connection,
look up the saved request ID and resume observing its original job.

## Working flow

Start from a conversation or open a package for manual work. Decisions and
artifact links appear in the conversation. Use **Name** or **F2** to title a new
problem before sending the idea. A newly created package follows that title.
For an existing package, choose whether to keep its name or match the problem
title. **Rename** previews changed files, the ZIP filename and any verification
and review needed before release.
Files opens the optional workspace, with separate groups for
conversation artifacts and the linked judge package. A conversation artifact
keeps its source revision and validity. Copy to package opens a draft at an
explicit destination, where the author can edit and save it. Subsequent engine
changes appear as conversation artifacts. Review the changes before applying
them to the package.

The action bar works directly with the linked judge package snapshot. Run
executes the saved source selected by the author, with provided standard input.
Build tests builds expected answers for existing test inputs from reference
solutions. Verify checks the package, links case and solution files, and lets
the author bring the report into chat. The output drawer distinguishes a queued
job, a requested stop and a completed stop. Jobs with backend cancellation
support expose Cancel job. If the status connection drops, reconnect to the
same job from its drawer. Local Run uses the
existing bounded host runner and reports its exit, timeout, or compile failure.
Measure limits is available alongside verification.

Export ZIP requires a passing verification report and human approval for the
current saved snapshot. The drawer points to the next action. Review can
approve the saved revision even if an outside edit created no change-log entry.
An approved ZIP for that revision remains available after a reload. The
server checks readiness and archive identity again for each download. Old
reports remain inspectable with an outdated label. See the
[application state contracts](docs/architecture/state-machines.md).

## Layout and editor

Chat is the initial view. Together opens a resizable workspace beside it, and
Workspace gives files the full scene. The output drawer opens on demand and can
resize independently. Wide workspaces retain their tree and splitter preferences.
At 850px and below, Chat and Workspace are separate views. Open file is the
temporary file picker. The output drawer becomes a full-width workspace view.
Reading size, editor size, resize preferences, density and theme follow local
preferences.

Use **Alt+K** for Commands, **Alt+P** for problems, and **Alt+O** for files.
The same controls work by pointer. In the tab strip, arrow keys switch tabs,
Home and End select the first and last, and Delete closes the focused tab.
Opening a file previews it. Editing or choosing Pin tab keeps it open.
Duplicate names show their path or revision. Reopen tab and the file picker
can recover a closed draft.

Monaco is loaded on demand with independent models for open files, undoable
formatting and diagnostics that can focus the relevant line. A text editor
remains usable if Monaco assets fail to load. Local draft recovery remembers
the composer, open tabs, editor position and last relevant output. Decision
buttons preserve the composer. Reopening keeps recovered files unsaved, and
Save compares the base hash with the current saved file. An uncertain chat
receipt is checked before an explicit retry uses the same request ID. Markdown renders
in Edit, Preview or Split using the pinned, locally hosted Marked and DOMPurify
dependencies. C/C++ formatting uses clang-format and diagnostics use GCC.
Python format and lint use Ruff. JSON has built-in formatting and validation.
Unavailable tools are reported by file type.
Generated statement PDFs open in their own tab. A local Poppler converter
renders the first page when available, with a link to the complete PDF.

The context control in the composer opens a compact popover. The current engine
does not publish a per-category request breakdown. The popover labels context
usage as unavailable and shows separately the number of materials stored.

---

# Classic workbench: The Proof Desk — design and experience contract

Status: working, implemented. Updated: 2026-11-17.
Evidence: [research](docs/design/research.md) · [components](docs/design/components.md) · [verification](docs/design/verification.md)

## Audience and purpose

One private ICPC problem setter works locally on one problem at a time. They
arrive with an incomplete idea, develop it through conversation, contribute
proofs/tests/solutions, inspect derived artifacts and evidence, correct
themselves, and eventually verify a package. Success means the author always
knows what the desk is doing, which question needs them, what evidence is
current, and how to recover a failed turn without preparing files or internal
identifiers. The same author returns across long sessions and reloads.

Known: desktop keyboard use, long-form statement/proof reading, exact status and
evidence are consequential, V0–V3 export is disabled. Assumption: narrow layout
is a reading/reply fallback rather than full mobile authoring. No user study,
analytics or author feedback was available.

## Design thesis

**A proof desk, not an AI dashboard.** Warm paper (`#f4efe6`), near-black ink,
one editorial red used for the author's mark, the open question and the primary
act. Problem prose and decisions use an editorial serif; UI controls use a
compact sans; code, paths and status use mono. Rules replace cards. The pipeline
is a ledger, not a stack of pills. The authoring conversation is docked as a
right-hand correspondence column on wide screens, so the plan and manuscript
remain visible while the author writes; below 1100px it becomes a focused sheet.
The signature detail is the **red margin rule** through the transcript and the
**open-question docket** — both tell the author where their attention is required.

## Reference curation

| Reference and exact URL | Evidence / access date | What we adopt | What we change or omit | Rationale |
|---|---|---|---|---|
| [Notion — Refero](https://styles.refero.design/style/2bf4c61f-de10-4614-ba1b-20c0453bd2a9) | `DESIGN.md` export + catalogue, 2026-11-17; live screenshot unsuccessful | Warm paper, ink hierarchy, hairline surfaces, one accent, sparing serif | Marketing hero scale, multicolor cards, playful motion, brand assets | Long proof/statement reading needs warmth and ruled order, not a landing page |
| [Superhuman — Refero](https://styles.refero.design/style/418b374a-be64-44f0-b17e-1d45308c7e62) | Live style page screenshot + export, 2026-11-17 | Parchment/ink, restrained punctuation, editorial hierarchy, keyboard-first density | Photography, maroon/lilac brand palette, large marketing type | Fits a private productivity tool with exact status and long sessions |
| [Hyer Aviation — Refero](https://styles.refero.design/style/f61cf515-ccd5-4494-bdd1-be9fe4d7258c) | `DESIGN.md` export, 2026-11-17 | One warm accent lesson | Enormous display type, pill buttons, spacious travel composition | Scale and airiness reduce scan density for a proof/test desk |
| [Refero Styles](https://styles.refero.design/) | Live catalogue + capture, 2026-11-17 | Method: compare systems and read exports critically | Catalogue's dark display aesthetic | Index, not a style |
| [Designeer Resources](https://designeer.xyz/resources) | Live catalogue, 2026-11-17 | Discovery of type/contrast tools | React component registries | Stack mismatch; no source adopted |

The project decisions below govern implementation. Detailed observations,
rejected alternatives and access limits are in [research.md](docs/design/research.md).

## Information architecture and journeys

The workbench is a single route (`/`) with a top masthead, a contents rail, a
plan/editor group and a conversation column. The Authoring desk is an explicit
mode opened from the masthead. The legacy general agent remains as **Classic
agent** in the right rail when the desk is closed; the desk replaces that rail
while open on wide screens. The contents rail switches Chats/Files/Changes; the
editor tabs switch Plan/File/Report/Diff/History/MCP.

| Journey | Entry and action sequence | Completion signal | Failure / recovery | Continuity |
|---|---|---|---|---|
| First problem idea | Authoring desk → New → type one sentence → send | The desk frames the problem or asks one consequential question | Unavailable/malformed model shows a recovery card; input remains fenced | Draft text stays in composer; transcript persists |
| Resolve semantics | Open-question docket → choose a ruled option or answer in words | Choice is stamped into the transcript; artifacts become current | Tentative/negated/quoted answer keeps the question open | Card and answer remain visible; reload keeps them |
| Contribute and inspect | Type lemma/test/solution → send → open Working ledger → artifact | Attributed contribution and artifact path/status appear | Stale/unresolved artifact is labelled with reason; Retry/recovery remains | Original transcript and file context preserved |
| Correct a constraint | State a correction → send | New generation; old proof/test/plan support marked stale | Old material remains historical; no silent deletion | Correction and superseded artifacts remain in history |
| Recover a failed turn | Failure card → Reload if needed → Retry this request | Old failure remains visible; replacement work is admitted and may publish once | Cancel remains available; unrelated barriers are not cleared | Recovery card and original request persist |
| Verify/export | Verify in masthead; inspect plan/report | Verification state and evidence are visible | Export stays disabled until the gate; V5 remains unsupported | Workspace and conversation remain |

## Screen composition

| Screen / route | Primary information and action | Secondary content | Layout and reading order |
|---|---|---|---|
| Workbench `/` | Problem title, current plan/progress, primary "Authoring desk" | Classic agent, files, changes, run, evidence, history | Masthead → contents rail → ruled plan ledger → right conversation rail; 54px masthead, 44px activity rail, 286px contents, fluid editor |
| Authoring desk (wide) | Conversation, current open question, composer | Conversation picker, disclosure, working ledger | Docked 620px right column; header → conversation toolbar → disclosure → transcript → composer → ledger; plan remains left |
| Authoring desk (narrow) | Same, reading-first | Ledger on demand | Full-screen sheet with its own header; wrapped workbench masthead behind it; composer before ledger |
| Files/editor | File tree/open file, code | Tabs, cursor, run panel | Contents rail → file tree → dark code slab; code remains a distinct surface |
| Dialogs/settings | One task and its consequence | Context/help | Existing modal controllers, paper surface, red primary action |

Cards are used only for the open question and recovery/finding; other content is
unboxed and separated by hairlines. This keeps evidence, pipeline and long text
from fragmenting into tiles.

## Tokens and typography

| Role | Value(s) | Usage / constraint |
|---|---|---|
| Canvas / deep / surface / raised / sunken | `#f4efe6` / `#ece5d9` / `#fbf8f1` / `#fffdf8` / `#e9e2d6` | Paper hierarchy; no pure-white canvas |
| Ink / soft / muted / faint | `#211d18` / `#4d463c` / `#6b6257` / `#6f6558` | Contrast computed; faint ≥ 4.9:1 on paper |
| Accent / deep / soft / ink | `#96382f` / `#76291f` / `#f0ddd8` / `#fffaf3` | Author's red; primary action, open question, margin rule |
| Olive / success / warning / danger / info | `#4f6653` / `#3f6b52` / `#86611f` / `#9d352c` / `#3d5f74` | Text/icon accompanies color; never color-only status |
| Borders | line `#d8cfc1`, strong `#968772` | Strong ≥ 3.3:1 on surface for controls; line for dividers |
| Dark variant | paper `#171410`, surface `#1e1a15`, ink `#f0e8db`, accent `#e08a7c` | Preserved dark ink mode; not the default |
| Body / heading / code | Inter/Segoe UI/system; Iowan Old Style/Palatino/Georgia; Cascadia/JetBrains Mono/Consolas | System fonts only; no webfont download or network dependency |
| Type scale | 9px eyebrow, 11–12.5 UI, 13–14 body, 18/23/26/34 serif headings, 10.5–12 code | Tight but readable; 1.45–1.55 body line-height |
| Spacing | 4px base; 6/8/12/16/20/24; 18–22 section padding | Dense but ruled; no large marketing gaps |
| Radii / elevation | 2px controls, 3px sheet, 1px status stamps; only the desk/overlays use shadows | Coherent ruled nesting; no elevation stacks |
| Motion | 140–180ms ease; desk entry; reduced-motion disables | Feedback only; no decorative looping |

Dark mode is retained as an **ink desk** because the app already exposes a theme
toggle and code/reading in low light is a real use case. It is not added for
template completeness.

## Components and patterns

| Component | Existing / selected source | Project adaptation | Behavior and states |
|---|---|---|---|
| Masthead | `web/index.html` topbar; app.js handlers | Serif brand, red desk action, human status stamp | Keyboard focus; export disabled state |
| Contents rail | `#navigator`, `.side-tabs` | Ruled contents; red active margin | Existing app.js tab/ARIA behavior |
| Plan ledger | `renderPlanResult` | Ruled rows, mono detail, no pills | Done/fail/incomplete labels + color |
| Authoring desk | `#collab-panel`, `web/engine.js` | Docked column/sheet, human status, collapsed disclosure, composer before ledger | Empty, waiting, ready, working, blocked, cancelled; recovery card |
| Decision docket | `.collab-msg.decision` + `.card-options` | Open-question kicker; option label + consequence; no repeated option prose | Click, keyboard, free-text answer; card remains on uncertainty |
| Recovery card | `kind="recovery"` + Retry | Red attention note; full-width Retry bound to failed input | Explicit recovery, cancel; history preserved |
| Working ledger | Existing details/sections | Summary rows; native disclosure | Artifacts, inputs, contributions, evidence, handoff, events on demand |
| Code/file editor | Native textarea/Monaco host | Dark code slab inside paper chrome in both themes | Existing editor/tabs/run states; not reimplemented |
| Status | `#collab-status`, `#status-pill` | Human labels, text+color | No raw enum strings in the author surface |

Full provenance, rejected components and license notes are in
[components.md](docs/design/components.md).

## Experience states and content

| Situation | What the user sees | Available action | What remains preserved |
|---|---|---|---|
| First use / empty desk | "What problem are you setting?" with two example ideas | Type or click an example into composer | No files/fixtures requested; internal run not pre-created |
| Loading / long operation | "Working…" receipt; busy state retains composer text | Keep typing (queued) | Existing transcript and draft |
| Pending question | Open-question docket with ruled choices and "Or answer…" | Choose, type, ask why, defer | Question and all history |
| Validation / error / retry | Recovery card with cause and Retry; no fake result | Retry, cancel, explain | Failed decision/attempt history and barrier |
| Success / partial | Applied turn, artifact status, handoff outcome | Inspect ledger, continue, verify | Current + historical artifacts |
| Permission / unavailable | "No model configured" panel or blocked status | Configure or cancel; V5 export refused | Conversation and local state |
| Narrow | Full-sheet desk, visible status, full-width composer | Read/reply; ledger on demand | Selected run and transcript |

Tone is direct and editorial: "Waiting for your choice", "Ready for you",
"Applied · turn 3", "No result was fabricated". Labels are sentence case; status
stamps are uppercase only as small metadata. Sample ideas are prompts, not real
results, and are visibly labelled as examples.

## Responsive and accessible behavior

- ≥1100px: desk is a 620px docked column; contents 286px; editor fluid; legacy
  conversation rail hidden while desk is open.
- 761–1099px: the masthead wraps to two rows; the desk is a 560px overlay drawer
  from the top-right, over the editor, with its own header and close control.
- ≤760px: desk is a full-screen sheet with its own header and close control;
  the workbench masthead wraps, status remains in the status bar, composer stays
  before the ledger, and horizontal overflow is avoided.
- Keyboard: native tab/select/textarea/button/details; `Ctrl+Enter` sends;
  `Escape` closes the desk; focus-visible 2px accent outline. No custom focus
  trap.
- Screen reader: transcript is `role=log` with `aria-live=polite`; buttons/labels
  retain names; details/summary native; status is text, not color-only.
- Contrast: body 14.6:1, muted 5.2:1, faint 4.98:1, accent 6.3:1, white on accent
  6.96:1, success/warning/danger > 5:1; control border 3.3:1 (dark 3.41:1).
  Dark tokens checked for faint 4.88:1 and accent 7.08:1.
- Touch: controls ≥ 30px in desk, ≥ 24px activity rail; primary actions larger.
  This is a usability choice, not a claim of full touch qualification.
- Reduced motion: all animation/transition durations collapse; desk entry is
  disabled.

## Interaction and motion

Motion communicates a sheet opening and state change, not decoration: 160–180ms
ease-out desk entry, 140ms control transitions, no looping. The transcript and
status update in place; the composer stays usable while work runs, with queued
text preserved. There is no hover-only essential action; all options are buttons
or typed text. Reduced-motion behavior is enforced in CSS.

## Frontend rebuild contract

Preserved routes, API contracts, IDs used by `web/app.js`/`web/engine.js`, the
single-owner engine, permissions, persistence and V3/V5 boundaries. No backend
replacement. The legacy workbench remains available; the Authoring desk is
docked when open. `web/design.css` is additive after the legacy styles; the only
markup changes restructure the desk and rename the topbar actions; engine.js adds
human status labels, option-prose suppression, an empty starter and a Retry/queue
affordance. Review by running the app and the existing browser journeys. The
superseded dark indigo visual layer remains in `style.css` but is overridden by
the canonical tokens; it can be retired only after the team confirms the legacy
theme is no longer needed.

## Verification and open decisions

| Journey / design requirement | Evidence to collect | Result and link |
|---|---|---|
| Empty desk → idea → pending question | Running UI at 1600/390; decision docket | Implemented; captured `desk-empty-1600.png`, `desk-decision-1600.png` |
| Failure → reload → Retry | Rendered recovery journey | Verified in existing browser recovery fixture; see verification |
| Resolve/contribute/correct/stale | Browser smoke/repair and full engine suite | Existing journeys rerun after CSS/JS changes |
| Composition / responsiveness | Captures 1600 and 390; overflow 0; panel dock/sheet | See verification |
| Keyboard/focus/reduced motion/contrast | CDP checks and computed pairs | See verification; no screen-reader claim |
| Dark ink variant | Toggle check | Implemented and tokenized; captured `desk-dark-1600.png` |

Open decision: the legacy general agent and the Authoring desk both remain
available; whether the classic agent should eventually be retired is a product
decision, not assumed here. No user validation or formal accessibility
conformance is claimed.
