"""LangChain agent runtime for the author.

This module uses the supported `create_agent` harness with middleware:
- durable SQLite checkpoints per workspace,
- pinned working memory in the system message,
- built-in todo list, summarization and human-in-the-loop approval,
- async tool-error handling.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import threading
import uuid
from typing import Annotated, Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    ModelCallLimitMiddleware,
    SummarizationMiddleware,
    TodoListMiddleware,
)
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, RemoveMessage, ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from agent_middleware import PinnedContextMiddleware, ToolErrorMiddleware
from agent_state import AuthorState, clean_brief, clean_decisions, clean_list
import agent
import config
import winutil
import workspace

REVIEWER_PROMPT = """You are an independent ICPC problem reviewer. You do not approve, export,
edit or run code. Review only the selected workspace files and the verification summary.
Look for ambiguity, missing constraints, weak or missing edge cases, validator gaps,
reference assumptions and negative solutions that do not exercise the intended defect.
Never read `data/secret`, answer files, or hidden test data. Return a concise set of
findings with exact file paths and, where useful, a suggested test. Do not claim a
package is verified; the deterministic verifier is the authority."""


_LOOP = None
_LOOP_LOCK = threading.Lock()
_TASKS: dict[str, asyncio.Task] = {}
_TASKS_LOCK = threading.Lock()


def _event_loop():
    global _LOOP
    with _LOOP_LOCK:
        if _LOOP is None or _LOOP.is_closed():
            _LOOP = asyncio.new_event_loop()
            threading.Thread(target=_LOOP.run_forever, name="author-agent-loop", daemon=True).start()
        return _LOOP


def _run_coro(coro, key: str | None = None):
    """Run a coroutine on one persistent loop and register its task by key."""
    loop = _event_loop()
    done: concurrent.futures.Future = concurrent.futures.Future()

    def create() -> None:
        task = loop.create_task(coro)
        if key:
            with _TASKS_LOCK:
                _TASKS[key] = task

        def finish(finished: asyncio.Task) -> None:
            try:
                if finished.cancelled():
                    done.set_exception(RuntimeError("Cancelled by user"))
                    return
                error = finished.exception()
                if error is not None:
                    done.set_exception(error)
                else:
                    done.set_result(finished.result())
            finally:
                if key:
                    with _TASKS_LOCK:
                        if _TASKS.get(key) is task:
                            _TASKS.pop(key, None)

        task.add_done_callback(finish)

    loop.call_soon_threadsafe(create)
    try:
        return done.result()
    except asyncio.CancelledError as exc:
        raise RuntimeError("Cancelled by user") from exc


def delete_thread(slug: str, chat_id: str) -> None:
    """Best-effort removal of a deleted chat's checkpoint thread."""

    async def remove() -> None:
        db = workspace.checkpoint_path(slug)
        async with AsyncSqliteSaver.from_conn_string(str(db)) as saver:
            await saver.setup()
            await saver.adelete_thread(chat_id)

    try:
        _run_coro(remove())
    except Exception:
        pass


def cancel_turn(slug: str, chat_id: str) -> bool:
    """Cancel the provider coroutine for a chat, aborting the HTTP stream."""
    key = f"chat:{slug}:{chat_id}"
    with _TASKS_LOCK:
        task = _TASKS.get(key)
    if task is None:
        return False
    loop = task.get_loop()
    loop.call_soon_threadsafe(task.cancel)
    return True


def _run(slug: str, name: str, args: dict) -> dict:
    return agent._dispatch(slug, name, args, lambda *_: None)


@tool
def list_files(path: str = ".", state: Annotated[dict, InjectedState] = None) -> dict:
    """List files and directories in the problem workspace."""
    return _run(state["slug"], "list_files", {"path": path})


@tool
def read_file(
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    state: Annotated[dict, InjectedState] = None,
) -> dict:
    """Read a UTF-8 text file, optionally a 1-based inclusive line range."""
    args = {"path": path}
    if start_line is not None:
        args["start_line"] = start_line
    if end_line is not None:
        args["end_line"] = end_line
    return _run(state["slug"], "read_file", args)


@tool
def write_file(path: str, content: str, state: Annotated[dict, InjectedState] = None) -> dict:
    """Create or replace a text file. The write is tracked as a reviewable change."""
    return _run(state["slug"], "write_file", {"path": path, "content": content})


@tool
def delete_file(path: str, state: Annotated[dict, InjectedState] = None) -> dict:
    """Delete a text file. The deletion is tracked and revertible."""
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
    """Run an allowlisted command inside the workspace. No shell, pipes or network."""
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
    """Run the accepted reference solutions on every input and write .ans files."""
    return _run(state["slug"], "build_answers", {})


@tool
def measure_limits(state: Annotated[dict, InjectedState] = None) -> dict:
    """Measure accepted references on every test and write measured time/memory limits."""
    return _run(state["slug"], "measure_limits", {})


@tool
def verify_package(write_answers: bool = False, state: Annotated[dict, InjectedState] = None) -> dict:
    """Run the deterministic package check: validator, references, negatives, statement."""
    return _run(state["slug"], "verify_package", {"write_answers": write_answers})


@tool
def read_report(state: Annotated[dict, InjectedState] = None) -> dict:
    """Read the last deterministic verification report without running anything."""
    return _run(state["slug"], "read_report", {})


@tool
def export_package(state: Annotated[dict, InjectedState] = None) -> dict:
    """Build the final DOMjudge ZIP. Always pause for human approval before this runs."""
    return _run(state["slug"], "export_package", {})


@tool
def search_workspace(
    query: str,
    glob: str | None = None,
    max_results: int = 40,
    state: Annotated[dict, InjectedState] = None,
) -> dict:
    """Search text files in the workspace and return bounded path/line snippets."""
    return _run(state["slug"], "search_workspace", {"query": query, "glob": glob, "max_results": max_results})


@tool
def list_tests(state: Annotated[dict, InjectedState] = None) -> dict:
    """List sample/secret test names and counts without exposing hidden test content."""
    return _run(state["slug"], "list_tests", {})


@tool
def report_summary(state: Annotated[dict, InjectedState] = None) -> dict:
    """Return a compact verification status, counts and blockers."""
    return _run(state["slug"], "report_summary", {})


@tool
def update_brief(brief: str, tool_call_id: Annotated[str, InjectedToolCallId], state: Annotated[dict, InjectedState] = None) -> Command:
    """Update the pinned working brief. Keep it concise and factual."""
    return Command(update={
        "brief": clean_brief(brief),
        "messages": [ToolMessage(content="Working brief updated.", tool_call_id=tool_call_id)],
    })


@tool
def record_decision(
    question: str,
    answer: str,
    rationale: str = "",
    source: str = "",
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
    state: Annotated[dict, InjectedState] = None,
) -> Command:
    """Record a setter interpretation or assumption so it survives context compaction."""
    decision = clean_decisions([{"question": question, "answer": answer, "rationale": rationale, "source": source}])
    if not decision:
        raise ValueError("A decision needs a question and an answer")
    return Command(update={
        "decisions": decision,
        "messages": [ToolMessage(content="Decision recorded.", tool_call_id=tool_call_id)],
    })


@tool
def set_focus(focus: str, tool_call_id: Annotated[str, InjectedToolCallId], state: Annotated[dict, InjectedState] = None) -> Command:
    """Set the current one-line objective for the agent."""
    return Command(update={
        "focus": " ".join(str(focus or "").split())[:500],
        "messages": [ToolMessage(content="Focus updated.", tool_call_id=tool_call_id)],
    })


@tool
def reviewer_list_files(path: str = ".", state: Annotated[dict, InjectedState] = None) -> dict:
    """List files for the independent reviewer."""
    return _run(state["slug"], "list_files", {"path": path})


@tool
def reviewer_read_file(path: str, state: Annotated[dict, InjectedState] = None) -> dict:
    """Read a non-secret file for the independent reviewer."""
    rel = str(path or "").replace("\\", "/")
    if rel.startswith("data/secret") or rel.endswith(".ans") or rel.endswith(".in"):
        raise ValueError("The reviewer may not read test data or answer files.")
    return _run(state["slug"], "read_file", {"path": rel})


@tool
def reviewer_report(state: Annotated[dict, InjectedState] = None) -> dict:
    """Read the compact verification report for the independent reviewer."""
    return _run(state["slug"], "report_summary", {})


REVIEWER_TOOLS = [reviewer_list_files, reviewer_read_file, reviewer_report]


@tool
async def review_package(request: str = "Review this package for ambiguity and weak tests.", state: Annotated[dict, InjectedState] = None) -> dict:
    """Ask an independent, read-only reviewer agent for proposal-only findings."""
    cfg = config.load()
    reviewer_model = _model(cfg)
    reviewer = create_agent(
        reviewer_model,
        REVIEWER_TOOLS,
        state_schema=AuthorState,
        system_prompt=REVIEWER_PROMPT,
        name="icpc_reviewer",
    )
    try:
        result = await reviewer.ainvoke({
            "messages": [HumanMessage(content=str(request))],
            "slug": state.get("slug"),
            "chat_id": state.get("chat_id") or "reviewer",
            "decisions": [],
        })
        value = getattr(result, "value", result)
        messages = value.get("messages", []) if isinstance(value, dict) else []
        text = str(messages[-1].content) if messages else "Reviewer returned no findings."
        return {"review": text}
    finally:
        try:
            await reviewer_model.async_client.close()
        except Exception:
            pass


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
    search_workspace,
    list_tests,
    report_summary,
    update_brief,
    record_decision,
    set_focus,
    review_package,
]


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


def _reasoning_of(chunk_or_message) -> str:
    additional = getattr(chunk_or_message, "additional_kwargs", {}) or {}
    metadata = getattr(chunk_or_message, "response_metadata", {}) or {}
    value = additional.get("reasoning_content") or additional.get("reasoning") or metadata.get("reasoning_content")
    return _content_text(value)


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
        return ToolMessage(content=_content_text(message.get("content")), tool_call_id=str(message.get("tool_call_id") or ""))
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
                "function": {"name": call.get("name") or "", "arguments": json.dumps(call.get("args") or {}, ensure_ascii=False)},
            })
        if calls:
            data["tool_calls"] = calls
        reasoning = message.additional_kwargs.get("reasoning_content") or message.additional_kwargs.get("reasoning")
        if reasoning:
            data["reasoning"] = _content_text(reasoning)
        return data
    if isinstance(message, ToolMessage):
        content = message.content if isinstance(message.content, str) else json.dumps(message.content, ensure_ascii=False)
        return {"role": "tool", "tool_call_id": message.tool_call_id, "content": content}
    return None


def _repair_history(messages: list[dict]) -> list[dict]:
    repaired: list[dict] = []
    pending: list[str] = []

    def flush() -> None:
        nonlocal pending
        for call_id in pending:
            repaired.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": json.dumps({"error": "Previous tool call did not complete; the run was interrupted."}),
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
        else:
            repaired.append(message)
    flush()
    return repaired


def _sanitize_message_ids(messages: list[BaseMessage]) -> tuple[list[str], bool]:
    """Return ids to remove and whether an id-less message blocks repair."""
    remove: list[str] = []
    blocked = False
    index = 0
    while index < len(messages):
        message = messages[index]
        if isinstance(message, AIMessage) and message.tool_calls:
            expected = {call.get("id") for call in message.tool_calls if call.get("id")}
            cursor = index + 1
            block: list[ToolMessage] = []
            while cursor < len(messages) and isinstance(messages[cursor], ToolMessage):
                block.append(messages[cursor])
                cursor += 1
            block_ids = {item.tool_call_id for item in block}
            if expected - block_ids:
                if message.id:
                    remove.append(message.id)
                else:
                    blocked = True
                for item in block:
                    if item.id:
                        remove.append(item.id)
                    else:
                        blocked = True
            else:
                for item in block:
                    if item.tool_call_id not in expected:
                        if item.id:
                            remove.append(item.id)
                        else:
                            blocked = True
            index = cursor
        elif isinstance(message, ToolMessage):
            # Orphan tool message, typically from a crashed repair or an
            # incomplete group whose assistant was removed.
            if message.id:
                remove.append(message.id)
            else:
                blocked = True
            index += 1
        else:
            index += 1
    return list(dict.fromkeys(remove)), blocked


async def _repair_checkpoint(graph, saver, config) -> bool:
    """Remove incomplete assistant/tool groups left by a crashed turn.

    A HITL pause intentionally has an assistant tool call without a tool result;
    those states have task interrupts and must not be repaired. Removing the
    whole incomplete group also handles a failed user message that already
    followed the dangling call. The failed user turn remains in the transcript.

    Returns True when the thread had to be reset and the caller must reseed.
    """
    snapshot = await graph.aget_state(config)
    if any(getattr(task, "interrupts", ()) for task in (getattr(snapshot, "tasks", ()) or ())):
        return False
    remove, blocked = _sanitize_message_ids(snapshot.values.get("messages", []))
    if blocked:
        chat_id = config.get("configurable", {}).get("thread_id")
        if chat_id:
            await saver.adelete_thread(chat_id)
        return True
    if remove:
        await graph.aupdate_state(config, {"messages": [RemoveMessage(id=item) for item in remove]})
    return False


def _result_of(output) -> dict:
    if isinstance(output, Command):
        update = output.update if isinstance(output.update, dict) else {}
        messages = update.get("messages") or []
        for message in messages:
            if isinstance(message, ToolMessage):
                parsed = _result_of(message)
                if isinstance(parsed, dict) and "result" in parsed and len(parsed) == 1:
                    return parsed["result"]
                return parsed
        return {"result": "command applied", "updateKeys": list(update.keys())}
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


def _jsonable(value) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    try:
        return json.loads(json.dumps(value, default=str))
    except (TypeError, ValueError):
        return str(value)


def _interrupts(snapshot) -> list[dict]:
    out = []
    for task in getattr(snapshot, "tasks", ()) or ():
        for item in getattr(task, "interrupts", ()) or ():
            out.append({"id": item.id, "value": _jsonable(item.value)})
    return out


def _todos_from_plan(plan: dict) -> list[dict]:
    out = []
    for step in (plan or {}).get("steps", []):
        title = str(step.get("title") or "").strip()
        if title:
            status = step.get("status") if step.get("status") in ("pending", "in_progress", "completed") else "pending"
            out.append({"content": title[:500], "status": status})
    return out[:12]


def _plan_from_todos(todos) -> list[dict]:
    out = []
    for item in todos or []:
        content = str(item.get("content") or "").strip()
        if content:
            out.append({"title": content[:500], "status": item.get("status") or "pending"})
    return out[:12]


def _save_snapshot(slug: str, chat_id: str, snapshot) -> dict:
    values = snapshot.values if snapshot and snapshot.values else {}
    messages = [item for item in (_from_lc(m) for m in values.get("messages", [])) if item]
    if messages:
        workspace.save_chat_messages(slug, chat_id, messages)
    todos = values.get("todos") or []
    workspace.save_plan(slug, chat_id, _plan_from_todos(todos))
    return values


def _accumulate_usage(totals: dict, message) -> None:
    usage = getattr(message, "usage_metadata", None)
    if not usage:
        return
    try:
        mapping = dict(usage)
    except (TypeError, ValueError):
        return
    for key in ("input_tokens", "output_tokens", "total_tokens", "cached_tokens"):
        value = mapping.get(key)
        if isinstance(value, (int, float)):
            totals[key] = int(totals.get(key, 0)) + int(value)
    totals["reported"] = True


async def _run_turn_async(
    slug: str,
    chat_id: str,
    user_message: str,
    emit,
    cfg: dict,
    mode: str | None = None,
    selected_context: list[str] | None = None,
    cancelled=None,
    resume=None,
) -> tuple[str, int, dict, list[dict], dict]:
    db = workspace.checkpoint_path(slug)
    async with AsyncSqliteSaver.from_conn_string(str(db)) as saver:
        await saver.setup()
        thread_config = {
            "configurable": {"thread_id": chat_id},
            # Middleware nodes (pinned context, todo, HITL, summarization,
            # call limit) add graph steps; keep the step budget wider than the
            # model-call limit. ModelCallLimitMiddleware still caps real calls.
            "recursion_limit": max(60, int(cfg.get("maxToolRounds", 24)) * 6 + 20),
        }
        graph, graph_model = _graph(cfg, saver)
        existing = await saver.aget_tuple(thread_config)
        if existing is not None and resume is None:
            if await _repair_checkpoint(graph, saver, thread_config):
                existing = None
        if resume is not None:
            input_state = Command(resume=resume)
        elif existing is None:
            history = _repair_history(workspace.get_chat(slug, chat_id).get("messages") or [])
            lc_history = [item for item in (_to_lc(m) for m in history) if item is not None]
            input_state = {
                "messages": lc_history + [HumanMessage(content=str(user_message)[:20000])],
                "slug": slug,
                "chat_id": chat_id,
                "mode": mode or "author",
                "selected_context": clean_list(selected_context or [], 25),
                "todos": _todos_from_plan(workspace.get_plan(slug, chat_id)),
                "decisions": [],
            }
        else:
            input_state = {
                "messages": [HumanMessage(content=str(user_message)[:20000])],
                "slug": slug,
                "chat_id": chat_id,
                "mode": mode or "author",
                "selected_context": clean_list(selected_context or [], 25),
                "decisions": [],
            }

        final_text = ""
        rounds = 0
        usage = {}
        async for event in graph.astream_events(input_state, config=thread_config, version="v2"):
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
                    _accumulate_usage(usage, message)
            elif kind == "on_tool_start":
                emit("tool_call", {"name": name, "args": data.get("input") or {}})
            elif kind == "on_tool_end":
                result = _result_of(data.get("output"))
                emit("tool_result", {"name": name, "result": result})
                _emit_tool_side_effects(name, result, emit)
            elif kind == "on_tool_error":
                emit("tool_result", {"name": name, "result": {"error": _content_text(data.get("error") or "Tool call failed")}})

        snapshot = await graph.aget_state(thread_config)
        values = _save_snapshot(slug, chat_id, snapshot)
        interrupts = _interrupts(snapshot)
        if interrupts:
            workspace.save_pending(slug, chat_id, interrupts)
            emit("approval", {"interrupts": interrupts})
        else:
            workspace.clear_pending(slug, chat_id)
        if usage:
            try:
                usage["costUsd"] = round(
                    int(usage.get("input_tokens", 0)) / 1_000_000 * float(cfg.get("inputPricePerMillion", 0.0))
                    + int(usage.get("output_tokens", 0)) / 1_000_000 * float(cfg.get("outputPricePerMillion", 0.0)),
                    6,
                )
            except (TypeError, ValueError):
                usage["costUsd"] = None
            emit("usage", usage)
        try:
            await graph_model.async_client.close()
        except Exception:
            pass
        return final_text, rounds, usage, interrupts, values


def _graph(cfg: dict, saver):
    model = _model(cfg)
    review_writes = bool(cfg.get("reviewWrites"))
    interrupt_on = {"export_package": {"allowed_decisions": ["approve", "reject"]}}
    if review_writes:
        interrupt_on["write_file"] = {"allowed_decisions": ["approve", "edit", "reject"]}
        interrupt_on["delete_file"] = {"allowed_decisions": ["approve", "reject"]}
    graph = create_agent(
        model,
        TOOLS,
        state_schema=AuthorState,
        system_prompt=agent.SYSTEM,
        middleware=[
            PinnedContextMiddleware(),
            SummarizationMiddleware(
                model=model,
                trigger=("tokens", int(cfg.get("summaryTriggerTokens", 30000))),
                keep=("messages", int(cfg.get("summaryKeepMessages", 12))),
            ),
            TodoListMiddleware(),
            HumanInTheLoopMiddleware(interrupt_on=interrupt_on, interrupt_mode="per_call"),
            ToolErrorMiddleware(),
            ModelCallLimitMiddleware(run_limit=max(8, int(cfg.get("maxToolRounds", 24)))),
        ],
        checkpointer=saver,
        name="icpc_author_agent",
    )
    return graph, model


def _model(cfg: dict) -> ChatOpenAI:
    if not cfg.get("apiKey"):
        raise RuntimeError("No API key is configured. Open Settings and add a DeepSeek or OpenRouter key.")
    # httpx2/OpenAI streaming can fail on compressed responses in the pinned
    # dependency set (`process() takes no keyword arguments`). Ask providers for
    # an identity-encoded response.
    headers = {"Accept-Encoding": "identity"}
    base = str(cfg.get("baseUrl") or "")
    if "openrouter" in base:
        headers.update({"HTTP-Referer": "http://127.0.0.1", "X-Title": "ICPC Author Agent"})
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


def run_turn(slug: str, chat_id: str, user_message: str, emit, cancelled=None, mode=None, selected_context=None) -> dict:
    winutil.prepare()
    if cancelled is not None and cancelled():
        raise RuntimeError("Cancelled by user")
    cfg = config.load()
    history = workspace.get_chat(slug, chat_id).get("messages") or []
    try:
        final_text, rounds, usage, interrupts, values = _run_coro(_run_turn_async(
            slug, chat_id, user_message, emit, cfg, mode, selected_context, cancelled,
        ), key=f"chat:{slug}:{chat_id}")
        result = {
            "text": final_text,
            "chatId": chat_id,
            "rounds": rounds,
            "usage": usage,
            "paused": bool(interrupts),
            "interrupts": interrupts,
            "plan": workspace.get_plan(slug, chat_id),
        }
        return result
    except Exception:
        # Preserve the user's turn in the visible mirror if the provider failed.
        try:
            repaired = _repair_history(history)
            repaired.append({"role": "user", "content": str(user_message)[:20000]})
            workspace.save_chat_messages(slug, chat_id, repaired)
        except Exception:
            pass
        raise


def resume_turn(slug: str, chat_id: str, decisions, emit, cancelled=None) -> dict:
    winutil.prepare()
    if cancelled is not None and cancelled():
        raise RuntimeError("Cancelled by user")
    cfg = config.load()
    final_text, rounds, usage, interrupts, values = _run_coro(_run_turn_async(
        slug, chat_id, "", emit, cfg, None, None, cancelled, resume=decisions,
    ), key=f"chat:{slug}:{chat_id}")
    return {
        "text": final_text,
        "chatId": chat_id,
        "rounds": rounds,
        "usage": usage,
        "paused": bool(interrupts),
        "interrupts": interrupts,
        "plan": workspace.get_plan(slug, chat_id),
    }
