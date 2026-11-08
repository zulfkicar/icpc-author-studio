"""Middleware for the authoring agent.

- PinnedContextMiddleware injects durable working memory into every model call
  without mutating the transcript.
- ToolErrorMiddleware converts tool exceptions into ToolMessages so the model
  can recover and history stays valid. It must not swallow LangGraph interrupts.
"""
from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest
from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.errors import GraphBubbleUp

import workspace
from agent_state import AuthorState, MAX_CONTEXT_FILES

MODE_INSTRUCTIONS = {
    "author": (
        "MODE: author. Move the package forward through the authoring pipeline. "
        "Write files, build tests, measure limits and verify. Keep the todo list current."
    ),
    "debug": (
        "MODE: debug. Focus on the current failure. Read the exact error and evidence, "
        "make the smallest concrete fix, rerun the failing check, and avoid unrelated edits."
    ),
    "review": (
        "MODE: review. Act as a reviewer. Inspect the statement, validator, reference, "
        "tests and evidence for ambiguity and gaps. Do not edit or export unless asked."
    ),
}


def _pinned_context(state: dict) -> str:
    slug = state.get("slug") or ""
    chat_id = state.get("chat_id") or ""
    lines = []
    if slug:
        lines.append(agent_state_note(slug))
    brief = state.get("brief") or ""
    if brief:
        lines.extend(["", "WORKING BRIEF", brief])
    requirements = state.get("requirements") or []
    if requirements:
        lines.extend(["", "REQUIREMENTS", *[f"- {item}" for item in requirements]])
    decisions = state.get("decisions") or []
    if decisions:
        lines.append("")
        lines.append("DECISIONS")
        for item in decisions:
            lines.append(f"- Q: {item.get('question')}\n  A: {item.get('answer')}")
            if item.get("rationale"):
                lines.append(f"  Why: {item['rationale']}")
    questions = state.get("open_questions") or []
    if questions:
        lines.extend(["", "OPEN QUESTIONS", *[f"- {item}" for item in questions]])
    focus = state.get("focus") or ""
    if focus:
        lines.extend(["", f"CURRENT FOCUS: {focus}"])
    mode = state.get("mode") or "author"
    lines.extend(["", MODE_INSTRUCTIONS.get(mode, MODE_INSTRUCTIONS["author"])])
    todos = state.get("todos") or []
    if todos:
        lines.append("")
        lines.append("CURRENT TODO LIST")
        for item in todos:
            lines.append(f"- [{item.get('status', 'pending')}] {item.get('content', '')}")
    selected = state.get("selected_context") or []
    if selected:
        lines.append("")
        lines.append("SELECTED CONTEXT")
        total = 0
        for path in selected[:MAX_CONTEXT_FILES]:
            try:
                text = workspace.read_text(slug, path).get("content") or ""
            except Exception:
                continue
            snippet = text[:1500]
            total += len(snippet)
            lines.append(f"\n--- {path} ---\n{snippet}")
            if total >= 8000:
                lines.append("\n[selected context truncated]")
                break
    return "\n".join(lines)


def agent_state_note(slug: str) -> str:
    """Local import avoids a module cycle with graph_agent/agent."""
    import agent

    try:
        return agent._state_note(slug)
    except Exception:
        return f"WORKSPACE: {slug}"


class PinnedContextMiddleware(AgentMiddleware):
    """Add durable working memory to the system message on every model call."""

    state_schema = AuthorState

    def _system(self, request: ModelRequest) -> SystemMessage:
        base = request.system_message.content if request.system_message else ""
        dynamic = _pinned_context(request.state or {})
        content = (str(base) + "\n\n" + dynamic).strip()
        return SystemMessage(content=content)

    def wrap_model_call(self, request, handler):
        return handler(request.override(system_message=self._system(request)))

    async def awrap_model_call(self, request, handler):
        return await handler(request.override(system_message=self._system(request)))


class ToolErrorMiddleware(AgentMiddleware):
    """Convert tool failures into ToolMessages, preserving interrupts."""

    state_schema = AuthorState

    @staticmethod
    def _error_message(request, exc: Exception) -> ToolMessage:
        call = getattr(request, "tool_call", {}) or {}
        return ToolMessage(
            content=f"Tool error: {type(exc).__name__}: {exc}",
            name=call.get("name") or "tool",
            tool_call_id=call.get("id") or "",
            status="error",
        )

    def wrap_tool_call(self, request, handler):
        try:
            return handler(request)
        except GraphBubbleUp:
            raise
        except Exception as exc:  # noqa: BLE001
            return self._error_message(request, exc)

    async def awrap_tool_call(self, request, handler):
        try:
            return await handler(request)
        except GraphBubbleUp:
            raise
        except Exception as exc:  # noqa: BLE001
            return self._error_message(request, exc)
