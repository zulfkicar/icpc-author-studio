# Manual screen-reader checklist

Automated gates already cover axe (0 serious/critical), the AX tree (no unnamed
controls), tab order, dialog labels and live regions. A human screen-reader pass
is still required; this file is the sign-off record.

Environment:

- OS:
- Browser:
- Screen reader + version:
- Date:
- Tester:

## Shell

- [ ] The skip links are the first Tab stops and move focus to the editor and
      composer.
- [ ] The activity rail announces each section and the current section.
- [ ] The navigator announces its name and the active side tab.
- [ ] The editor group announces its name; the tab list announces the active
      editor view and file tab.
- [ ] The agent panel announces its name; the transcript is a named log.
- [ ] The status bar is reachable and its connection/backend/verify text is
      announced as text, not colour.

## Dialogs

- [ ] Every dialog announces its title and description on open.
- [ ] Inline validation is announced as an alert.
- [ ] Cancel, Escape and backdrop close the dialog.
- [ ] Focus returns to the invoking control.

## Editor

- [ ] The Monaco editor announces its label, line/column and the current file.
- [ ] Opening a second file announces the new tab and the active tab.
- [ ] A dirty tab announces unsaved changes; close asks for confirmation.
- [ ] The textarea fallback (`?editor=textarea`) is usable and labelled.

## Evidence and review

- [ ] The report tab announces its status, stale banner, limits and checks.
- [ ] A changed-file button opens the diff tab and focus moves there.
- [ ] The review queue announces the unreviewed count.
- [ ] Export announces why it is disabled, with text, not only colour.

## Run panel

- [ ] The backend selector is labelled and its options are announced.
- [ ] “Quick run is not verification” is announced next to the selector.
- [ ] stdin/stdout/stderr/compile/result tabs are announced as tabs.
- [ ] Run status, time and memory are announced as text.

## Result

- [ ] Pass
- [ ] Fail (list findings below)

Findings:

```text
```
