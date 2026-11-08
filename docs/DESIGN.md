# ICPC Author Agent — Design

Status: design specification
Companion to [`MASTER-PLAN.md`](MASTER-PLAN.md)

## 1. Design thesis

This is an authoring workbench, not a chat toy.

The user must be able to answer, at any moment:

- What is the agent doing?
- Why is it doing that?
- What did it change?
- What did it run?
- What did it prove?
- What is still uncertain?
- What can I do next?

The interface is organized around **evidence**, **progress** and **control**, not around message bubbles alone.

## 2. Principles

1. **Nothing important happens only in chat.**
2. **Evidence sits next to the claim.**
3. **Summary first; detail on demand; raw on request.**
4. **The user can pause, cancel, retry, undo and restore.**
5. **Approvals show exact effects.**
6. **Clarifications are questions, not hidden assumptions.**
7. **No hidden terminal windows.**
8. **No color-only status.**
9. **Keyboard and screen-reader accessible.**
10. **Never steal scroll position.**

## 3. Information architecture

```text
Top bar: workspace, mode, connection, settings
Left:  Chats / Files / Changes
Center: conversation + live activity rail
Right: Plan / Run / Verify / Review / History
Panel: Output / Tests / Problem / Raw
```

### 3.1 Left sidebar

- Chats: search, rename, delete, tabs for open chats.
- Files: expandable tree, create/rename/delete, change markers.
- Changes: reviewable changes, diffs, revert, hunk review.

### 3.2 Center

- Conversation with compact event cards.
- Intent line before tool batches.
- Inline approval and clarification cards.
- Stage rail pinned above the transcript.
- Follow-live control.

### 3.3 Right inspector

- **Plan:** stage checklist, todos, decisions, open questions.
- **Run:** editor, test cases, custom input, output.
- **Verify:** checklist, checker matrix, interactive transcript, report.
- **Review:** findings by reviewer/verifier-auditor.
- **History:** checkpoints, snapshots, restore.

### 3.4 Panel

- Output/log stream.
- Test results.
- Problem/PDF.
- Raw JSON.
- Searchable, virtualized, downloadable.

## 4. Visual language

### 4.1 Density

Dense but calm. Technical users benefit from high information density, but hierarchy must make the current action obvious.

### 4.2 Type

- UI: variable sans-serif with tabular numerals for metrics.
- Code: monospace with clear `0/O` and `1/l/I`.
- Sizes: 11–13px for dense UI, 14–16px for primary reading, 12px code.
- Numeric columns use tabular numerals.

### 4.3 Color

- Neutral background hierarchy.
- One accent for current action.
- Green: passed/accepted.
- Amber: warning/pending/clarification.
- Red: failed/rejected.
- Blue: information/links.
- Never rely on color alone; pair with icon and text.

### 4.4 Spacing and shape

- 4px spacing scale.
- 6–8px card radius.
- Borders over heavy shadows.
- Strong focus ring.
- Avoid nested-card visual noise.

### 4.5 Motion

- 120–180ms transitions.
- Motion explains change (expand, enter, status).
- Respect `prefers-reduced-motion`.

## 5. Core components

### 5.1 Stage rail

Stages:

```text
Plan -> Generate -> Validate -> Build answers -> Measure -> Verify -> Review -> Export
```

Each stage shows:

- status icon + text,
- elapsed time,
- one-line evidence,
- expandable details,
- failure action.

States: queued, running, passed, failed, cancelled, stale, blocked on clarification.

### 5.2 Tool card

Fields:

- tool name and icon,
- intent (why),
- arguments summary,
- status and duration,
- readable result,
- raw result toggle,
- artifact links.

Failure card includes exact error, affected file/line and recovery actions.

### 5.3 Command output

- Command line.
- Exit code.
- Duration.
- Parsed compiler diagnostics: file, line, column, severity, message.
- stdout/stderr split.
- Full-log link.
- ANSI-safe rendering.

### 5.4 Test card

- Test name and group.
- Input preview.
- Expected output.
- Actual output.
- Verdict: pass/fail/compile error/timeout/runtime error.
- Time and memory.
- Rerun single/all.
- Filter failures.

### 5.5 Verifier checklist

- Requirement.
- Status.
- Evidence summary.
- Link to artifact.
- Stale marker.
- “Fix with agent” action.

### 5.6 Checker self-test matrix

- Case name.
- Expected verdict.
- Actual verdict.
- Checker message.
- Reference/alternative/wrong/malformed category.
- Pass/fail.

### 5.7 Interactive transcript

- Direction: judge → solution / solution → judge.
- Query index.
- Timestamp.
- Message.
- Protocol error marker.
- Query-limit counter.
- Search/filter.

### 5.8 Approval card

- Action and risk.
- Exact command or diff.
- Affected files.
- Evidence.
- Approve / Reject / Edit.
- Keyboard actions.
- Pending queue and audit.

### 5.9 Clarification card

- Question(s).
- Why it matters.
- Options with descriptions.
- Recommended default.
- Free-text answer.
- “Use recommended defaults”.
- Blocking state.
- Recorded decision link.

### 5.10 Error state

- Plain-language summary.
- Exact failing operation.
- Evidence and reproduction.
- Retry / Open log / Ask agent to fix / Revert.
- Distinguish agent error, package error, environment error and provider error.

### 5.11 Empty/loading states

- Explain what will happen.
- Skeleton for short waits; explicit progress for long jobs.
- Never show a blank pane during work.

## 6. Follow-along behavior

- Follow live output by default.
- Pause when the user scrolls up.
- Show “Jump to live”.
- Do not move the viewport while the user is reading.
- Collapse successful stages; expand failures.
- Announce major status changes via ARIA live regions.
- Offer a compact “activity only” view for long runs.

## 7. Readable output contract

Every event has:

```json
{
  "runId": "string",
  "seq": 1,
  "at": "ISO-8601",
  "stage": "plan|generate|validate|answers|measure|verify|review|export",
  "tool": "string",
  "intent": "string",
  "status": "queued|running|passed|failed|cancelled|stale|blocked",
  "durationMs": 0,
  "summary": "string",
  "detail": "string",
  "artifacts": [],
  "raw": "string"
}
```

Rules:

- Every tool call emits start and end.
- Every end has status and duration.
- Every failure has a recovery action.
- Raw output is always available.
- Truncation is explicit.
- Links to full artifacts are stable.
- ANSI/control characters are escaped.
- Untrusted content is rendered as data, never executed.

## 8. Keyboard model

- `Ctrl/Cmd+Enter`: send.
- `Esc`: close dialog / cancel current modal.
- `Ctrl/Cmd+K`: command palette.
- `Ctrl/Cmd+S`: save file.
- `Ctrl/Cmd+Shift+F`: search workspace.
- `Alt+Up/Down`: previous/next failure.
- `Ctrl/Cmd+Shift+P`: pause/resume follow.
- `Tab` order follows visual order.
- Focus is visible and not obscured.

## 9. Accessibility

Target WCAG 2.2 AA:

- status messages announced,
- keyboard operable,
- focus visible/not obscured,
- target size at least 24×24,
- reflow at 320px,
- no color-only status,
- pause/stop/hide for streaming,
- reduced motion,
- contrast,
- labels and instructions.

Test with keyboard-only navigation and a screen reader; do not rely only on automated scans.

## 10. Performance

- Virtualize long logs and test lists.
- Batch stream updates.
- Use sequence numbers to deduplicate.
- Reconnect and replay from the last sequence.
- Avoid layout thrash during streaming.
- Keep typing latency low; never block the editor on agent events.
- Target 60fps for interactions; use skeletons for long work.

## 11. Trust and security

- Approval shows exact command/diff.
- Clarification is separate from approval.
- Untrusted tool/file content is marked as data.
- Secrets are redacted in logs and UI.
- Executor has no provider key and no external network.
- MCP tools require explicit consent and roots.
- No hidden agent action.
- Every destructive action has a clear recovery path.

## 12. References

- Jakob Nielsen, *10 Usability Heuristics for User Interface Design* — visibility, control, consistency, error prevention, recognition, minimalism, recovery.
- VS Code UX Guidelines — activity bar, sidebar, editor, panel, status bar, views.
- GitHub Primer — tokens, components, accessibility.
- *Refactoring UI* — hierarchy, spacing, color, depth.
- W3C WCAG 2.2 — accessibility success criteria.
- OWASP Top 10 for LLM Applications — prompt injection, excessive agency, unbounded consumption.
- LeetCode / HackerRank — test-case tabs, run/submit, expected vs actual.
- Codeforces Polygon / DOMjudge / Kattis package format — verification, checker/interactor evidence, test groups.

## 13. Anti-patterns

- Chat-only status.
- Raw JSON by default.
- Hidden terminal.
- Modal spam.
- Auto-scroll hijack.
- Color-only pass/fail.
- Approval without exact effect.
- Clarification without context.
- “Verified” without artifacts.
- Infinite retry loops.
- Silent assumption of semantics.

## 14. Acceptance checklist

- [ ] Every async action has queued/running/passed/failed/cancelled/stale state.
- [ ] Every tool call has intent, arguments, duration and readable result.
- [ ] Every output has readable and raw views.
- [ ] Every approval shows exact effect.
- [ ] Every clarification shows impact, options and default.
- [ ] Every failure has recovery.
- [ ] Follow mode can be paused and resumed.
- [ ] Keyboard-only flow works.
- [ ] Screen reader announces status changes.
- [ ] 320px reflow works.
- [ ] No color-only status.
- [ ] Reduced motion respected.
- [ ] Logs are virtualized and bounded.
- [ ] Reconnect/replay does not duplicate events.
- [ ] Secrets never appear in UI/logs.
- [ ] Agent cannot claim verified without evidence.
