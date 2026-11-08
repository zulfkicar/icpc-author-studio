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
import sys

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

LIMITS: never choose time or memory limits when creating the problem. The workspace starts with provisional defaults. Only after the reference solution and tests are ready, build answers, then call measure_limits. It runs the accepted references on every test and writes measured limits to problem.yaml, domjudge-problem.ini and the statement. Verification will not pass until limits are measured.

PLANNING AND MEMORY: use write_todos for the current operational task list. Use update_brief for a concise durable brief, record_decision for setter interpretations, and set_focus for the current one-line objective. Use search_workspace and read_file with optional start_line/end_line to keep context small; use list_tests and report_summary for compact evidence. Keep the todo list current. Use review_package for an independent, proposal-only review when useful; it cannot read secret tests or answers and cannot approve or export.

APPROVAL: export_package is human-gated. If review mode is enabled, write_file and delete_file are also human-gated. Approval is handled by the runtime; never claim an action was approved, and never try to bypass the gate. The deterministic verifier and snapshot/review gates remain the authority.

NEGATIVE SOLUTIONS: a negative solution must be genuinely wrong for the stated constraints. If the verifier says a negative solution survives because it is actually correct for those constraints, remove it or replace it with a different genuinely wrong solution. Never weaken tests or constraints just to kill a solution. Use the verifier's exact error and report as the next check.
"""

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
        result = workspace.read_text(slug, args["path"])
        if result.get("text"):
            start = args.get("start_line")
            end = args.get("end_line")
            if start is not None or end is not None:
                lines = result.get("content", "").splitlines(keepends=True)
                try:
                    first = max(1, int(start or 1))
                    last = min(len(lines), int(end or len(lines)))
                except (TypeError, ValueError):
                    raise ValueError("start_line and end_line must be integers")
                if first > last:
                    raise ValueError("start_line must not exceed end_line")
                result["content"] = "".join(lines[first - 1:last])
                result["range"] = {"start": first, "end": last, "totalLines": len(lines)}
        return result
    if name == "search_workspace":
        query = str(args.get("query") or "").strip()
        if not query:
            raise ValueError("A search query is required")
        pattern = str(args.get("glob") or "*")
        try:
            max_results = max(1, min(100, int(args.get("max_results", 40))))
        except (TypeError, ValueError):
            max_results = 40
        matches = []
        import fnmatch
        for row in workspace.tree(slug):
            if row["type"] != "file" or not row.get("text"):
                continue
            if not fnmatch.fnmatch(row["path"], pattern):
                continue
            try:
                text = workspace.read_text(slug, row["path"]).get("content") or ""
            except Exception:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if query.lower() in line.lower():
                    matches.append({"path": row["path"], "line": number, "text": line.strip()[:240]})
                    if len(matches) >= max_results:
                        break
            if len(matches) >= max_results:
                break
        return {"query": query, "matches": matches, "count": len(matches), "truncated": len(matches) >= max_results}
    if name == "list_tests":
        rows = workspace.tree(slug)
        sample = [r["path"] for r in rows if r["type"] == "file" and r["path"].startswith("data/sample/") and r["path"].endswith(".in")]
        secret = [r["path"] for r in rows if r["type"] == "file" and r["path"].startswith("data/secret/") and r["path"].endswith(".in")]
        return {"sample": sample, "secret": secret, "sampleCount": len(sample), "secretCount": len(secret)}
    if name == "report_summary":
        report = workspace.state(slug).get("lastReport") or {"status": "none"}
        return {
            "status": report.get("status", "none"),
            "errors": (report.get("errors") or [])[:12],
            "warnings": (report.get("warnings") or [])[:8],
            "counts": report.get("counts") or {},
            "limits": report.get("limits") or {},
            "checks": [{"name": c.get("name"), "status": c.get("status"), "detail": str(c.get("detail"))[:300]} for c in (report.get("checks") or [])],
        }
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
    if name == "measure_limits":
        result = verify.measure_limits(slug)
        emit("limits", result)
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
