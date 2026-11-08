"""Provider tool loop for the author agent.

The model is given a small registry of typed tools. Every tool dispatches
through the same workspace/verifier functions used by the UI. Tool output is
untrusted data, never instructions. The model cannot approve or export by
itself: export is a separate human action and is blocked unless the
deterministic verifier says the package is verified.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request

from config import TEMPLATES
import config
import verify
import winutil
import workspace

SYSTEM = """You are ICPC Author Agent, a careful problem-setting agent working inside a local workspace.

Your job is to take an idea or draft statement to a complete, verified DOMjudge package:
statement -> validator -> reference solution -> tests -> generated answers -> negative solutions -> verification -> export.

Non-negotiable rules:
1. Use the tools for all work. Never claim you compiled, ran, or verified something unless a tool result proves it.
2. Stay inside the workspace. Never try to read files elsewhere on the machine and never use the network.
3. The deterministic verify_package tool is the source of truth. A chat answer is not evidence.
4. Do not call export_package until verify_package returns status "verified". Export also requires the human to mark changes reviewed, so if export is refused for unreviewed changes, tell the user to review the Changes panel and click Export themselves.
5. Inputs are literal test data. Generators may be kept as extra files, but every secret/sample input must exist as .in with a matching .ans.
6. Write the statement in problem_statement/problem.en.tex using the provided icpcproblem class. Compile it with pdflatex; fix all errors.
7. The validator in input_validators/validate.py must exit 42 (or 0) for valid input and reject malformed or out-of-constraint input.
8. Reference solutions live in submissions/accepted/. Negative solutions live in submissions/wrong_answer/ (or time_limit_exceeded/). At least one negative solution must be killed by a test; a wrong program that gets AC everywhere proves the tests are weak.
9. Keep test names descriptive, e.g. data/secret/07_max_n.in. Samples live in data/sample/.
10. Prefer C++20 for the reference solution unless the workspace already uses another language. Python is acceptable if fast enough.
11. After a failed tool call, read the error, fix the cause, and try again. Do not repeat the same failing command blindly.
12. Be concise in chat. Report what you changed, what you ran, and the exact verification result. Put explanations in the files, not in long chat messages.

A good turn is: inspect the workspace, write or patch files, build answers, run verification, fix concrete failures, re-run until green, then summarize the remaining human-review items. If the idea is underspecified, state the assumptions you made and encode them in NOTES.md and the statement/validator.

Narrate your work for the author. Before each batch of tool calls, write 1-3 short sentences saying what you are about to do and why. After tool results, say what you learned, what failed, and what you will do next. This is a working explanation, not a hidden chain-of-thought dump: be concrete, mention file names and commands, and keep moving. Never claim something passed unless the tool result says so.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in the workspace. Use this before reading blindly.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Optional subdirectory, default ."}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file inside the workspace.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or replace a text file. Parent directories are created. Every write is tracked as a reviewable change.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a text file inside the workspace. The deletion is tracked and can be reverted.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run an allowlisted compiler/interpreter command (g++, gcc, python, javac, java, pdflatex, latexmk) with cwd inside the workspace. No shell, no pipes, no redirection, no network tools. Use it to compile, run solutions, and build the PDF.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Full command line, e.g. g++ -O2 -std=gnu++20 -o build/ref submissions/accepted/ref.cpp"},
                    "timeout_seconds": {"type": "number", "description": "Optional, default 30, maximum 120"},
                    "stdin": {"type": "string", "description": "Optional literal text piped to the program's standard input. Use this to test a solution on one case."},
                    "cwd": {"type": "string", "description": "Optional working directory inside the workspace, e.g. problem_statement when compiling LaTeX."},
                    "stdout_path": {"type": "string", "description": "Optional workspace file to receive the program's stdout. Use this to save a generated test input without shell redirection."},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_answers",
            "description": "Run the reference solution(s) on every sample and secret input and write the .ans files. Fails if accepted references disagree.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify_package",
            "description": "Run the full deterministic package check: structure, validator, reference vs answers, negative solutions, and statement compilation. Returns the exact report.",
            "parameters": {
                "type": "object",
                "properties": {
                    "write_answers": {
                        "type": "boolean",
                        "description": "Also regenerate answers from the reference before checking. Default false.",
                    }
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_report",
            "description": "Read the last verification report without running anything.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_package",
            "description": "Build the final DOMjudge ZIP. Refused unless the last verification report is verified.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
]

ALLOWED = {"python", "python3", "g++", "gcc", "javac", "java", "pdflatex", "latexmk"}
META = re.compile(r"[;&|<>`$\n\r]")


def _tool_text(value, limit: int = 24000) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, indent=2)
    if len(value) > limit:
        value = value[:limit] + f"\n... [truncated, {len(value) - limit} more characters]"
    return value


def _clean_command(slug: str, raw: str) -> tuple[list[str], pathlib.Path]:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("A command is required")
    if META.search(raw):
        raise ValueError("Shell operators, redirection and substitution are not allowed")
    try:
        argv = shlex.split(raw, posix=True)
    except ValueError as exc:
        raise ValueError(f"Could not parse command: {exc}") from exc
    if not argv:
        raise ValueError("A command is required")
    name = pathlib.Path(argv[0]).name.lower()
    if name.endswith(".exe"):
        name = name[:-4]
    root = workspace.ws_path(slug)
    if name not in ALLOWED:
        candidate = pathlib.Path(argv[0])
        resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
        if resolved.is_relative_to(root) and resolved.is_file() and resolved.suffix.lower() in (".exe", ".bin"):
            argv[0] = str(resolved)
        else:
            raise ValueError(f"Command not allowed: {argv[0]}. Allowed: {', '.join(sorted(ALLOWED))}, or a compiled binary inside the workspace")
    if name in ("python", "python3"):
        argv[0] = sys.executable
    for index, token in enumerate(argv[1:], start=1):
        value = token
        if "=" in value and value.startswith("-"):
            value = value.split("=", 1)[1]
        if not value or value.startswith("-") or value in ("|", "&", ";", ">", "<"):
            continue
        looks_like_path = "/" in value or "\\" in value or pathlib.Path(value).suffix.lower() in {
            ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".py", ".java", ".class",
            ".exe", ".in", ".ans", ".tex", ".pdf", ".txt", ".aux", ".log", ".zip",
        }
        if not looks_like_path:
            continue
        path = pathlib.Path(value)
        if path.is_absolute():
            if not path.resolve().is_relative_to(root):
                raise ValueError(f"Path is outside the workspace: {value}")
        else:
            resolved = (root / path).resolve()
            if not resolved.is_relative_to(root):
                raise ValueError(f"Path escapes the workspace: {value}")
    return argv, root


def _dispatch(slug: str, name: str, args: dict, emit) -> dict:
    if name == "list_files":
        rel = str(args.get("path") or ".")
        prefix = "" if rel in (".", "") else rel.replace("\\", "/").strip("/") + "/"
        rows = [row for row in workspace.tree(slug) if row["path"].startswith(prefix)]
        return {"path": rel, "entries": rows[:800], "count": len(rows)}
    if name == "read_file":
        return workspace.read_text(slug, args["path"])
    if name == "write_file":
        result = workspace.write_text(slug, args["path"], args.get("content", ""), source="agent")
        if result.get("diff"):
            emit("change", {"path": result["path"], "diff": result["diff"][:12000], "changeId": result["change"]["id"]})
        return {
            "path": result["path"],
            "changed": result["changed"],
            "changeId": result["change"]["id"] if result.get("change") else None,
            "diff": (result.get("diff") or "")[:8000],
        }
    if name == "delete_file":
        result = workspace.delete_file(slug, args["path"], source="agent")
        emit("change", {"path": result["path"], "diff": result["diff"][:12000], "changeId": result["change"]["id"]})
        return {"path": result["path"], "deleted": True, "changeId": result["change"]["id"]}
    if name == "run_command":
        argv, root = _clean_command(slug, args.get("command", ""))
        (root / "build").mkdir(exist_ok=True)
        (root / "tmp").mkdir(exist_ok=True)
        workdir = root
        if isinstance(args.get("cwd"), str) and args["cwd"].strip() not in ("", "."):
            workdir = workspace.resolve(slug, args["cwd"])
            if not workdir.is_dir():
                raise ValueError("cwd is not a directory")
        tex_env = str(TEMPLATES) + os.pathsep + os.environ.get("TEXINPUTS", "")
        try:
            timeout = float(args.get("timeout_seconds") or 30)
        except (TypeError, ValueError):
            timeout = 30.0
        timeout = max(1.0, min(120.0, timeout))
        stdin = args.get("stdin")
        data = stdin.encode("utf-8") if isinstance(stdin, str) and stdin else b""
        child_env = winutil.python_env()
        child_env["TEXINPUTS"] = tex_env
        result = winutil.run_captured(argv, workdir, data=data, timeout=timeout, env=child_env)
        saved = None
        if isinstance(args.get("stdout_path"), str) and args["stdout_path"].strip():
            saved = workspace.write_text(slug, args["stdout_path"], result["stdout"].decode("utf-8", "replace"), source="agent")
            if saved.get("diff"):
                emit("change", {"path": saved["path"], "diff": saved["diff"][:12000], "changeId": saved["change"]["id"]})
        return {
            "command": argv,
            "exitCode": result["returncode"],
            "timedOut": result["timedOut"],
            "ms": round(result["ms"], 1),
            "stdout": _tool_text(result["stdout"]) if not saved else f"[stdout saved to {saved['path']}]",
            "stderr": _tool_text(result["stderr"]),
            "savedTo": saved["path"] if saved else None,
            "stdin": stdin or "",
            "diagnostic": "The command exceeded its time limit and was stopped." if result["timedOut"] else winutil.diagnostic(result["returncode"]),
        }
    if name == "build_answers":
        result = verify.build_answers(slug)
        emit("verification", {"stage": "answers", "result": result})
        return result
    if name == "verify_package":
        value = args.get("write_answers")
        write_answers = value is True or str(value).lower() in ("true", "1", "yes")
        result = verify.verify(slug, write_answers=write_answers)
        emit("verification", {"stage": "verify", "result": result})
        return {
            "status": result["status"],
            "errors": result["errors"],
            "warnings": result["warnings"],
            "counts": result["counts"],
            "tests": result["tests"],
            "negative": result["negative"],
            "checks": result["checks"],
        }
    if name == "read_report":
        report = workspace.state(slug).get("lastReport")
        return report or {"status": "none", "detail": "No verification has run yet"}
    if name == "export_package":
        return verify.export_package(slug)
    raise ValueError(f"Unknown tool: {name}")


def _provider_call(cfg: dict, messages: list[dict], tools: list[dict]) -> dict:
    if not cfg.get("apiKey"):
        raise RuntimeError("No API key is configured. Open Settings and add a DeepSeek or OpenRouter key.")
    base = str(cfg.get("baseUrl") or "").rstrip("/")
    if not base:
        raise RuntimeError("No provider base URL is configured")
    url = base if base.endswith("/chat/completions") else base + "/chat/completions"
    body = {
        "model": cfg.get("model"),
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": float(cfg.get("temperature", 0.2)),
        "max_tokens": 8000,
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": "Bearer " + str(cfg.get("apiKey")),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if "openrouter" in base:
        headers["HTTP-Referer"] = "http://127.0.0.1"
        headers["X-Title"] = "ICPC Author Agent"
    last_error = None
    for attempt in range(2):
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict) or "choices" not in payload:
                raise RuntimeError("Provider returned an unexpected response: " + _tool_text(payload, 1200))
            return payload
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            last_error = f"Provider HTTP {exc.code}: {detail[:2000]}"
            if exc.code in (429, 500, 502, 503) and attempt == 0:
                time.sleep(2)
                continue
            break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = f"Provider request failed: {exc}"
            if attempt == 0:
                time.sleep(2)
                continue
            break
    raise RuntimeError(last_error or "Provider request failed")


def _history_path(slug: str) -> pathlib.Path:
    return workspace.ws_path(slug) / ".agent" / "conversation.json"


def _load_history(slug: str) -> list[dict]:
    try:
        value = json.loads(_history_path(slug).read_text("utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, ValueError):
        return []


def _window(messages: list[dict], budget: int = 180000) -> list[dict]:
    """Keep the current user turn intact and as much older history as fits."""
    if not messages:
        return []
    system = messages[0]
    rest = messages[1:]
    last_user = max((i for i, m in enumerate(rest) if m.get("role") == "user"), default=0)
    head, tail = rest[:last_user], rest[last_user:]
    total = len(json.dumps(system, ensure_ascii=False)) + sum(len(json.dumps(m, ensure_ascii=False)) for m in tail)
    selected = []
    for message in reversed(head):
        size = len(json.dumps(message, ensure_ascii=False))
        if selected and total + size > budget:
            break
        selected.append(message)
        total += size
    selected.reverse()
    while selected and selected[0].get("role") != "user":
        selected.pop(0)
    return [system] + selected + tail


def _save_history(slug: str, messages: list[dict]) -> None:
    trimmed = _window(messages, budget=120000)
    if len(trimmed) > 1:
        trimmed = trimmed[1:]
    else:
        trimmed = []
    path = _history_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(trimmed, ensure_ascii=False, indent=2), "utf-8")


def _state_note(slug: str) -> str:
    summary = workspace.summary(slug)
    report = summary.get("lastReport") or {}
    meta = summary.get("meta", {})
    lines = [
        "WORKSPACE STATE",
        f"- Name: {meta.get('name', slug)}",
        f"- Idea: {meta.get('idea', '')[:600]}",
        f"- Last verification: {report.get('status', 'never')} at {report.get('at', '-')}",
        f"- Unreviewed changes: {summary.get('unreviewed', 0)}",
    ]
    if report.get("errors"):
        lines.append("- Current verification errors: " + "; ".join(str(e) for e in report["errors"])[:2000])
    return "\n".join(lines)


def run_turn(slug: str, user_message: str, emit) -> dict:
    winutil.prepare()
    cfg = config.load()
    messages = _load_history(slug)
    messages.append({"role": "user", "content": str(user_message)[:20000]})
    transcript = [{"role": "system", "content": SYSTEM + "\n\n" + _state_note(slug), "hidden": True}]
    convo = transcript + messages
    max_rounds = int(cfg.get("maxToolRounds", 24))
    final_text = ""
    try:
        for round_index in range(max_rounds):
            emit("thinking", {"round": round_index + 1})
            payload = _provider_call(cfg, [{"role": m["role"], "content": m.get("content") or "", **({"tool_calls": m["tool_calls"]} if m.get("tool_calls") else {}), **({"tool_call_id": m["tool_call_id"]} if m.get("tool_call_id") else {})} for m in _window(convo)], TOOLS)
            choice = (payload.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            tool_calls = message.get("tool_calls") or []
            reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
            if isinstance(reasoning, list):
                reasoning = "\n".join(str(part) for part in reasoning)
            assistant = {"role": "assistant", "content": message.get("content") or ""}
            if reasoning:
                assistant["reasoning"] = str(reasoning)
            if tool_calls:
                assistant["tool_calls"] = tool_calls
            convo.append(assistant)
            messages.append(assistant)
            _save_history(slug, messages)
            if assistant.get("reasoning"):
                emit("reasoning", {"text": assistant["reasoning"]})
            if assistant["content"]:
                emit("assistant", {"text": assistant["content"]})
                final_text = assistant["content"]
            if not tool_calls:
                break
            for call in tool_calls:
                fn = call.get("function") or {}
                name = fn.get("name") or ""
                raw_args = fn.get("arguments") or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                    if not isinstance(args, dict):
                        raise ValueError("Tool arguments must be an object")
                except (ValueError, TypeError) as exc:
                    result = {"error": f"Invalid tool arguments: {exc}"}
                    args = {}
                else:
                    emit("tool_call", {"name": name, "args": args})
                    try:
                        result = _dispatch(slug, name, args, emit)
                    except Exception as exc:  # noqa: BLE001 - surfaced to the model
                        result = {"error": f"{type(exc).__name__}: {exc}"}
                emit("tool_result", {"name": name, "result": result})
                content = _tool_text(result, 8000)
                tool_message = {"role": "tool", "tool_call_id": call.get("id") or "missing", "content": content}
                convo.append(tool_message)
                messages.append(tool_message)
                _save_history(slug, messages)
        else:
            final_text = final_text or "Stopped after the maximum number of tool rounds. Inspect the changes and continue."
            emit("assistant", {"text": final_text})
        if not final_text:
            final_text = "The model returned no text. Check the tool activity, then tell it what to do next."
            emit("assistant", {"text": final_text})
        _save_history(slug, messages)
        return {"text": final_text, "rounds": round_index + 1}
    except Exception as exc:  # noqa: BLE001 - job surfaces provider/tool failure
        _save_history(slug, messages)
        emit("error", {"error": str(exc)})
        raise
