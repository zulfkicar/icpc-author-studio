# Incident: agent turn rejected with 1.12M input tokens

Date: 2026-11-09

## Symptom

An agent turn failed with:

```text
OpenAIInvalidRequestError: Error code: 400 - provider rejected the request:
Input too long: model limit 1048576 tokens, requested 1120042 tokens
```

The visible chat appeared not to save the turn.

## Root cause

The `new-idea` conversation checkpoint contained a 1.3 MB `ToolMessage` from
reading `data/secret/09_alternating_tiny_huge_max_n.in`. The approximate token
counter reported ~341k tokens, so `SummarizationMiddleware` (trigger 500k) did
not fire. The provider's tokenizer counted that dense numeric content at
~1.12M tokens, above the 1,048,576 model window.

Secondary causes:

- `read_file` allowed `data/secret/**` and `**/*.ans`, contrary to the system
  prompt and the reviewer/MCP guards.
- `read_file` returned unlimited file content, so one large file could defeat
  the context budget.
- A failed turn did not save the checkpoint state or a visible error message;
  only the toast reported the failure.

This is not a Judge0 database failure. Judge0's PostgreSQL stores Judge0
submissions; authored problems, chats and checkpoints live under
`workspaces/<slug>/.agent/` as JSON and SQLite. A Judge0 database reset would
not affect this path.

## Fix

- `agent_middleware.ContextBudgetMiddleware` now:
  - estimates tokens conservatively (`max(approximate, chars/2)`);
  - truncates individual tool/message content (`12k` chars for tool results,
    `60k` for other messages) with an explicit truncation marker;
  - drops the oldest complete messages until the configured context budget
    (`contextBudgetTokens`, default 500k) is met;
  - keeps the current user message and avoids orphaned tool messages;
  - then clamps `max_tokens` against the provider window.
- `SummarizationMiddleware` now runs before the hard guard, so normal long
  histories still get a semantic summary; the hard guard catches dense tool
  output that the approximate counter undercounts.
- `read_file` rejects `data/secret/**` and `**/*.ans` in both the LangChain tool
  and `agent._dispatch`; large non-secret reads are capped at 200k chars with a
  `truncated` flag and a line-range hint.
- `search_workspace` skips secret tests and `.ans` files.
- A failed/cancelled turn now saves the checkpoint state plus a clearly labelled
  assistant message (and any partial streamed output) before re-raising.
- The UI refreshes the conversation after a failed job, so the saved error is
  visible instead of only appearing as a toast.

## Verification

Exact failed checkpoint:

```text
messagesBefore=71, estimateBefore=677334
messagesAfter=71, estimateAfter=31144
maxMessageChars=10864
```

Synthetic and guard tests:

```text
python qa/test_context_budget.py
CONTEXT BUDGET TESTS PASSED

python qa/test_context_500k.py
messages=4 chars=1656
500K CONTEXT TEST PASSED
```

Real provider turn after the fix:

```text
model=configured-model
job=4b492b206c0a state=done
result.text=OK
usage={input_tokens:4341, output_tokens:3}
conversation messages=2 (user + assistant OK)
```

## Reset policy

- No database or workspace reset is required for this incident.
- A fresh app image/restart is sufficient; the fix is in the image.
- If a full reset is ever wanted:
  - Back up `workspaces/` and `.author-agent/` first.
  - Judge0 `down -v` only discards Judge0 submission history (safe for authored
    data, but still confirm).
  - Deleting `workspaces/` deletes authored problems and checkpoints; require
    explicit confirmation.
  - Do not delete `.author-agent/config.json` unless the provider key is being
    rotated deliberately.

## Judge0 IDE decision

The workbench uses **Judge0 CE as a quick-run backend** embedded natively in
the editor's run panel (backend selector, stdin, output tabs, history). It does
not embed the separate `judge0/ide` frontend:

- `judge0/ide` has its own Monaco instance, file model and settings; it cannot
  see this workbench's workspace or agent context.
- The design deliberately rejected iframing it as the primary experience to
  avoid two editors, two file models and a CSP/frame bridge.
- The compose stack includes Judge0 server/worker/PostgreSQL/Redis, not the
  `judge0/ide` frontend.

If the actual Judge0 IDE is wanted, add it as an optional **separate** service
and open it in a new tab; do not replace the native editor. That is a product
decision, not a bug fix.
