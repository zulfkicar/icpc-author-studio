# Research: the proof desk

Access date for all live checks below: **2026-11-17** (Asia/Karachi). The
in-app browser relay was paired but its extension was offline, so live inspection
used headless Chrome, HTTP retrieval and the project's own CDP checks. That is a
real visual/interaction limitation, not a claim of user testing.

## 1. Product and audience

**Observed in the running app and source**

- One private ICPC problem setter, working locally under `C:\Projects\author-agent`.
  The app is loopback-only and single-user; it exposes no account or role system.
- The workbench already holds problem workspaces, files, a plan pipeline, a
  verification gate, a review queue, a run panel, notes/history and a legacy
  general agent. The conversation-first V0–V3 engine is opened separately from
  the top bar as **Collaborate**, now **Authoring desk**.
- The engine conversation is the normal path for creating the internal run,
  specification, editorial, candidate solution, validator, tests, proofs,
  decisions, evidence and recovery cards. It is durable in SQLite; the selected
  run is remembered in local storage. Reload resumes the transcript and pending
  card.
- Important routes and APIs: `/` (single-page workbench), `/api/state`,
  `/api/settings`, `/api/engine/capabilities`, `/api/engine/runs`,
  `/api/engine/runs/<id>/{view,chat,events,artifacts,decisions}`, `/api/engine/chat`,
  `/api/engine/runs/<id>/messages`, workspace/files/changes/jobs APIs, and dialog
  flows. The frontend preserves these contracts; no backend replacement.
- Permission and safety behavior observed: export is disabled until deterministic
  verification; V5 delivery/export/restore are refused; the engine decision layer
  is labelled demo or unconfigured; recovery cards can retry or cancel an
  unresolved turn; stale artifacts stay historical.
- Main tasks: describe a problem, resolve consequential semantics, contribute
  proof/solution/test material, inspect evidence and artifacts, correct mistakes,
  recover from a failed interpretation, verify, and return later.
- Device/input assumption: desktop keyboard-first authoring, with narrow fallback
  for reading and replying. No validated mobile/touch user research exists.

**Baseline problems observed**

- Two conversation surfaces competed: a legacy "Conversation" panel and the
  engine overlay. Raw engine states (`WAITING_HUMAN`, `AWAITING_AUTHOR`) leaked
  into the interface.
- The demo/worker disclosure occupied the most valuable space before the work,
  and the conversation selector sat below the composer.
- Decision cards repeated the options in prose and in buttons; long clarify and
  handoff notices were visually equal to the actual question.
- The dark indigo/AI-gradient theme made a long-form proof/statement desk feel
  generic and tired; the pipeline was a stack of rounded dark pills.
- Captures: `docs/design/captures/baseline-workbench.png` (initial),
  `baseline-collaborate-1600.png`, `baseline-collaborate-390.png`,
  `baseline-active-conversation-1600.png`.

## 2. Reference cards

### Refero Styles — catalogue

- **URL:** https://styles.refero.design/ (accessed 2026-11-17)
- **Evidence:** live page inspected and catalogue screenshots reviewed locally.
- **Lesson:** many distinct systems; cards show visual grammar, token exports and
  `DESIGN.md`. It is a starting point, not a default style. The catalogue itself
  uses a dark editorial/display treatment that is not appropriate for a dense
  workbench.
- **Decision:** research index, not a visual direction.

### Notion design system

- **URL:** https://styles.refero.design/style/2bf4c61f-de10-4614-ba1b-20c0453bd2a9
  (accessed 2026-11-17)
- **Evidence:** `DESIGN.md` export reviewed locally.
  The live page screenshot did not render usefully (tiny capture), so visual
  judgment is from the export and known product grammar, not a fresh screenshot.
- **Observed:** warm off-white paper `#f6f5f4`, ink at alpha levels, a single blue
  primary action, a sparing editorial serif, hairline 12px cards with no shadow,
  and sparse color used as punctuation.
- **Adapt:** warm paper, ink hierarchy, one accent, hairline ruled surfaces,
  editorial serif for problem/proof reading, no decorative shadows.
- **Omit/change:** marketing hero scale, multicolor sticky-note cards, playful
  bouncy motion, product branding. The workbench is not a landing page.
- **Decision:** **selected** as the primary warmth/reading reference.

### Superhuman design system

- **URL:** https://styles.refero.design/style/418b374a-be64-44f0-b17e-1d45308c7e62
  (accessed 2026-11-17)
- **Evidence:** live style page screenshot and `DESIGN.md` export reviewed locally.
- **Observed:** warm parchment, warm charcoal ink, hairline borders, quiet
  editorial hierarchy, color reserved for deliberate punctuation, keyboard-first
  productivity framing. It avoids elevation stacks on UI surfaces.
- **Adapt:** parchment + ink, restrained red punctuation, tabular numerals for
  status/progress, compact desktop productivity composition, keyboard hinting.
- **Omit/change:** photography, maroon brand fill, lilac secondary, large
  marketing type. The accent becomes an author's red editorial mark, not a brand
  color.
- **Decision:** **selected** as the primary productivity/density reference.

### Hyer Aviation design system

- **URL:** https://styles.refero.design/style/f61cf515-ccd5-4494-bdd1-be9fe4d7258c
  (accessed 2026-11-17)
- **Evidence:** `DESIGN.md` export read; no useful live screenshot retained.
- **Observed:** luxury travel editorial, enormous display type, spacious rhythm,
  pill buttons, one terracotta accent.
- **Why rejected:** its scale and airy marketing rhythm reduce scan density for a
  proof/test workbench. Pills and giant display type would compete with evidence
  and controls. One warm accent lesson was kept; the composition was not.
- **Decision:** **rejected** as a direction; supporting color lesson only.

### Designeer resources

- **URL:** https://designeer.xyz/resources (accessed 2026-11-17)
- **Evidence:** live catalogue read; 207 listings, categories for components,
  icons, motion/3D and type/colour; entries link to original sources.
- **Use:** checked complementary type/contrast tools (Fontshare, Utopia, OKLCH,
  Color.review) for availability thinking. No component was adopted: the project
  is vanilla HTML/CSS/JS and the useful candidates are React registries.
- **Decision:** discovery source only; no blanket asset reuse.

### aMicro

- **URL:** https://amicro.dev/ (attempted 2026-11-17)
- **Access limitation:** returned HTTP 429 in this session. I did not inspect the
  live catalogue, source payload, licence or behavior. The resources guide is
  the only evidence.
- **Decision:** **not adopted**. React/transition primitives are unnecessary for
  this native UI, and the live source was unavailable.

### Component foundations not adopted

- shadcn/ui, Radix, React Aria, Layro, Base UI: React-only or registry/account
  paths; this app is vanilla. Adopting one would change the framework for a
  component need that native `<details>`, `<select>`, `<textarea>`, buttons and
  CSS already cover.
- Piixpal and Stick It Up: expressive character/sticker systems. Rejected for the
  working desk; they would add personality to a place where the author needs
  quiet reading and precise status. No asset was copied.

## 3. Chosen direction

**The Proof Desk.** The interface behaves like a private mathematical editor's
desk: warm paper, near-black ink, one editorial red used for the author's mark,
the open question and the primary act. Problem prose and decisions use an
editorial serif; controls use a compact sans; code, paths and status use mono.
Rules replace cards; the pipeline is a ledger; the conversation is correspondence
with a margin note. The distinctive detail is the **red margin rule** running
through the desk transcript and the **open-question docket** — useful signals for
where the author's attention is required, not decoration.

The desk is docked as the right working column on wide screens, replacing the
legacy conversation rail while it is open; below 1100px it becomes a focused
sheet. This makes "the conversation is the work" true in layout, while the plan,
problem and files remain visible beside it.

Alternatives considered: a dark "precision instrument" cockpit (Hyer/Raycast-like)
was rejected for long statement/proof reading and because it reinforces the
generic AI-console look; a Notion-style colorful card canvas was rejected because
it would fragment evidence and status into decorative tiles.

## 4. Assumptions and open questions

- The private setter uses a desktop keyboard most of the time; narrow support is
  a reading/reply fallback, not a mobile authoring promise.
- No usability session, analytics or author feedback was available. The direction
  is desk research plus implementation inspection, not validated user testing.
- The legacy general agent and the engine authoring desk remain distinct tools;
  the desk is visually primary but auto-opening it was not assumed.
