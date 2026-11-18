"""Local Author Studio services shared by the chat and package workbench."""
import hashlib
from contextlib import nullcontext
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import threading

import workspace
from config import STATE_DIR
from problem_titles import validate_title


LINK_LOCK = threading.Lock()


class EditConflict(ValueError):
    """A title or package selection changed after it was presented."""


def package_link(service, run_id):
    service.store(run_id).get_run(run_id)
    path = service.base_root / "runs" / run_id / "studio-package.json"
    try:
        return json.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        return {"slug": None}


def _link_basis(link, title):
    return {"expectedSlug": link["slug"], "expectedSyncTitle": link.get("syncTitle", True),
            "expectedTitle": title}


def _check_basis(body, basis):
    for key, current in basis.items():
        if key in body and body[key] != current:
            label = basis.get("expectedPackageTitle") or basis.get("expectedTitle") or "Untitled problem"
            raise EditConflict(f'The saved title or package changed. Current name: “{label}”. Review the updated preview.')


def _package_basis(slug):
    return {"expectedSnapshot": workspace.snapshot_hash(slug),
            "expectedPackageTitle": workspace.state(slug).get("meta", {}).get("name") or slug}


def _title_impact(slug, title, run_id):
    st = workspace.state(slug)
    owner = st.get("titleOwner")
    if owner not in (None, run_id):
        return {"syncBlocked": "This package already follows the title of another conversation."}
    try:
        edits, statement_supported = workspace.problem_title_edits(slug, title)
    except ValueError:
        return {"syncBlocked": "The imported title files could not be read. Keep the existing package name or inspect those files."}
    return {"files": [rel for rel, *_ in edits], "statementSupported": statement_supported,
            "filename": workspace.export_filename(slug, title),
            "requiresVerification": bool(st.get("lastReport") and edits)}


def problem_preview(service, run_id, body, workspace_lock, *, linking=False):
    with LINK_LOCK:
        link = package_link(service, run_id)
        current = service.store(run_id).get_run(run_id)["title"]
        basis = _link_basis(link, current)
        slug = body.get("slug") if linking else link["slug"]
        if not slug:
            return {"basis": basis}
        slug = workspace.safe_slug(slug)
        if not workspace.ws_path(slug).is_dir():
            raise FileNotFoundError("Workspace not found")
        with workspace_lock(slug):
            basis.update(_package_basis(slug))
            result = {"basis": basis, "packageTitle": basis["expectedPackageTitle"],
                      "filename": workspace.export_filename(slug)}
            proposed = current if linking else validate_title(body.get("title"))
            if not linking and link.get("syncTitle", True) is False:
                result["separate"] = True
            elif proposed and (linking or proposed != current):
                result.update(_title_impact(slug, proposed, run_id))
            return result


def link_package(service, run_id, body, workspace_lock):
    with LINK_LOCK:
        link = package_link(service, run_id)
        title = service.store(run_id).get_run(run_id)["title"]
        if "syncTitle" not in body and "expectedTitle" not in body:
            if "expectedSlug" in body and link["slug"] != body["expectedSlug"]:
                raise ValueError("The linked package changed. Close and reopen package setup.")
            if link["slug"] and ("expectedSlug" not in body or body.get("slug") == link["slug"]):
                return link
        _check_basis(body, _link_basis(link, title))
        slug = body.get("slug")
        sync = body.get("syncTitle", True)
        if not isinstance(sync, bool):
            raise ValueError("Choose whether the package follows the problem title.")
        assign_title = False
        if slug:
            if not workspace.ws_path(slug).is_dir():
                raise FileNotFoundError("Workspace not found")
            slug = workspace.safe_slug(slug)
        else:
            sync = True
            if "syncTitle" in body and not title:
                title = validate_title(body.get("name"))
                assign_title = True
            slug = workspace.create(title or str(body.get("name") or "")[:120])["slug"]
        path = service.base_root / "runs" / run_id / "studio-package.json"
        temp = path.with_suffix(".tmp")
        result = {"slug": slug}
        if not sync:
            result["syncTitle"] = False
        with workspace_lock(slug):
            if body.get("slug"):
                _check_basis(body, _package_basis(slug))
            with (workspace.use_problem_title(slug, title, run_id) if title and sync else nullcontext()):
                temp.write_text(json.dumps(result), encoding="utf-8")
                if assign_title:
                    service.rename_run(run_id, title)
                temp.replace(path)
        return result


def rename_problem(service, run_id, body, workspace_lock):
    title = validate_title(body.get("title"))
    with LINK_LOCK:
        link = package_link(service, run_id)
        slug = link["slug"]
        current = service.store(run_id).get_run(run_id)["title"]
        _check_basis(body, _link_basis(link, current))
        if title == current:
            return {"runId": run_id, "title": current}
        if slug and link.get("syncTitle", True):
            with workspace_lock(slug):
                _check_basis(body, _package_basis(slug))
                with workspace.use_problem_title(slug, title, run_id):
                    return service.rename_run(run_id, title)
        return service.rename_run(run_id, title)


def file_hash(slug, rel):
    path = workspace.resolve(slug, rel)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def require_snapshot(slug, body):
    return workspace.require_snapshot(slug, body.get("expectedSnapshot"))


def _tool(name):
    if name in ("clang-format", "ruff"):
        root = pathlib.Path(os.environ.get("AUTHOR_AGENT_EDITOR_TOOLS") or STATE_DIR / "editor-tools")
        binary = name + (".exe" if os.name == "nt" else "")
        relative = pathlib.Path("clang_format/data/bin") if name == "clang-format" else pathlib.Path("bin")
        candidate = (root / relative / binary).resolve()
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


def _process(args, text):
    with tempfile.TemporaryDirectory(prefix="author-studio-") as directory:
        process = subprocess.run(
            args, input=text.encode("utf-8"), capture_output=True, timeout=12, cwd=directory,
        )
    return process.returncode, process.stdout.decode("utf-8", "replace"), process.stderr.decode("utf-8", "replace")


def _diagnostic(line, column, severity, message):
    return {"line": line, "column": column, "severity": severity, "message": message}


def editor_tool(body):
    """Check or format submitted text. Tool choice and options belong to the host."""
    path = pathlib.PurePosixPath(workspace.validate_rel(body.get("path")))
    text = body.get("content")
    operation = body.get("operation")
    if not isinstance(text, str) or len(text.encode("utf-8")) > 256 * 1024:
        raise ValueError("Editor tools accept up to 256 KiB of text.")
    if operation not in ("format", "check"):
        raise ValueError("Unknown editor operation.")
    ext = path.suffix.lower()
    if ext == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            if operation == "format":
                raise ValueError(f"JSON {exc.lineno}:{exc.colno}: {exc.msg}") from exc
            return {"tool": "JSON", "diagnostics": [_diagnostic(exc.lineno, exc.colno, "error", exc.msg)]}
        if operation == "format":
            # Preserve number lexemes and duplicate keys in strict JSON.
            return {"tool": "JSON", "content": _format_json(text)}
        return {"tool": "JSON", "diagnostics": []}
    if ext == ".py":
        command = _tool("ruff")
        args = [command, "format", "--isolated", "--stdin-filename", "draft.py", "-"] if operation == "format" else [
            command, "check", "--isolated", "--output-format", "json", "--stdin-filename", "draft.py", "-",
        ]
        label = "Ruff"
    elif ext in (".cpp", ".cc", ".cxx", ".c", ".h", ".hpp"):
        is_c = ext == ".c"
        if operation == "format":
            command = _tool("clang-format")
            label = "clang-format"
            args = [command, "--style=LLVM", "--fail-on-incomplete-format", "--assume-filename=draft" + ext]
        else:
            command = _tool("gcc" if is_c else "g++")
            label = "GCC compiler warnings"
            args = [command, "-fsyntax-only", "-Wall", "-Wextra", "-fdiagnostics-color=never",
                    "-std=c17" if is_c else "-std=c++17", "-x", "c" if is_c else "c++", "-"]
    else:
        return {"available": False, "reason": f"No {operation} tool is configured for {ext or 'this file type'}."}
    if not command:
        return {"available": False, "reason": f"{label} is unavailable on the server. Install its CLI on PATH."}
    try:
        code, stdout, stderr = _process(args, text)
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"{label} exceeded its 12 second limit.") from exc
    if operation == "format":
        if code:
            raise ValueError(stderr[:2000] or f"{label} could not format this draft.")
        return {"tool": label, "content": stdout}
    if ext == ".py" and code in (0, 1):
        diagnostics = [
            _diagnostic(item["location"]["row"], item["location"]["column"], "warning",
                        f'{item["code"]}: {item["message"]}')
            for item in json.loads(stdout)
        ]
    else:
        diagnostics = [
            _diagnostic(int(line), int(column or 1), "error" if "error" in kind else "warning", message)
            for line, column, kind, message in re.findall(
                r"^<stdin>:(\d+)(?::(\d+))?: (fatal error|error|warning): (.+)$", stderr, re.M
            )
        ]
        if code and not diagnostics:
            raise ValueError(stderr[:2000] or f"{label} could not check this draft.")
    return {"tool": label, "diagnostics": diagnostics[:200]}


def _format_json(text):
    # The tokenizer ignores whitespace only outside strings. Validation has
    # already happened, so this changes layout without reserializing values.
    tokens = re.findall(r'"(?:[^"\\]|\\.)*"|[{}\[\],:]|[^\s{}\[\],:"]+', text)
    out = []
    depth = 0
    previous = ""
    for token in tokens:
        if token in ("}", "]"):
            depth -= 1
            if previous not in ("{", "["):
                out.append("\n" + "  " * depth)
        elif previous in ("{", "[", ","):
            out.append("\n" + "  " * depth)
        out.append(token + (" " if token == ":" else ""))
        if token in ("{", "["):
            depth += 1
        previous = token
    return "".join(out) + "\n"
