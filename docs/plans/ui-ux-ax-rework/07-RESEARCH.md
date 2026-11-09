# Research notes

Research date: 2026-11-09. This document records what was read, what was
borrowed, and what was rejected. It is the evidence trail for the design and the
goal prompt.

## 1. UI/UX skill sources

| Source | Stars | License | Pushed | Used for |
|---|---:|---|---|---|
| [UI UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | 146,849 | MIT | 2026-11-07 | Priority gates: accessibility, interaction, performance, layout, typography, motion, forms, navigation |
| [UX/UI Agent Skills](https://github.com/plugin87/ux-ui-agent-skills) | 3,136 | MIT | 2026-10-27 | 52 objective gates; axe/contrast/keyboard/target-size/reflow; render-and-look |
| [Hallmark](https://github.com/Nutlope/hallmark) | 50,814 | MIT | 2026-11-05 | Anti-AI-slop review: no decorative filler, no empty frames, no machine-made patterns |

Applied subset: [`.opencode/skills/ui-ux-audit/SKILL.md`](../../../.opencode/skills/ui-ux-audit/SKILL.md).

The audit found the four reported defects and their shared root cause (grid
row without `minmax(0, 1fr)`), hover-only chat actions, and missing keyboard
activation for chat titles. Those are now fixed and tested.

## 2. IDE and interaction references

| Project | Stars | License | Pushed | Pattern borrowed |
|---|---:|---|---|---|
| [microsoft/vscode](https://github.com/microsoft/vscode) | 195,192 | MIT | 2026-11-08 | Activity bar → sidebar → editor group → panel → status bar; tabs, breadcrumbs, diff editor, command palette |
| [coder/code-server](https://github.com/coder/code-server) | 79,790 | MIT | 2026-11-07 | VS Code workbench in a browser; remote workspace model |
| [cline/cline](https://github.com/cline/cline) | 71,465 | Apache-2.0 | 2026-11-07 | Persistent chat webview (`App.tsx` keeps `ChatView` mounted), one flex column, one scrolling transcript, sticky composer, context mentions, inline approval/ask cards |
| [microsoft/monaco-editor](https://github.com/microsoft/monaco-editor) | 46,961 | MIT | 2026-11-08 | Browser editor, models per file, diff editor, workers |
| [judge0/ide](https://github.com/judge0/ide) | 1,127 | MIT | 2026-01-15 | Monaco 0.44, GoldenLayout panes, language/compiler options, stdin/stdout, Run, status line |
| [gitpod-io/gitpod](https://github.com/gitpod-io/gitpod) | 13,798 | AGPL | 2026-11-08 | Workspace lifecycle and IDE handoff; reference only |
| [stackblitz/core](https://github.com/stackblitz/core) | 10,891 | MIT | 2024-06-09 | Browser dev-environment UX; older reference |
| [codemirror/dev](https://github.com/codemirror/dev) | 7,807 | MIT | 2026-04-15 | Lighter editor alternative |

### What was borrowed

- **VS Code:** five-region skeleton, one primary scroll per region, tabs with
  dirty dots, breadcrumbs, bottom panel, status bar as information.
- **Cline:** the agent panel is persistent and never remounted; one flex
  column; transcript is the only scroller; composer sticky; approvals and
  clarifications are inline; context mentions are chips.
- **Judge0 IDE:** the run surface belongs to the editor, not a separate page;
  language, compiler options, stdin, stdout, Run, status.
- **Monaco:** use a real editor model for tabs and diffs.

### What was rejected

- **Iframing `judge0/ide` as the primary experience** — duplicates the editor,
  file model and theme; cannot share the workspace; needs its own CSP and
  message bridge; GoldenLayout lets users hide required panes.
- **Cline’s full-screen settings/history takeovers** — evidence should stay
  beside the code.
- **VS Code’s full activity surface** — this is a focused authoring tool, not a
  general IDE.
- **A frontend framework/bundler** — the app is a classic-script frontend; the
  migration would add risk without a product benefit.

## 3. Prompting research

### 3.1 Anthropic — Claude Code best practices

Source: <https://www.anthropic.com/engineering/claude-code-best-practices>

Extracted principles:

1. **Tell the model what it cannot see.** The repo is discoverable; team
   decisions, deploy steps, test commands and constraints are not.
2. **Keep the instruction file short.** Only what cannot be derived from the
   code; long files dilute attention.
3. **Give it a check to run.** A pass/fail command lets the agent close the
   loop: test suite, build exit code, linter, screenshot comparison.
4. **Ask for evidence.** The command and its output, not “all tests pass”.
5. **Separate deterministic from non-deterministic.** Prompts/skills are
   guidance; hooks, deny rules and tests are enforcement.
6. **Be specific and say what “fixed” looks like.** Name the file, symptom and
   acceptance.
7. **Say “be ambitious” when scope matters.** Models otherwise build the
   smallest thing that satisfies the request.
8. **For unattended runs:** know what done looks like, can self-check, allowed
   touch surface, stop bound, result destination and sign-off.
9. **Review against the spec**, not just general bug hunting. Ask for gaps that
   affect correctness and say “skip style”.
10. **Keep the first minute supervised.** Esc early; after two failed
    corrections, clear and rewrite the prompt.

### 3.2 Anthropic — `/goal`

Source: <https://code.claude.com/docs/en/goal>

Extracted principles:

- A goal is a **completion condition** checked after each turn by a separate
  model; it keeps the session working until met, impossible, or cleared.
- The evaluator only sees the transcript, so the condition must be
  **demonstrable in the transcript**.
- An effective condition has:
  - one measurable end state;
  - a stated check (e.g. `npm test` exits 0);
  - constraints that must not change;
  - a turn/time bound.
- The condition can be up to 4,000 characters.
- Use goals for substantial work with a verifiable end state, not vague
  “improve the UI”.

### 3.3 OpenAI — prompt engineering

Source: <https://platform.openai.com/docs/guides/prompt-engineering>

Extracted principles:

- Developer/system instructions carry higher authority than user input.
- A developer message usually has: **identity → instructions → examples →
  context**.
- Use Markdown/XML to delimit sections; keep the structure consistent.
- Few-shot examples steer format and scope; use diverse, consistent examples.
- Put reusable context first and the specific query near the end for long
  contexts.
- For coding agents: define the role, enforce structured tool use with
  examples, require tests/validation, and set Markdown standards.
- For agentic tasks: plan thoroughly, decompose into sub-tasks, keep going
  until resolved, explain notable tool calls, track progress with TODO/rubrics.
- Version prompts in code; test and evaluate them like code.
- Reasoning models do better with high-level goals; non-reasoning models need
  more explicit instructions.

### 3.4 Google — prompt design strategies

Source: <https://ai.google.dev/gemini-api/docs/prompting-strategies>

Extracted principles:

- Be precise and direct; avoid persuasive filler.
- Use consistent delimiters (XML tags or Markdown headings).
- Define ambiguous parameters.
- Control output verbosity explicitly.
- Put critical constraints and output format at the start/system level.
- For long context: context first, instructions/query last; add a transition
  phrase.
- Agentic dimensions to steer: reasoning depth, adaptability, persistence,
  risk assessment, ambiguity handling, verbosity, precision.
- The agentic system template: plan before action, resolve logical
  dependencies, assess risk, form/test hypotheses, adapt, ground claims,
  ensure completeness, persist intelligently, inhibit action until reasoning is
  complete.

### 3.5 GitHub Spec Kit — spec-driven development

Source: <https://github.com/github/spec-kit> and
<https://github.github.io/spec-kit/reference/agentic-sdd.html>

Extracted principles:

- Process: **constitution → specify → clarify → plan → checklist → tasks →
  analyze → implement → converge**.
- The constitution is the guiding principles every later phase is evaluated
  against.
- Specify the **what/why**, not the tech stack; keep implementation detail for
  the plan.
- Clarify ambiguous requirements before planning.
- The plan produces design artifacts from the spec.
- The checklist is “unit tests for requirements”, reviewer-owned; implementation
  must not self-approve it.
- Tasks are dependency-ordered, phased (setup → foundational → user stories →
  polish), with parallel markers and tests inside each story.
- Analyze is read-only cross-artifact consistency checking.
- Converge is append-only and reports `Converged` only when gaps are gone.

## 4. How research shaped this package

| Research principle | Artifact |
|---|---|
| Constitution before spec | `00-CONSTITUTION.md` |
| Specify what/why, not stack | `01-SPEC.md` |
| Clarify before plan | resolved decisions + open questions in `01-SPEC.md` |
| Plan technical detail | `03-ARCHITECTURE.md` |
| Dependency-ordered tasks | `04-TASKS.md` |
| Requirements-quality checklist | `05-TEST-PLAN.md` §10 |
| Read-only analysis / convergence | `05-TEST-PLAN.md` §11 |
| Measurable goal + check + bound | `GOAL-PROMPT.md` |
| Tell what cannot be seen | current state, commands, constraints |
| Give a check to run | exact command block |
| Evidence over assertion | `EVIDENCE.md` + screenshots |
| Deterministic vs non-deterministic | test gates vs model review |
| Few-shot output format | evidence/status templates |
| Context first, task last | prompt section order |
| Say “be ambitious” | scope statement in the goal prompt |

## 5. Open research questions

1. Does Monaco add acceptable startup cost on the target hardware? Measure
   before Phase 2 is declared done.
2. Does the five-region shell remain usable at 768 px, or does the agent panel
   need to become a bottom sheet? Decide after screenshots.
3. Is a command palette worth the surface area for a single-user local tool?
   Default: yes, for keyboard and agent parity.
4. Should the status bar show token/cost usage? Default: yes, behind a tooltip.
5. Should the verifier time budget be 15 minutes or a per-test budget? Measure
   after Phase 3; keep 15 minutes until data says otherwise.

## 6. Citation index

- Anthropic Claude Code best practices:
  <https://www.anthropic.com/engineering/claude-code-best-practices>
- Anthropic `/goal`:
  <https://code.claude.com/docs/en/goal>
- OpenAI prompt engineering:
  <https://platform.openai.com/docs/guides/prompt-engineering>
- Google prompt design strategies:
  <https://ai.google.dev/gemini-api/docs/prompting-strategies>
- GitHub Spec Kit:
  <https://github.com/github/spec-kit>
- Spec Kit agentic SDD:
  <https://github.github.io/spec-kit/reference/agentic-sdd.html>
- UI UX Pro Max:
  <https://github.com/nextlevelbuilder/ui-ux-pro-max-skill>
- UX/UI Agent Skills:
  <https://github.com/plugin87/ux-ui-agent-skills>
- Hallmark:
  <https://github.com/Nutlope/hallmark>
- VS Code:
  <https://github.com/microsoft/vscode>
- Cline:
  <https://github.com/cline/cline>
- Judge0 IDE:
  <https://github.com/judge0/ide>
- Monaco:
  <https://github.com/microsoft/monaco-editor>
- code-server:
  <https://github.com/coder/code-server>
