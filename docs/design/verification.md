# Verification: the proof desk

For the current Studio, see [Release 4 verification](product-experience/RELEASE-4.md).

Date: 2026-11-17. Environment: Windows 11, local `server.py` on
`http://127.0.0.1:8787`, demo engine model + simulated worker, disposable
application roots. Visual checks use headless Chrome via CDP because the in-app
browser relay's extension was offline. This is implementation inspection, not
user testing or accessibility conformance.

## Visual and composition checks

| Check | Environment / viewport / state | Observed result | Evidence | Remaining issue |
|---|---|---|---|---|
| Workbench first screen | 1600×1000, Claim or Concede, no desk | Warm paper, serif problem title, ruled pipeline, clear red "Authoring desk"; no horizontal overflow | `docs/design/captures/baseline-workbench-1600.png` | Legacy Classic agent still occupies the right rail when desk closed |
| Masthead at narrow width | 390×900, desk closed, file open | Two-row masthead with no overlap; problem selector fits; secondary actions scroll horizontally; status stays in the status bar | `desk-code-390.png` | Some topbar actions need horizontal scrolling |
| Docked authoring desk | 1600×1000, existing conversation | Desk occupies 620px right column, replaces Classic agent rail; plan and editor remain visible; status "Ready for you" | `baseline-collaborate-1600.png` | At 1100–1280px the editor is narrow (331px at 1152), though readable |
| Docked desk at 1280 and below | 1152×900, existing conversation | 520px dock; masthead wraps to two rows; editor still readable; no horizontal overflow | `desk-dock-1152.png` | Editor is a secondary pane beside the desk |
| Overlay desk | 1024×900, empty desk | 560px full-height drawer over the editor; masthead actions remain visible on the left; no squeezed editor column | `desk-overlay-1024.png` | Drawer covers the right side of the masthead while open |
| Empty desk | 1600×1000, New conversation | "What problem are you setting?" with two example prompts; no setup ceremony; composer visible | `desk-empty-1600.png` | None observed |
| Open question | 1600×1000, endpoint card | Red margin rule, "OPEN QUESTION" stamp, prompt in plain reading order, two ruled choices, "Or answer…"; option prose no longer repeated | `desk-decision-1600.png` | No recommendation is shown because the fixture supplies none |
| File/editor | 1600×1000, Files, `problem_statement/problem.en.tex` | Paper shell, contents list, dark code slab with populated LaTeX, visible cursor/status | `desk-code-1600.png` | Monaco worker/run panel not separately captured; narrow file view has no tree |
| Narrow code view | 390×900, same file | Masthead wraps in two rows without overlap; editor, tabs and code stay inside the viewport; no horizontal overflow | `desk-code-390.png` | File tree is hidden below 760px by the existing app, not by this design |
| Diff | 1600×1000, Changes → NOTES.md deletion | Warm hunk/removal tints, dark-red diff text, readable on paper; legacy indigo/pink leftovers replaced | `desk-diff-1600.png` | Diff view is a plain text renderer, not Monaco; large diffs scroll |
| Settings dialog | 1600×1000, provider settings | Paper modal, serif title, legible fields, focusable controls, warm scrollbar | Local review | Long form scrolls. Narrow dialog capture remains open. |
| Dark ink variant | 1600×1000, theme toggle, desk | Warm dark paper, light coral accent, readable notices and status | `desk-dark-1600.png` | Dark-mode dialogs and file editor not individually captured |
| Narrow desk | 390×900, waiting/ready | Full-screen sheet, visible status, full-width composer, ledger on demand, no horizontal overflow | `baseline-collaborate-390.png` | The sheet intentionally covers the workbench masthead; close returns to it |

## Interaction and state checks

| Check | Method | Observed result | Evidence | Remaining issue |
|---|---|---|---|---|
| Empty → idea → question | Rendered UI, demo engine | Decision docket appears with a clear next action | `desk-decision-1600.png` | Answer click in the baseline script was not captured; browser suite covers the click |
| Refusal/question vs approval | `browser_repair.mjs`, `browser_decision.mjs` | 0 patches for refusal/question, positive approval publishes once | `qa/engine_contracts/browser_*.mjs` | Uses scripted model; not live-model behavior |
| Failed interpretation → reload → Retry | `browser_recovery.mjs` against `decision_browser_server.py --mode fail-once` | Failure card visible, solution unchanged, reload retains card, Retry publishes once and failure remains in history | `desk-recovery.png`, `browser-recovery` JSON (suite) | Controlled fixture, not a real provider outage |
| Received/applied visibility | Rendered send | Receipt shows "Working…", then "Applied · turn N" or received status; turn remains visible in ledger | CDP observation; browser suite | Applied text reflects the last author input, not per-message in transcript |
| Reload/resume | `browser_smoke.mjs`, `browser_repair.mjs` | Transcript, pending card, artifacts and status resume; no duplicate question | suite browser JSON | None observed |
| Export gate | Browser export button | Refused with no effects | suite browser assertions | V5 remains intentionally unsupported |

## Keyboard, focus and reduced motion

| Check | Method | Observed result | Evidence | Remaining issue |
|---|---|---|---|---|
| Tab focus visibility | CDP Tab from masthead and inside desk | `#workspace-select` focused with `outline: solid 2px`; desk summary focused with `solid 2px rgb(150,56,47)` | `verify-keyboard.mjs` run | Focus order through every dialog was not exhaustively traversed |
| Escape closes desk | CDP key event | `#collab-panel.hidden === true`; focus returns to the "Authoring desk" trigger; an open dialog takes precedence | `verify-keyboard.mjs` | Dialog focus order was not exhaustively traversed |
| Ctrl+Enter sends | Existing engine.js handler; composer hint | Handler present and keyboard hint visible | Source + rendered hint | Not re-scripted in this pass |
| Reduced motion | `prefers-reduced-motion: reduce` emulation | Desk animation computes to `none`; global durations collapse | `verify-design.mjs` | No motion audit beyond CSS |
| Touch targets | CSS + narrow capture | Primary buttons ≥ 30px; native details/selects; no hover-only actions | `baseline-collaborate-390.png` | Not a full touch-device test |

## Contrast

Computed with the project tokens (see `DESIGN.md`):

| Pair | Ratio | Requirement / result |
|---|---|---|
| Ink `#211d18` on paper `#f4efe6` | 14.63:1 | Normal text passes |
| Muted `#6b6257` on paper | 5.22:1 | Normal text passes |
| Faint `#6f6558` on paper | 4.98:1 | Normal text passes |
| Accent `#96382f` on paper | 6.32:1 | Normal text passes |
| Accent ink `#fffaf3` on accent | 6.96:1 | Button text passes |
| Success `#3f6b52` on surface | 5.76:1 | Text/status passes |
| Warning `#86611f` on surface | 5.29:1 | Text/status passes |
| Danger `#9d352c` on surface | 6.65:1 | Text/status passes |
| Control border `#968772` on surface | 3.30:1 | Non-text UI boundary passes 3:1 |
| Dark control border `#7c6c58` on `#1e1a15` | 3.41:1 | Non-text UI boundary passes 3:1 |
| Dark faint `#8e8270` on `#171410` | 4.88:1 | Normal text passes |
| Dark accent `#e08a7c` on `#171410` | 7.08:1 | Normal text passes |

## Automated and repository checks

| Check | Command | Result | Evidence | Remaining issue |
|---|---|---|---|---|
| UI contracts | `python qa/test_ui_contracts.py` | PASS (all printed checks) | command output | Structural checks, not visual/a11y conformance |
| Rendered smoke | `node qa/engine_contracts/browser_smoke.mjs` | PASS in documented suite | `evidence/20261117-190421/ui-collab.json` | Scripted engine; no live provider |
| Repair journey | `node qa/engine_contracts/browser_repair.mjs` | PASS in documented suite | `evidence/20261117-190421/ui-chat-repair.json` | Controlled hostile adapter |
| Decision/budget journey | `node qa/engine_contracts/browser_decision.mjs` | PASS in documented suite | `evidence/20261117-190421/ui-chat-decision.json` | Budget exhaustion fixture |
| Recovery journey | `node qa/engine_contracts/browser_recovery.mjs` | PASS in documented suite | `evidence/20261117-190421/ui-chat-recovery.json`; `desk-recovery.png` | Controlled fail-once adapter |
| Full engine suite | `python -m pytest qa/engine_contracts -q` | **286 passed** (661.73s) | `evidence/20261117-190421/pytest.txt` | Frontend change does not add backend coverage |
| Documented suite | `python scripts/run_v0_v3_suite.py` | Run `20261117-190421`, `ok: true`; engine suite, demo, identity, browser smoke, repair, decision and recovery all passed | `evidence/20261117-190421/run-v0-v3.json`, `LATEST.json` | Scripted engine and simulated worker only |

After the final responsive, scrollbar, diff-tint and Escape-focus pass,
`python qa/test_ui_contracts.py` and `node qa/engine_contracts/browser_smoke.mjs`
were re-run against the local demo server and passed. The 286-test suite stamp
above still applies because only CSS, markup and presentation-level JS changed
after it; no backend or contract behavior was modified.

## Unrun / limitations

- No screen-reader session, automated axe/Lighthouse audit, cross-browser run or
  real-device touch test. The browser relay extension was offline; headless Chrome
  and CDP were used instead.
- No author usability session or analytics. The direction is desk research and
  implementation inspection, not validated user need.
- Populated code and the text diff were captured at 1600 and 390 after the
  redesign; the Monaco worker, run/evidence panels and every dialog state were
  not individually captured. The legacy Classic agent was captured, not reworked.
- No live model/worker behavior was exercised; fake/simulated adapters are still
  labelled.
