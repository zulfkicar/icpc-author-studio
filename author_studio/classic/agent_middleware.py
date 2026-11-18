"""Middleware for the authoring agent.

- PinnedContextMiddleware injects durable working memory into every model call
  without mutating the transcript.
- ToolErrorMiddleware converts tool exceptions into ToolMessages so the model
  can recover and history stays valid. It must not swallow LangGraph interrupts.
"""
from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest
from langchain_core.exceptions import ModelRefusalError
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.errors import GraphBubbleUp

from author_studio.classic import prompt_loader
from author_studio.classic import skill_registry
from author_studio.packages import workspace
from author_studio.classic.agent_state import AuthorState, MAX_CONTEXT_FILES

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


def conservative_token_count(messages) -> int:
    """Token estimate that does not undercount dense numeric test data.

    ``count_tokens_approximately`` is a chars/4 style estimate. A 1.3 MB file
    of space-separated integers can be ~1.1M provider tokens while that counter
    reports ~341k, so a 500k summarization trigger never fires. chars/2 is
    deliberately conservative for normal prose and safely over-counts dense
    numeric data.
    """
    materialized = list(messages or [])
    try:
        approximate = int(count_tokens_approximately(materialized))
    except Exception:
        approximate = 0
    chars = sum(len(str(getattr(message, "content", ""))) for message in materialized)
    return max(approximate, chars // 2)


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
    lines.extend(["", prompt_loader.mode_text(mode)])
    raw_skills = state.get("active_skills") or {}
    if isinstance(raw_skills, dict):
        skills = [name for name, active in raw_skills.items() if active]
    else:
        skills = list(raw_skills)
    skills = skills[: skill_registry.MAX_ACTIVE]
    if skills:
        lines.extend(["", "ACTIVE SKILLS", skill_registry.pinned_text(skills)])
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
            normalized = str(path).replace("\\", "/").lstrip("./")
            if (
                normalized == "data/secret"
                or normalized.startswith("data/secret/")
                or normalized.lower().endswith(".ans")
            ):
                continue
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
    from author_studio.classic import agent

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


class ContextBudgetMiddleware(AgentMiddleware):
    """Keep every model call inside the context budget and model window.

    SummarizationMiddleware usually compacts older turns, but its approximate
    token counter can undercount dense numeric data by 3x or more, and a single
    huge tool result can survive the kept-message window. This middleware is the
    final guard: it truncates oversized tool/message content, drops the oldest
    complete messages until the conservative estimate fits, and then lowers
    max_tokens so input plus output cannot exceed the provider window.
    """

    state_schema = AuthorState

    def __init__(
        self,
        *,
        model_window_tokens: int = 1_048_576,
        max_output_tokens: int = 393_216,
        reserve_tokens: int = 8192,
        min_output_tokens: int = 1024,
        context_budget_tokens: int = 500_000,
        max_tool_chars: int = 12_000,
        max_message_chars: int = 60_000,
    ) -> None:
        self.model_window_tokens = max(1024, int(model_window_tokens))
        self.max_output_tokens = max(1, int(max_output_tokens))
        self.reserve_tokens = max(0, int(reserve_tokens))
        self.min_output_tokens = max(1, int(min_output_tokens))
        self.context_budget_tokens = max(4096, int(context_budget_tokens))
        self.max_tool_chars = max(1000, int(max_tool_chars))
        self.max_message_chars = max(2000, int(max_message_chars))

    @staticmethod
    def _text(message) -> str:
        content = getattr(message, "content", "")
        return content if isinstance(content, str) else str(content)

    def _truncate(self, message):
        """Bound one message before counting it.

        Numeric test data tokenizes far denser than chars/4 (a 1.3 MB file can
        be ~1.1M provider tokens), so a token estimate alone is not safe.
        """
        text = self._text(message)
        limit = self.max_tool_chars if isinstance(message, ToolMessage) else self.max_message_chars
        if len(text) <= limit:
            return message
        head = text[: int(limit * 0.72)]
        tail = text[-int(limit * 0.18):]
        note = f"\n...[truncated {len(text) - len(head) - len(tail)} chars; request a line range for more]...\n"
        content = head + note + tail
        try:
            return message.model_copy(update={"content": content})
        except Exception:
            return message

    def _estimate(self, messages) -> int:
        return conservative_token_count(messages)

    def _trimmed(self, request: ModelRequest):
        system = request.system_message
        messages = [self._truncate(message) for message in (request.messages or [])]
        if system is not None:
            system = self._truncate(system)
        budget = min(
            self.context_budget_tokens,
            max(1024, self.model_window_tokens - self.reserve_tokens - self.min_output_tokens),
        )

        def total() -> int:
            return self._estimate(([system] if system is not None else []) + messages)

        # Drop the oldest complete messages until the conservative estimate fits.
        while len(messages) > 1 and total() > budget:
            dropped = messages.pop(0)
            if isinstance(dropped, AIMessage) and getattr(dropped, "tool_calls", None):
                while messages and isinstance(messages[0], ToolMessage):
                    messages.pop(0)
        while messages and isinstance(messages[0], ToolMessage):
            messages.pop(0)

        # A single remaining message can still be too large. Cut it to the
        # conservative char budget rather than sending a guaranteed 400.
        if messages and total() > budget:
            last = messages[-1]
            text = self._text(last)
            allowed = max(1000, min(len(text), budget))
            if len(text) > allowed:
                try:
                    last = last.model_copy(update={"content": text[:allowed] + "\n...[truncated to fit the context budget]..."})
                except Exception:
                    pass
                messages[-1] = last
        return system, messages

    def _budget(self, request: ModelRequest) -> tuple[int, int]:
        system, messages = self._trimmed(request)
        all_messages = ([system] if system is not None else []) + messages
        input_tokens = self._estimate(all_messages)
        available = self.model_window_tokens - int(input_tokens) - self.reserve_tokens
        output_tokens = min(self.max_output_tokens, max(self.min_output_tokens, available))
        settings = dict(request.model_settings or {})
        existing = settings.get("max_tokens")
        if isinstance(existing, (int, float)) and existing > 0:
            output_tokens = min(output_tokens, int(existing))
        return int(input_tokens), int(output_tokens)

    def _override(self, request: ModelRequest) -> ModelRequest:
        system, messages = self._trimmed(request)
        all_messages = ([system] if system is not None else []) + messages
        input_tokens = self._estimate(all_messages)
        available = self.model_window_tokens - int(input_tokens) - self.reserve_tokens
        output_tokens = min(self.max_output_tokens, max(self.min_output_tokens, available))
        settings = dict(request.model_settings or {})
        existing = settings.get("max_tokens")
        if isinstance(existing, (int, float)) and existing > 0:
            output_tokens = min(output_tokens, int(existing))
        settings["max_tokens"] = output_tokens
        overrides = {"messages": messages, "model_settings": settings}
        if system is not None:
            overrides["system_message"] = system
        return request.override(**overrides)

    def wrap_model_call(self, request, handler):
        return handler(self._override(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._override(request))


class ProviderStreamError(RuntimeError):
    """A streamed response ended without a terminal finish reason."""


class StreamIntegrityMiddleware(AgentMiddleware):
    """Reject truncated provider streams instead of committing partial text."""

    def _check(self, response):
        for message in response.result:
            content = getattr(message, "content", None)
            tool_calls = getattr(message, "tool_calls", None) or []
            metadata = getattr(message, "response_metadata", None) or {}
            # Test doubles and some local models return no metadata at all;
            # only flag a provider response that has metadata but no terminal
            # finish reason (the signature of a truncated stream).
            if metadata and (content or tool_calls) and not metadata.get("finish_reason"):
                raise ProviderStreamError("Provider stream ended before a finish reason")
        return response

    def wrap_model_call(self, request, handler):
        return self._check(handler(request))

    async def awrap_model_call(self, request, handler):
        return self._check(await handler(request))


class ProviderRefusalMiddleware(AgentMiddleware):
    """Treat OpenAI-style ``refusal`` fields as errors, not success.

    ``ModelRefusalMiddleware`` only inspects standard content blocks. OpenAI
    compatible providers return refusals in ``message.refusal``, which
    LangChain stores in ``additional_kwargs``. Without this guard a refusal
    would be shown as a normal answer.
    """

    def _check(self, response):
        for message in response.result:
            blocks = getattr(message, "content_blocks", None) or []
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "refusal":
                    raise ModelRefusalError.from_refusal(block, raw_message=message)
            refusal = (getattr(message, "additional_kwargs", None) or {}).get("refusal")
            if refusal:
                raise ModelRefusalError.from_refusal(
                    {"type": "refusal", "refusal": str(refusal)},
                    raw_message=message,
                )
        return response

    def wrap_model_call(self, request, handler):
        return self._check(handler(request))

    async def awrap_model_call(self, request, handler):
        return self._check(await handler(request))


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
