"""LangGraph orchestration for the author agent.

The graph is intentionally small: the model node can call the same bounded
workspace tools as before, and a ToolNode executes them. LangGraph gives us
streaming events, a clean state graph, and a place to add checkpoints or
human-in-the-loop interrupts without rewriting the tool loop.

The deterministic verifier remains the authority. The graph can propose and
run work; it cannot mark a package verified or bypass export review.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.message import add_messages
from langgraph.prebuilt import InjectedState, ToolNode, create_react_agent
from pydantic import BaseModel, Field

import agent
import config
import winutil
import workspace


class PlanStep(BaseModel):
    title: str = Field(description="Short step name, e.g. 'Write the input validator'.")
    status: Literal["pending", "in_progress", "completed"] = Field(
        default="pending", description="Current state of this step."
    )


class AgentState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    slug: str
    chat_id: str
    remaining_steps: int


def _run(slug: str, name: str, args: dict) -> dict:
    return agent._dispatch(slug, name, args, lambda *_: None)


@tool
def list_files(path: str = ".", state: Annotated[dict, InjectedState] = None) -> dict:
    """List files and directories in the problem workspace."""
    return _run(state["slug"], "list_files", {"path": path})


@tool
def read_file(path: str, state: Annotated[dict, InjectedState] = None) -> dict:
    """Read a UTF-8 text file from the workspace."""
    return _run(state["slug"], "read_file", {"path": path})


@tool
def write_file(path: str, content: str, state: Annotated[dict, InjectedState] = None) -> dict:
    """Create or replace a text file. The write is tracked as a reviewable change."""
    return _run(state["slug"], "write_file", {"path": path, "content": content})


@tool
def delete_file(path: str, state: Annotated[dict, InjectedState] = None) -> dict:
    """Delete a text file from the workspace. The deletion is tracked and revertible."""
    return _run(state["slug"], "delete_file", {"path": path})


@tool
def run_command(
    command: str,
    timeout_seconds: float | None = None,
    stdin: str | None = None,
    cwd: str | None = None,
    stdout_path: str | None = None,
    state: Annotated[dict, InjectedState] = None,
) -> dict:
    """Run an allowlisted command inside the workspace (g++, gcc, python, javac, java, pdflatex, latexmk).
    No shell, no pipes, no redirection, no network tools. Use stdin for a literal test input and
    stdout_path to save generated output into the workspace."""
    args = {"command": command}
    if timeout_seconds is not None:
        args["timeout_seconds"] = timeout_seconds
    if stdin is not None:
        args["stdin"] = stdin
    if cwd is not None:
        args["cwd"] = cwd
    if stdout_path is not None:
        args["stdout_path"] = stdout_path
    return _run(state["slug"], "run_command", args)


@tool
def build_answers(state: Annotated[dict, InjectedState] = None) -> dict:
    """Run the accepted reference solution(s) on every input and write .ans files."""
    return _run(state["slug"], "build_answers", {})


@tool
def measure_limits(state: Annotated[dict, InjectedState] = None) -> dict:
    """Measure the accepted references on every test and write measured time/memory limits.
    Call this after the reference and tests exist, before final verification."""
    return _run(state["slug"], "measure_limits", {})


@tool
def verify_package(write_answers: bool = False, state: Annotated[dict, InjectedState] = None) -> dict:
    """Run the deterministic package check: validator, reference answers, negative solutions, statement."""
    return _run(state["slug"], "verify_package", {"write_answers": write_answers})


@tool
def read_report(state: Annotated[dict, InjectedState] = None) -> dict:
    """Read the last deterministic verification report without running anything."""
    return _run(state["slug"], "read_report", {})


@tool
def export_package(state: Annotated[dict, InjectedState] = None) -> dict:
    """Build the final DOMjudge ZIP. Refused unless verification and review gates pass."""
    return _run(state["slug"], "export_package", {})


@tool
def update_plan(steps: list[PlanStep], state: Annotated[dict, InjectedState] = None) -> dict:
    """Publish the current authoring plan so the user can follow the work. Use 3-8 concrete steps."""
    payload = [step.model_dump() for step in steps]
    return workspace.save_plan(state["slug"], state["chat_id"], payload)


TOOLS = [
    list_files,
    read_file,
    write_file,
    delete_file,
    run_command,
    build_answers,
    measure_limits,
    verify_package,
    read_report,
    export_package,
    update_plan,
]


def _prompt(state: AgentState):
    system = agent.SYSTEM + "\n\n" + agent._state_note(state["slug"])
    return [SystemMessage(content=system)] + list(state.get("messages") or [])


def _model(cfg: dict) -> ChatOpenAI:
    if not cfg.get("apiKey"):
        raise RuntimeError("No API key is configured. Open Settings and add a DeepSeek or OpenRouter key.")
    headers = {}
    base = str(cfg.get("baseUrl") or "")
    if "openrouter" in base:
        headers = {"HTTP-Referer": "http://127.0.0.1", "X-Title": "ICPC Author Agent"}
    return ChatOpenAI(
        model=str(cfg.get("model") or "deepseek-chat"),
        api_key=str(cfg.get("apiKey")),
        base_url=base or None,
        temperature=float(cfg.get("temperature", 0.2)),
        max_retries=1,
        timeout=300,
        streaming=True,
        extra_body={"max_tokens": 8000},
        default_headers=headers or None,
    )


def _graph(cfg: dict, checkpointer=None):
    return create_react_agent(
        _model(cfg),
        ToolNode(TOOLS, handle_tool_errors=True),
        prompt=_prompt,
        state_schema=AgentState,
        checkpointer=checkpointer,
        name="icpc_author_agent",
    )


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
        return "".join(parts)
    return "" if content is None else str(content)


def _repair_history(messages: list[dict]) -> list[dict]:
    """Make saved history valid for the next graph turn.

    A tool exception or a server restart can leave an AIMessage with tool_calls
    but no matching ToolMessage. LangGraph rejects that history. Insert a
    synthetic error result so the model can recover instead of losing the chat.
    """
    repaired: list[dict] = []
    pending: list[str] = []

    def flush() -> None:
        nonlocal pending
        for call_id in pending:
            repaired.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": json.dumps({
                    "error": "Previous tool call did not complete; the run was interrupted before a result was recorded."
                }),
            })
        pending = []

    for message in messages:
        role = message.get("role")
        if role in ("user", "assistant") and pending:
            flush()
        if role == "assistant":
            repaired.append(message)
            pending = [call.get("id") for call in (message.get("tool_calls") or []) if call.get("id")]
        elif role == "tool":
            call_id = message.get("tool_call_id")
            if call_id in pending:
                pending.remove(call_id)
                repaired.append(message)
            # Orphan tool messages are dropped rather than breaking validation.
        else:
            repaired.append(message)
    flush()
    return repaired


def _to_lc(message: dict) -> BaseMessage | None:
    role = message.get("role")
    if role == "user":
        return HumanMessage(content=_content_text(message.get("content")))
    if role == "assistant":
        calls = []
        for call in message.get("tool_calls") or []:
            fn = call.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except (TypeError, ValueError):
                args = {}
            calls.append({"name": fn.get("name") or "", "args": args, "id": call.get("id") or ""})
        result = AIMessage(content=_content_text(message.get("content")), tool_calls=calls)
        if message.get("reasoning"):
            result.additional_kwargs["reasoning_content"] = str(message["reasoning"])
        return result
    if role == "tool":
        return ToolMessage(
            content=_content_text(message.get("content")),
            tool_call_id=str(message.get("tool_call_id") or ""),
        )
    return None


def _from_lc(message: BaseMessage) -> dict | None:
    if isinstance(message, HumanMessage):
        return {"role": "user", "content": _content_text(message.content)}
    if isinstance(message, AIMessage):
        data = {"role": "assistant", "content": _content_text(message.content)}
        calls = []
        for index, call in enumerate(message.tool_calls or []):
            calls.append({
                "id": call.get("id") or f"call_{index}",
                "type": "function",
                "function": {
                    "name": call.get("name") or "",
                    "arguments": json.dumps(call.get("args") or {}, ensure_ascii=False),
                },
            })
        if calls:
            data["tool_calls"] = calls
        reasoning = (
            message.additional_kwargs.get("reasoning_content")
            or message.additional_kwargs.get("reasoning")
            or message.response_metadata.get("reasoning_content")
        )
        if reasoning:
            data["reasoning"] = _content_text(reasoning)
        return data
    if isinstance(message, ToolMessage):
        content = message.content if isinstance(message.content, str) else json.dumps(message.content, ensure_ascii=False)
        return {"role": "tool", "tool_call_id": message.tool_call_id, "content": content}
    return None


def _reasoning_of(chunk_or_message) -> str:
    additional = getattr(chunk_or_message, "additional_kwargs", {}) or {}
    metadata = getattr(chunk_or_message, "response_metadata", {}) or {}
    value = additional.get("reasoning_content") or additional.get("reasoning") or metadata.get("reasoning_content")
    return _content_text(value)


def _result_of(output) -> dict:
    if isinstance(output, ToolMessage):
        content = output.content
        if isinstance(content, str):
            try:
                parsed = json.loads(content)
                return parsed if isinstance(parsed, dict) else {"result": parsed}
            except ValueError:
                return {"result": content}
        if isinstance(content, dict):
            return content
        return {"result": _content_text(content)}
    if isinstance(output, dict):
        return output
    return {"result": _content_text(output)}


def _emit_tool_side_effects(name: str, result: dict, emit) -> None:
    if name in ("write_file", "delete_file") and result.get("changed"):
        emit("change", {
            "path": result.get("path"),
            "diff": str(result.get("diff") or "")[:12000],
            "changeId": result.get("changeId"),
        })
    if name == "verify_package":
        emit("verification", {"stage": "verify", "result": result})
    if name == "build_answers":
        emit("verification", {"stage": "answers", "result": result})
    if name == "measure_limits":
        emit("limits", result)
    if name == "export_package":
        emit("export", result)
    if name == "update_plan":
        emit("plan", result)


async def _run_turn_async(slug: str, chat_id: str, user_message: str, emit, cfg: dict, collected: list[BaseMessage], cancelled=None) -> tuple[str, int, list[BaseMessage] | None]:
    checkpointer = MemorySaver()
    graph = _graph(cfg, checkpointer)
    thread_id = f"{chat_id}-{uuid.uuid4().hex[:10]}"
    graph_config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": max(8, int(cfg.get("maxToolRounds", 24)) * 2 + 4),
    }
    final_text = ""
    rounds = 0
    async for event in graph.astream_events(
        {"messages": collected, "slug": slug, "chat_id": chat_id},
        config=graph_config,
        version="v2",
    ):
        if cancelled is not None and cancelled():
            raise RuntimeError("Cancelled by user")
        kind = event.get("event")
        name = event.get("name") or ""
        data = event.get("data") or {}
        if kind == "on_chat_model_start":
            rounds += 1
            emit("thinking", {"round": rounds})
        elif kind == "on_chat_model_stream":
            chunk = data.get("chunk")
            reasoning = _reasoning_of(chunk)
            if reasoning:
                emit("reasoning_delta", {"text": reasoning})
            text = _content_text(getattr(chunk, "content", ""))
            if text:
                emit("assistant_delta", {"text": text})
        elif kind == "on_chat_model_end":
            message = data.get("output")
            if isinstance(message, AIMessage):
                reasoning = _reasoning_of(message)
                text = _content_text(message.content)
                if reasoning:
                    emit("reasoning", {"text": reasoning})
                if text:
                    final_text = text
                    emit("assistant", {"text": text})
                collected.append(message)
        elif kind == "on_tool_start":
            emit("tool_call", {"name": name, "args": data.get("input") or {}})
        elif kind == "on_tool_end":
            result = _result_of(data.get("output"))
            emit("tool_result", {"name": name, "result": result})
            _emit_tool_side_effects(name, result, emit)
            output = data.get("output")
            if isinstance(output, ToolMessage):
                collected.append(output)
        elif kind == "on_tool_error":
            error = _content_text(data.get("error") or "Tool call failed")
            emit("tool_result", {"name": name, "result": {"error": error}})
    snapshot = graph.get_state(graph_config)
    final_messages = snapshot.values.get("messages") if snapshot and snapshot.values else None
    return final_text, rounds, final_messages


def run_turn(slug: str, chat_id: str, user_message: str, emit, cancelled=None) -> dict:
    winutil.prepare()
    if cancelled is not None and cancelled():
        raise RuntimeError("Cancelled by user")
    cfg = config.load()
    chat = workspace.get_chat(slug, chat_id)
    original_history = chat.get("messages") or []
    history = _repair_history(original_history)
    if history != original_history:
        workspace.save_chat_messages(slug, chat_id, history)
    user_message = str(user_message)[:20000]

    lc_history = [message for message in (_to_lc(item) for item in history) if message is not None]
    user = HumanMessage(content=user_message)
    collected = list(lc_history) + [user]

    # Persist the user turn immediately so a provider failure never loses it.
    workspace.save_chat_messages(slug, chat_id, [item for item in (_from_lc(m) for m in collected) if item])

    if not cfg.get("apiKey"):
        raise RuntimeError("No API key is configured. Open Settings and add a DeepSeek or OpenRouter key.")

    try:
        final_text, rounds, final_messages = asyncio.run(_run_turn_async(slug, chat_id, user_message, emit, cfg, collected, cancelled))
        source = final_messages if final_messages is not None else collected
        converted = [item for item in (_from_lc(m) for m in source) if item]
        workspace.save_chat_messages(slug, chat_id, converted)
        return {"text": final_text, "chatId": chat_id, "rounds": rounds}
    except Exception as exc:  # noqa: BLE001
        converted = [item for item in (_from_lc(m) for m in collected) if item]
        workspace.save_chat_messages(slug, chat_id, converted)
        if cancelled is not None and cancelled():
            raise RuntimeError("Cancelled by user") from exc
        emit("error", {"error": str(exc)})
        raise
