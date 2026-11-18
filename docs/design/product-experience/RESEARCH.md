# Research and design direction

18 November 2026

The product should feel like a focused workbench for a problem setter. The
strongest evidence comes from the current journeys and the project's interaction
history. Public references supply useful patterns and visual comparisons. Their
marketing screens and documentation establish different kinds of evidence.

## Reference shortlist

| Reference | Evidence consulted | Lesson for Studio | Adaptation |
| --- | --- | --- | --- |
| [Linear via Refero](https://styles.refero.design/style/90ce5883-bb24-4466-93f7-801cd617b0d1) | Live style page and rendered DESIGN.md export | Fine visual hierarchy, compact neutral controls and one high-salience action | Apply its spacing discipline to toolbars and the problem list using Studio's teal. Keep long mathematical prose comfortable. |
| [Raycast via Refero](https://styles.refero.design/style/3b6a17f0-3bdf-418c-a95e-0b89e5a8b2f8) | Live style page and rendered DESIGN.md export | A predictable command surface and visible hints help expert navigation | Use quiet keyboard hints in commands and file search. Leave hero scale and branding with the source. |
| [Notion via Refero](https://styles.refero.design/style/2bf4c61f-de10-4614-ba1b-20c0453bd2a9) | Live style page and rendered DESIGN.md export | Readable writing surfaces and well-separated control and reading typography | Keep a measured text column and give proof, code and tables their own presentation. Use the existing sans and mono family. |
| [Linear's collapsible sidebar](https://linear.app/changelog/unpublished-collapsible-sidebar) and [command actions](https://linear.app/docs/select-issues) | Product documentation and example visuals | Mouse and keyboard can reach the same actions. Collapsing a surface helps the current task. | Make switcher and file search equally useful by pointer. Keep commands scoped to the visible problem. |
| [VS Code interface](https://code.visualstudio.com/docs/editing/getting-started/userinterface) and [Hot Exit](https://code.visualstudio.com/docs/editing/codebasics#_hot-exit) | Official docs describe Quick Open, preview tabs, disambiguation, resize and recovery | Reopening unsaved work and quickly finding a similarly named file are core editor behavior | Apply them to package and conversation files with explicit source and base hash. Keep the simpler set of panes Studio needs. |
| [Bencho Context meter, Field](https://bencho.dev/?c=context-meter&style=Field&theme=dark) | Exact live demo observed in IAB. Free block source and licence inspection recorded in the earlier component review. | A tiny bar can open a more expressive composition map. Toggleable categories focus inspection. | Keep the map inside the existing anchored popover. Use direct keyboard/touch controls, role-specific data and an honest unknown state. Leave demo values, sound and simulated compaction in the demo. |
| [Claude Code interactive mode](https://code.claude.com/docs/en/interactive-mode#queue-messages-while-claude-works) | Official behavior docs describe queue visibility, ordering, and attached selection | Queued work and the context present when it was submitted are visible | Give each message a receipt, retain the draft independently, and keep attachments bound to the sent target. Studio retains its own permission rules. |
| [Microsoft HAX correction](https://www.microsoft.com/en-us/haxtoolkit/guideline/support-efficient-correction/) and [consequences](https://www.microsoft.com/en-us/haxtoolkit/guideline/convey-the-consequences-of-user-actions/) | Primary design guidelines and patterns | Make corrections efficient and give users enough information to predict effects | Explain linked rename impact, reopen a semantic decision and show which material needs checking again. |
| [GitHub review workflow](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/reviewing-proposed-changes-in-a-pull-request) | Official review docs describe filtering, file tree, split/unified diff and approval | Review works better when changes are scoped, comparable and navigable | Group changes by file and purpose, link to source and retain chronological history under details. Keep approval on the exact saved package. |
| [DOMjudge 8.2 format](https://www.domjudge.org/docs/manual/8.2/problem-format.html) and [ICPC legacy format](httpC://Projects.io/problem-package-format/spec/legacy-icpc) | Versioned judge and referenced format documentation | The title can appear in metadata and the contestant statement. The ZIP is an import package with a particular format. | Show package profile, exact title and filename. Distinguish local verification from a disposable import check against a named judge version. |

Refero describes its extracted measurements as normalized and recommendations
as interpreted. Its HTML examples are reconstructions. Use the exports as
design references and verify Studio's own tokens, fonts, contrast and behavior.
The exact Bencho example is a separate interaction reference. Its demonstration
numbers are illustrative.

For access and behavior use [modal dialogs](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/),
[comboboxes](https://www.w3.org/WAI/ARIA/apg/patterns/combobox/),
[splitters](https://www.w3.org/WAI/ARIA/apg/patterns/windowsplitter/),
[reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html),
[contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html),
[target size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)
and [status messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html).

## Design decision

**Refine the technical Studio in place.** Use Linear and Raycast for compact
orientation, Notion for reading rhythm, and the editor and review references for
behavior. Concentrate polish in useful signals such as “Draft recovered”, “Run
saved source”, a named case with expected and actual output, and a release button
that leads to the correct prerequisite. The applied title, scoped package, and
active revision should read as parts of one coherent experience.

| Direction considered | Where it works | Fit for this release |
| --- | --- | --- |
| Technical studio | Long conversations, source, cases, verification and keyboard work | Selected. Existing graphite navigation, neutral canvas and teal survive. Their supporting hierarchy gets clearer. |
| Warmer, document-first proof desk | Longer editorials and printed problem statements | Use the reading rhythm in prose and Markdown. The current technical shell makes switching to tools and judge evidence easier. |
| Dense agent operations console | Long-running coordination, deep diagnostics and parallel work | Put useful event and attempt details behind Activity. Lead with the current task and what requires the author. |
| Full component/framework migration | A product with several UI teams and an established shared component build | Reconsider only if measured maintenance or interaction costs justify it. The first releases are safer on the existing native and Monaco foundation. |

### Visual and interaction details

- **Type.** Start at 14px for controls, 18px for long-form reading, and 15px for
  code. Let the reading control adjust prose and previews. Use monospace for
  code, case fixtures and hashes. Keep consequential labels at a readable size.
- **Spacing.** Use a 4px scale and 6–8px corners. A single toolbar row gets the
  task action at wide widths. At narrow widths reduce the chrome and put compact
  secondary actions in a labelled menu. Start at a 40px touch target and check
  24px or applicable spacing on desktop. The 40px figure is a product target.
- **Color.** Retain Studio canvas, ink and accent roles. Add a distinct error
  text role `#a83145` light and `#ff9eae` dark. Calculated source-token
  examples on their specified surfaces were 6.51:1 for light accent on white,
  5.63:1 for light muted on canvas, 9.89:1 for dark accent on dark surface, and
  6.58:1 and 8.19:1 for the proposed error pairs. Check actual computed colors,
  focus indicators, editor widgets and every badge in both themes.
- **Motion and feedback.** Use short state transitions for opening a drawer or
  moving a selection. Honor reduced motion and keep layout stable while results
  stream. Announce meaningful transitions once. Let failures and next actions
  stay visible until acknowledged or resolved.
- **Content.** Use a normal heading and one sentence with the next action.
  Stable codes, timestamps, model attempt IDs, digests and raw text belong in
  Details. A result can show an example input with copy and run actions without
  ejecting the author from the current file.

## Component choices

| Component | Implementation route | Conditions to verify |
| --- | --- | --- |
| Rename, link, conflict and release review | Reuse native `dialog` and shared focus/validation helpers in Studio and the classic dialog controller where compatible | Initial focus, clear Cancel, Enter/IME behavior, Escape, labelled error, no focus reset on data refresh, restoration to the invoker |
| Problem switcher and quick file open | Build on a native input/dialog and the existing search data. Adopt accessible list/combobox behavior when the listing needs it | Arrow/Enter/Escape, full title/path announced, distinct names, scoped and stable selection, no model request |
| File editor and compare | Reuse local Monaco loader, models and classic diff capability. Add per-buffer persisted state and a plain-text fallback | Model disposal, separate cursor/scroll, base hash and conflict fence, no save from fallback until scope is known |
| Markdown and proof reading | Reuse the vendored renderer and sanitizer in [the local manifest](../../../web/vendor/studio/manifest.json), with an audited allowlist | Marked 18.2.1 and DOMPurify 3.4.18 as present on disk. Sanitize both chat and preview where rich rendering is added. Assess offline math separately with license evidence and known rendering limitations. |
| Context bar and field | Native popover plus a small controlled map based on Bencho behavior. Recheck [licence](https://bencho.dev/licence) if reusing exact source and preserve required notices such as the MIT notice | Button, Escape/focus return, textual legend and role-specific availability. Local/offline assets. This plan adopts the interaction and carries no third-party source. |
| Inline decisions, evidence and status | Reuse the current transcript slots, server workflow and typed ledger records | Message focus and position, evidence attribution, current/stale state, scoped authorization, live-region noise, safe text content |
| Workspace resize | Reuse splitters, reset and keyboard support. Add temporary narrow file navigation | Touch sizes, pointer capture, arrows and limits, focus, data persistence, current workspace listening to redraw |

The proposed changes keep each view composable with existing routes. New UI data
needs a named source and revision rule so Studio, classic, and the agent can
describe the same saved work.
