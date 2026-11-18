# Release 2 · Make it easy to work

18 November 2026

Author Studio now has searchable commands, recent problems and files. The
workspace tree groups statements, editorial and proof, solutions, validators,
sample cases, secret cases, and drafts. Tabs support preview, pinning, keyboard
selection, closing, and reopening. Local links refer to saved files with an
opaque token, or to an artifact with its immutable ID. Browser Back can revisit
linked files. A missing target leaves its problem open.

| Keystroke | Action |
| --- | --- |
| Alt+K | Open Commands |
| Alt+P | Find a recent problem or start a new one |
| Alt+O | Find a file by name or path |
| Alt+R | Open Run with a source and input to confirm |
| Alt+Shift+O | Reopen the last closed tab |
| F2 | Rename the problem when outside an editor or text field |
| Ctrl/Cmd+S | Save the active editable file |
| Left/Right, Home/End | Select a tab when the tab strip has focus |
| Delete | Close the focused tab |
| Escape | Close search, appearance or focused output and return focus |

All core actions also have pointer controls. The browser can reserve some
keystrokes. The Studio shortcuts preserve Monaco's Find widget commands when
it holds focus. At narrow widths, Open file temporarily supplies the tree's
navigation and Commands supplies secondary operations. The output pane takes
the working width and returns focus on close. Appearance controls reading and
code size independently, with system, light and dark options.

Chat keeps stable transcript rows during updates, groups routine artifact
messages, and offers Jump to latest when the author is reading earlier work.
Provider settings opens the existing workbench dialog, with the unsent draft
available on return. A generated statement PDF can be opened in full. The
inline first page uses the local Poppler converter. If the converter is
unavailable, the tab provides the full PDF link and explains the fallback.

## Browser verification

An isolated loopback instance used scripted chat, two similar problem titles,
a 100-message fixture, and a real local sum package. The authoring and
download tests used the normal UI routes and the saved snapshot checks.

| Scenario | Observed result |
| --- | --- |
| Keyboard navigation | Alt+P found both full titles with distinct endings. Alt+K opened Commands, Alt+O found files by path, Escape closed the picker and returned focus, and Alt+R opened Run from Monaco. |
| Tab behavior | Opening a source produced a preview. Editing pinned it. Two \`main.py\` files displayed their differing folders. Delete focused the adjacent tab, and Alt+Shift+O reopened the closed one. Reload restored the selected dirty file. |
| Grouped files | Searching \`01.in\` showed Sample cases and Secret cases as separate results. |
| Wide layout | Together showed the split at 1280px. ArrowLeft resized it, and Home returned it to 52%. |
| Narrow layout | At 320px and 768px the tree took 0px and the document had no horizontal overflow. At 320px the editor and output each used 319px. Output covered the editor, with keyboard focus restored to the editor on close. [320px workspace](evidence/release-2-workspace-320.jpg). |
| Theme and reading | At 390px, changing to light theme and increasing code size yielded 16px code with 18px reading size. The Markdown table rendered in Preview. |
| Statement | The generated first page loaded as a 990×1400 PNG at 390px. The same tab exposed the complete local PDF. [390px statement](evidence/release-2-statement-390.jpg). |
| Continuity and links | Browser Back returned from Markdown to the PDF. The copied artifact link exposed an ID, with no editorial path in its fragment. An invalid opaque file token fell back to the same problem. |
| Long transcript | A decision added grouped artifacts and results to the 102-row conversation. The reading position remained near the earlier turn. Jump to latest scrolled to the end and returned focus to the composer. |
| Settings and drafts | Opening provider settings and returning with Browser Back restored the unsent text. Selecting a decision also retained the unsent draft. |
| Focus during restoration | Skip to conversation kept Chat active when refresh completed, kept the same problem address, and focused the composer. Escape returned focus from Appearance to its trigger. |
| Full package flow | Saved a keyboard-edited reference, ran \`7 9\` and saw \`16\`, built expected answers, verified the package, reviewed the changes, and generated a ZIP from narrow views. The archive's CRCs, reference bytes, generated PDF and answers \`5\` and \`9\` passed inspection. |

These checks cover the in-app desktop browser and its narrow viewports in light
and dark. Browser zoom and assistive-technology qualification remain separate
checks. Regression tests cover [PDF route behavior](../../../qa/engine_contracts/test_studio_release_two.py)
and the existing draft, naming, and package contracts.

The engine contract suite passed 318 tests during implementation. The final
focused run passed 19 tests, including the scoped PDF and first-page response.
The classic UI, state-machine and draft storage checks passed. After the
local app refresh, all nine main conversations and five workspaces were
present. The approved Canal Lock ZIP downloaded with its original SHA-256.
