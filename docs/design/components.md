# Component inventory and decisions

The application is vanilla HTML, CSS and JavaScript served by `server.py`.
No frontend framework or package installation was added for this redesign.

| Component / pattern | Exact source | Version / license evidence | Project destination | Adaptation and rationale | Behavior / checks / gaps |
|---|---|---|---|---|---|
| Top masthead, problem switcher, status stamp | Existing native markup in `web/index.html`; existing `#workspace-select`, `#status-pill` | Project source; no third-party asset | `web/index.html`, `web/design.css` | Serif wordmark, paper surface, red primary desk action, human status labels | Existing app.js handlers preserved; keyboard focus and labels retained; checked at 1600/390 |
| Contents rail and conversation list | Existing `.navigator`, `.side-tabs`, `#chat-list` in app.js | Project source | `web/style.css` overridden by `design.css` | Ruled contents list, red active margin, denser type; keeps app.js selection behavior | Existing click/aria/selection; no new focus trap |
| Authoring pipeline ledger | Existing `renderPlanResult` markup (`.plan-section`, `.pipeline`, `.pipeline-step`) in `web/app.js` | Project source | `web/design.css` | Replaced rounded pills with an editorial ledger of ruled rows and mono status detail; improves scan order for setter | Existing data/state unchanged; checked with empty and populated plan |
| Plan/current state sections | Existing `.agent-plan`, `.agent-step` | Project source | `web/design.css` | Hairline rows instead of cards; muted metadata | Existing app.js rendering; verified visually |
| Code/file editor | Existing native textarea, `<pre>` and Monaco host; `#file-view`, `#file-editor`, `#monaco-host` | Monaco is vendored/part of project; existing dependency not changed | `web/design.css`, `web/app.js` | Kept a dark code slab for code contrast in both themes; light chrome around it; no editor replacement | Existing editor behavior preserved; file view checked with populated LaTeX; Monaco forced to `vs-dark` so it matches the highlighted view |
| Buttons, inputs, selects, dialogs | Native HTML + existing app.js dialogs | Project source | `web/design.css` | 2px ruled controls, paper/ink states, accent focus ring; no framework primitives | Focus-visible CSS present; keyboard test via Tab/focus; native dialogs retain existing controller |
| Authoring desk sheet | Existing `#collab-panel` markup, restructured; `web/engine.js` | Project source | `web/index.html`, `web/design.css`, `web/engine.js` | Docked right column on >=1100px; focused sheet below; status humanized; disclosure collapsed; composer before ledger | Existing chat API/state and all test IDs retained; checked at 1600/390 and reduced motion |
| Decision docket | Existing `.collab-msg.decision` + `.card-options` rendering in `web/engine.js` | Project source | `web/design.css`, `web/engine.js` | Suppressed repeated prose options; card now shows label + consequence buttons; open-question kicker | Existing option handlers and rescue path; checked at open decision |
| Recovery card / retry | Existing `kind="recovery"` message + `recoverInputId` API; native button | Project source | `web/engine.js`, `web/design.css` | Red "Needs attention" note with a full-width Retry; history remains visible | Existing recovery tests; browser journey later |
| Collapsible disclosure and ledger | Native `<details>/<summary>` | Project source; no dependency | `web/index.html`, `web/design.css` | Model/worker/limits collapsed; working ledger on demand; keeps required disclosure available | Native keyboard/summary behavior; browser tests read textContent |
| Status stamp (engine) | `#collab-status` + `humanStatus()` | Project source | `web/engine.js`, `web/design.css` | Human labels ("Waiting for your choice", "Ready for you", "Cancelled") with distinct text, not color alone | Existing status API values preserved; verified waiting/ready/cancelled |
| Empty desk starter | `renderTranscript` new empty state | Project source | `web/engine.js`, `web/design.css` | Example prompts fill the composer; explains no setup needed | No automatic send; keyboard/click; checked 1600 |
| Icons | Existing Unicode glyphs in HTML and app.js | Project source | Existing markup | Kept to avoid an icon dependency; size/contrast adjusted | Glyph alt/aria labels retained where present; no icon license issue |
| Type | System stacks: Inter/Segoe UI/system, Iowan Old Style/Palatino/Georgia, Cascadia/JetBrains Mono/Consolas | System fonts; no webfont download or license added | `web/design.css` | Serif for problem reading, sans for controls, mono for code/status; avoids network/font loading | Fallback stacks documented; visual check on available Windows fonts |
| Color | Project tokens in `web/design.css` | Project source | `web/design.css` | Warm paper/ink/editorial red; dark ink variant retained | Contrast pairs computed; see `verification.md` |

## Author Studio release states

Studio uses the same backend gates as the classic Workbench. Classic keeps the
full authoring panel and provider settings. Studio puts frequently used actions
beside the chat and within the Commands picker on narrow screens.

| Component | Source and adaptation | Examples and checks |
| --- | --- | --- |
| Context bar and map | Local native popover, select and toggle buttons in `web/studio-context.js`. Bencho Field informed the interaction. | **No context receipt**, **Estimated**, **Provider-reported**, and **Model capacity is unknown**. Categories work with keyboard and touch. The label carries the value in forced colors. |
| Sample | Existing Commands dialog and an explicit empty-conversation button. Scripted mode is indicated in the provider and header. | **Open Canal Bookings sample**, **Start a fresh sample**, and **Load sample fix**. The preview becomes an unsaved draft before Save & Run. |
| Saved job | Existing output drawer, backend job receipt and local cursor. | **Waiting for the workspace**, **Reconnect to job**, and **The server has no receipt**. A completed Run still shows its source and case. |
| Review | Existing collapsible groups and shared package rules. | **Earlier verification**, **Approve saved snapshot**, and **Archive ready to download**. A stale package returns to the needed action. |
| History and file search | Existing transcript, combobox and native controls with bounded pages. | **Load earlier messages**, **Jump to latest**, and **Showing 50 of N matches**. Narrow and high-density checks use the same controls. |

See [Release 4 verification](product-experience/RELEASE-4.md) for the exact
Chrome, job recovery and DOMjudge results.

## Rejected candidates

| Candidate | Reason not adopted |
|---|---|
| shadcn/ui, Radix Primitives, React Aria, Base UI | React-only foundations; would require framework replacement for behavior already covered by native controls. No component source was copied. |
| Layro components / CLI | React TypeScript registry; CLI requires Node/React setup. Not compatible with this vanilla app; no install run. |
| aMicro transitions | Live site returned 429 during this research; React/motion payload unverified. Decorative motion not needed. |
| Piixpal / Stick It Up | Expressive character/sticker layers; would compete with a focused proof/test workflow. No assets copied. |
| Designeer directory listings | Used for discovery only; directory inclusion and showcase licensing do not establish component code licenses. No source adopted. |
| Hyer Aviation visual system | Luxury travel marketing scale; rejected for dense authoring (see research). |

## Verification gaps

- No screen-reader run, cross-browser matrix, or automated axe audit was executed.
- The file/editor and diff were checked with a populated LaTeX statement at 1600
  and 390; the Monaco worker, run/evidence panels and every dialog state remain
  uncaptured.
- The design applies to all shell surfaces through tokens, but dialogs, settings,
  tour and the legacy agent were not each visually captured after the change.
- No third-party code was adopted, so no third-party license/version pin is pending.
