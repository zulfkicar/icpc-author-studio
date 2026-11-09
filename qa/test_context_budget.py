"""Context-budget and tool-read guards.

The production failure: a 1.3 MB secret input was read into a ToolMessage and
the provider counted ~1.12M tokens while the approximate counter said ~341k.
These tests pin the conservative estimate, hard truncation and read guards.
"""
from __future__ import annotations

import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage  # noqa: E402

import agent  # noqa: E402
import agent_middleware  # noqa: E402
import workspace  # noqa: E402


class FakeRequest:
    def __init__(self, messages, system_message=None):
        self.messages = messages
        self.system_message = system_message


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS {name}")
        return
    print(f"  FAIL {name} {detail}")
    raise AssertionError(name)


def main() -> int:
    big = "1 1000000000 " * 100_000
    messages = [
        HumanMessage(content="start"),
        AIMessage(content="working"),
        AIMessage(content="reading", tool_calls=[{"name": "read_file", "args": {}, "id": "call-1"}]),
        ToolMessage(content=big, tool_call_id="call-1", name="read_file"),
        HumanMessage(content="what happened?"),
    ]
    middleware = agent_middleware.ContextBudgetMiddleware(
        model_window_tokens=1_048_576,
        max_output_tokens=393_216,
        context_budget_tokens=500_000,
    )
    check("conservative estimate sees dense numeric data", middleware._estimate(messages) > 500_000, middleware._estimate(messages))
    check(
        "summarization trigger sees dense numeric data",
        agent_middleware.conservative_token_count(messages) > 500_000,
        agent_middleware.conservative_token_count(messages),
    )
    system, trimmed = middleware._trimmed(FakeRequest(messages, SystemMessage(content="system")))
    check("trimmed estimate fits the context budget", middleware._estimate(([system] if system else []) + trimmed) <= 500_000)
    tools = [item for item in trimmed if isinstance(item, ToolMessage)]
    check("tool output is bounded", all(len(item.content) < 15_000 for item in tools), [len(item.content) for item in tools])
    check("history does not start with an orphan tool message", not isinstance(trimmed[0], ToolMessage), type(trimmed[0]).__name__)
    check("current user message is preserved", isinstance(trimmed[-1], HumanMessage))

    created = workspace.create("QA Context Budget", "context budget")
    slug = created["slug"]
    try:
        workspace.write_text(slug, "data/secret/01.in", "1 2\n", source="test")
        workspace.write_text(slug, "data/sample/01.in", "1 2\n", source="test")
        workspace.write_text(slug, "big.txt", "x" * 300_000, source="test")
        try:
            agent._dispatch(slug, "read_file", {"path": "data/secret/01.in"}, lambda *_: None)
        except ValueError:
            check("secret input read is blocked", True)
        else:
            check("secret input read is blocked", False)
        try:
            agent._dispatch(slug, "read_file", {"path": "data/sample/01.in"}, lambda *_: None)
            check("sample input read remains allowed", True)
        except Exception as exc:
            check("sample input read remains allowed", False, str(exc))
        result = agent._dispatch(slug, "read_file", {"path": "big.txt"}, lambda *_: None)
        check("large non-secret read is truncated", result.get("truncated") is True, result.get("totalChars"))
        check("large non-secret read stays bounded", len(result.get("content") or "") <= 200_100, len(result.get("content") or ""))
        search = agent._dispatch(slug, "search_workspace", {"query": "1 2"}, lambda *_: None)
        check("search does not expose secret paths", all("data/secret" not in item["path"] for item in search.get("matches", [])), search)
        pinned = agent_middleware._pinned_context({
            "slug": slug,
            "mode": "author",
            "selected_context": ["data/secret/01.in", "data/sample/01.in"],
        })
        check(
            "pinned context excludes secret tests",
            "data/secret/01.in" not in pinned and "data/sample/01.in" in pinned,
            pinned,
        )
    finally:
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)
    print("CONTEXT BUDGET TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
