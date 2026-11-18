# Release 1 · Keep my work

18 November 2026

## Implemented

- Typed messages, inline decisions, retries, and example insertion use separate
  paths in Studio. A choice gets the receipt for the actual response and keeps
  the composition text and caret.
- Local browser storage holds scoped drafts and the last working location.
  Its durable file records include the base hash and edit generation.
  Recovery returns an unsaved buffer and compares its base to saved bytes.
  The conflict view shows the saved copy and lets the setter copy the draft,
  open the saved version separately or explicitly rebase and save.
- The browser retains unsent and uncertain requests in its outbox. A local
  backend receipt lookup finds accepted requests. A durable reservation
  gives a first chat request one run ID across retries or server restart.
  Restoring a browser view checks receipts without replaying requests.
- Name is available before the first message and via F2 outside the editor
  and input fields. Package setup preserves an existing title by default.
  Matching existing titles is explicit. New packages follow the problem
  title. A versioned preview shows affected title files, statement support,
  and ZIP name. If another operation changes the title or package, the
  preview can refresh while retaining the text.
- Package setup continues the requested artifact copy. Starting chat from
  a manual package offers it as a link and retains the package separately
  if the setter leaves the dialog.

The draft store is browser-local and subject to the browser's quota and
retention. Storage refusal keeps in-page text usable and raises a persistent
warning. Local restoration never saves project files. Saved chat records
and package approvals remain on the host.

## Observed in the running app

| Scenario | Result |
| --- | --- |
| Name a new problem and reload | F2 opened naming. The title and unsent idea text reappeared in the draft. |
| Answer an inline decision while composing | The Half-open choice produced **Choice saved**. An unrelated unsent note and its caret at position zero were retained. |
| Link during artifact copy | The existing package kept its title. The Copy artifact dialog reopened with the original editorial and destination. |
| Reload the editor | Editor layout, selected Python file, three tabs, unsaved source text and the chat draft recovered. A later reload restored the previous Run drawer with output \`16\`. |
| File changed outside Studio | The recovered draft showed a conflict, displayed the outside edit, and remained unsaved until an explicit review and Save. Running the saved file with \`7 9\` returned \`16\`. |
| Separate and matched titles | A conversation rename kept the imported title. Choosing Match the problem title displayed the exact edits and proposed ZIP filename before changing the package. |
| Rename after approval | The old approval could not release the renamed snapshot. Fresh verification and human review produced \`canal-relay-final-booking-domjudge.zip\`. Its manifest, escaped statement title, CRCs and secret expected answer were checked. |
| Concurrent rename | A second tab saved its own title. The first tab got a conflict and refreshed its preview with both current names and its originally typed title. Escape returned focus to Rename. [Capture](evidence/release-1-rename-conflict.jpg). |
| Manual workspace to chat | The new conversation offered the exact package used for manual work. Closing the dialog preserved the package. Switching back restored the original chat draft and caret. |
| Lost first reply | A test server committed the first chat and then returned a synthetic 503 for both its response and the first receipt read. The browser retained the uncertain request. Reload found one conversation with its question and cleared the outbox. |

This walkthrough used the in-app desktop browser, a scripted model, synthetic
problems, and the real local package backend. The storage test separately
simulated quota refusal. Cross-browser, long-session performance, and narrow
viewport qualification remain planned. The two active app instances were
updated using their original roots. All nine main conversations and five
workspaces were present after restart. The already approved Canal Lock ZIP
downloaded with its original hash.

## Regression entry points

All 317 engine contract tests passed. The final focused run passed 35 tests,
including the database reopen check for a first-message receipt. The browser
storage, state-machine and classic UI checks also passed.

- [Release 1 HTTP tests](../../../qa/engine_contracts/test_studio_release_one.py)
- [Browser storage unit tests](../../../qa/test_studio_recovery.mjs)
- [Existing package workflow tests](../../../qa/engine_contracts/test_studio_routes.py)
