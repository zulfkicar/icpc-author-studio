"""Safe file operations and change tracking for one problem workspace.

The agent never gets a raw shell rooted at the user's machine. Every path is
resolved inside a workspace, text writes are recorded as reviewable changes,
and the UI can inspect or revert each change.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import pathlib
import re
import threading
import time
import uuid

from config import TEMPLATES, WORKSPACES

_LOCK = threading.RLock()

TEXT_EXT = {
    ".in", ".ans", ".interaction", ".out", ".txt", ".md", ".markdown",
    ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".py", ".java", ".kt",
    ".tex", ".sty", ".cls", ".yaml", ".yml", ".ini", ".json", ".csv",
    ".sh", ".html", ".js", ".css", ".tmpl", ".cfg", ".conf", ".log",
}
SKIP_DIRS = {".agent", ".git", "__pycache__", "node_modules", ".venv", "build", "tmp"}
MAX_FILE = 2 * 1024 * 1024


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return (slug or "problem")[:48]


def validate_rel(rel: str) -> str:
    rel = str(rel or "").replace("\\", "/").strip()
    if not rel or rel.startswith("/"):
        raise ValueError("A relative path is required")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise ValueError("Path escapes the workspace")
    if parts[0] == ".agent":
        raise ValueError("The .agent directory is managed by the app")
    if any(p in SKIP_DIRS for p in parts):
        raise ValueError("That directory is not an authoring path")
    return "/".join(parts)


def ws_path(slug: str) -> pathlib.Path:
    slug = safe_slug(slug)
    path = (WORKSPACES / slug).resolve()
    if not path.is_relative_to(WORKSPACES.resolve()):
        raise ValueError("Invalid workspace")
    return path


def resolve(slug: str, rel: str, *, allow_state: bool = False) -> pathlib.Path:
    root = ws_path(slug)
    if not root.is_dir():
        raise FileNotFoundError("Workspace not found")
    if allow_state:
        rel = str(rel or "").replace("\\", "/").lstrip("/")
        if ".." in pathlib.PurePosixPath(rel).parts:
            raise ValueError("Path escapes the workspace")
    else:
        rel = validate_rel(rel)
    target = (root / rel).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Path escapes the workspace")
    return target


def _read_json(path: pathlib.Path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return default


def _write_json(path: pathlib.Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, indent=2)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(data, "utf-8")
        tmp.replace(path)
    except OSError:
        # Some mounted filesystems reject atomic replace; fall back to a direct write.
        path.write_text(data, "utf-8")
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _state_dir(slug: str) -> pathlib.Path:
    path = ws_path(slug) / ".agent"
    path.mkdir(parents=True, exist_ok=True)
    return path


def state(slug: str) -> dict:
    return _read_json(_state_dir(slug) / "state.json", {})


def _save_state(slug: str, value: dict) -> None:
    _write_json(_state_dir(slug) / "state.json", value)


def is_text(path: pathlib.Path) -> bool:
    if path.suffix.lower() in TEXT_EXT:
        return True
    try:
        chunk = path.read_bytes()[:4096]
    except OSError:
        return False
    return b"\x00" not in chunk


def list_workspaces() -> list[dict]:
    items = []
    if not WORKSPACES.is_dir():
        return items
    for folder in sorted(WORKSPACES.iterdir()):
        if not folder.is_dir():
            continue
        st = state(folder.name)
        meta = st.get("meta", {})
        items.append({
            "slug": folder.name,
            "name": meta.get("name") or folder.name.replace("-", " ").title(),
            "created": meta.get("created"),
            "idea": meta.get("idea", ""),
            "status": st.get("lastStatus", "unverified"),
        })
    return items


def create(name: str, idea: str = "", meta: dict | None = None) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("A problem name is required")
    base = safe_slug(name)
    slug = base
    counter = 2
    while (WORKSPACES / slug).exists():
        slug = f"{base}-{counter}"
        counter += 1
    root = WORKSPACES / slug
    root.mkdir(parents=True)
    meta = dict(meta or {})
    author = str(meta.get("author") or "Author")
    short = str(meta.get("shortName") or "A")[:4]
    timelimit = str(meta.get("timeLimit") or "2")
    memory = str(meta.get("memoryMb") or "256")
    source = str(meta.get("source") or "Local practice")
    license_name = str(meta.get("license") or "educational")
    rights = str(meta.get("rightsOwner") or author)
    color = str(meta.get("color") or "#000000")

    def sub(text: str) -> str:
        values = {
            "{{PROBLEM_NAME}}": name,
            "{{PROBLEM_ID}}": short,
            "{{AUTHOR}}": author,
            "{{TIME_LIMIT}}": f"{timelimit} seconds",
            "{{MEMORY_LIMIT}}": f"{memory} MiB",
            "{{SOURCE}}": source,
            "{{LICENSE}}": license_name,
            "{{RIGHTS_OWNER}}": rights,
            "{{MEMORY_MB}}": memory,
            "{{TIME_LIMIT_SECONDS}}": timelimit,
            "{{SHORT_NAME}}": short,
            "{{COLOR}}": color,
            "{{PROBLEM_DESCRIPTION}}": "Describe the task here.",
            "{{INPUT_DESCRIPTION}}": "Describe the input format here.",
            "{{OUTPUT_DESCRIPTION}}": "Describe the output format here.",
            "{{CONSTRAINTS}}": r"\item Replace with the real constraints.",
            "{{NOTES}}": "Replace with notes, if any.",
        }
        for key, value in values.items():
            text = text.replace(key, value)
        return text

    template_files = {
        "problem.yaml": TEMPLATES / "problem.yaml",
        "domjudge-problem.ini": TEMPLATES / "domjudge-problem.ini",
        "data/testdata.yaml": TEMPLATES / "testdata.yaml",
        "problem_statement/problem.en.tex": TEMPLATES / "problem_statement" / "problem.en.tex",
        "data/sample/01.in": TEMPLATES / "data" / "sample" / "01.in",
        "data/sample/01.ans": TEMPLATES / "data" / "sample" / "01.ans",
    }
    for rel, src in template_files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(sub(src.read_text("utf-8")).encode("utf-8"))

    for rel in (
        "data/secret/.keep", "submissions/accepted/.keep",
        "submissions/wrong_answer/.keep", "input_validators/.keep",
        "output_validators/.keep", "generators/.keep",
    ):
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", "utf-8")

    notes = [
        f"# {name}",
        "",
        f"- Author: {author}",
        f"- Time limit: {timelimit} s",
        f"- Memory limit: {memory} MiB",
        "",
        "## Idea",
        "",
        idea.strip() or "Not written yet.",
        "",
        "## Required package layout",
        "",
        "- `problem_statement/problem.en.tex` and a compiled `problem.pdf`",
        "- `data/sample/*.in|.ans` and `data/secret/*.in|.ans`",
        "- `input_validators/validate.py` (exit 42 for valid input)",
        "- `submissions/accepted/` with at least one reference solution",
        "- `submissions/wrong_answer/` with at least one deliberately wrong solution",
        "- `generators/` for any generator source used to produce secret inputs",
        "- `problem.yaml` and `domjudge-problem.ini` with limits",
        "",
        "## Author checklist",
        "",
        "- [ ] Statement is complete and unambiguous",
        "- [ ] Constraints are enforced by the validator",
        "- [ ] Samples match the sample files",
        "- [ ] Secret tests cover all constraints and edge cases",
        "- [ ] Answers are generated from the reference solution",
        "- [ ] Wrong solutions are killed by at least one secret test",
        "- [ ] Package verification is green",
        "",
    ]
    (root / "NOTES.md").write_text("\n".join(notes), "utf-8")

    st = {
        "meta": {
            "name": name,
            "idea": idea,
            "created": now(),
            "author": author,
            "shortName": short,
            "timeLimit": timelimit,
            "memoryMb": memory,
        },
        "lastStatus": "unverified",
        "lastReport": None,
        "lastReview": None,
    }
    _save_state(slug, st)
    _write_json(_state_dir(slug) / "changes.json", [])
    return summary(slug)


def summary(slug: str) -> dict:
    st = state(slug)
    report = st.get("lastReport")
    stale = bool(report and report.get("snapshot") and report.get("snapshot") != snapshot_hash(slug))
    status = "stale" if stale else st.get("lastStatus", "unverified")
    return {
        "slug": safe_slug(slug),
        "meta": st.get("meta", {}),
        "lastStatus": status,
        "lastReport": report,
        "lastReview": st.get("lastReview"),
        "stale": stale,
        "unreviewed": sum(1 for c in changes(slug) if not c.get("reviewed") and not c.get("reverted")),
        "tree": tree(slug),
    }


def tree(slug: str) -> list[dict]:
    root = ws_path(slug)
    out = []

    def walk(folder: pathlib.Path, prefix: str = "") -> None:
        try:
            entries = sorted(folder.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError:
            return
        for entry in entries:
            if entry.name in SKIP_DIRS or entry.name == ".keep":
                continue
            rel = f"{prefix}{entry.name}"
            if entry.is_dir():
                out.append({"path": rel, "type": "dir"})
                walk(entry, rel + "/")
            else:
                if entry.suffix.lower() in (".aux", ".log", ".out", ".toc") or entry.name.endswith(".synctex.gz"):
                    continue
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = 0
                out.append({"path": rel, "type": "file", "size": size, "text": is_text(entry)})

    walk(root)
    return out


def read_text(slug: str, rel: str) -> dict:
    path = resolve(slug, rel)
    if not path.is_file():
        raise FileNotFoundError("File not found")
    size = path.stat().st_size
    if size > MAX_FILE:
        raise ValueError(f"File is larger than {MAX_FILE // 1024} KiB")
    if not is_text(path):
        return {"path": rel, "text": False, "size": size, "content": ""}
    return {"path": rel, "text": True, "size": size, "content": path.read_text("utf-8", errors="replace")}


def _changes_path(slug: str) -> pathlib.Path:
    return _state_dir(slug) / "changes.json"


def changes(slug: str) -> list[dict]:
    return _read_json(_changes_path(slug), [])


def _line_stats(before: str | None, after: str | None) -> tuple[int, int]:
    old = (before or "").splitlines()
    new = (after or "").splitlines()
    added = removed = 0
    for line in difflib.unified_diff(old, new, lineterm=""):
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


def _record(slug: str, action: str, rel: str, before: str | None, after: str | None, source: str) -> dict:
    with _LOCK:
        items = changes(slug)
        added, removed = _line_stats(before, after)
        entry = {
            "id": uuid.uuid4().hex[:12],
            "at": now(),
            "source": source,
            "action": action,
            "path": rel,
            "before": before,
            "after": after,
            "additions": added,
            "deletions": removed,
            "reviewed": False,
            "reverted": False,
        }
        items.append(entry)
        if len(items) > 400:
            items = items[-400:]
        _write_json(_changes_path(slug), items)
        return entry


def write_text(slug: str, rel: str, content: str, source: str = "agent") -> dict:
    rel = validate_rel(rel)
    if not isinstance(content, str):
        raise ValueError("Text content is required")
    if len(content.encode("utf-8")) > MAX_FILE:
        raise ValueError("Content is too large")
    path = resolve(slug, rel)
    before = path.read_text("utf-8", errors="replace") if path.is_file() else None
    if before == content:
        return {"path": rel, "changed": False, "change": None}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, "utf-8", newline="")
    entry = _record(slug, "write", rel, before, content, source)
    return {"path": rel, "changed": True, "change": entry, "diff": diff(before or "", content, rel)}


def delete_file(slug: str, rel: str, source: str = "agent") -> dict:
    rel = validate_rel(rel)
    path = resolve(slug, rel)
    if not path.is_file():
        raise FileNotFoundError("File not found")
    before = path.read_text("utf-8", errors="replace")
    path.unlink()
    entry = _record(slug, "delete", rel, before, None, source)
    return {"path": rel, "changed": True, "change": entry, "diff": diff(before, "", rel)}


def revert(slug: str, change_id: str) -> dict:
    items = changes(slug)
    entry = next((c for c in items if c["id"] == change_id), None)
    if entry is None:
        raise FileNotFoundError("Change not found")
    if entry.get("reverted"):
        raise ValueError("Change was already reverted")
    position = next(i for i, c in enumerate(items) if c["id"] == entry["id"])
    later = [c for c in items[position + 1:] if c["path"] == entry["path"] and not c.get("reverted")]
    if later:
        raise ValueError("A newer change exists for this file; revert that one first")
    path = resolve(slug, entry["path"])
    if entry["action"] == "delete":
        if entry.get("before") is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(entry["before"], "utf-8", newline="")
    elif entry.get("before") is None:
        if path.is_file():
            path.unlink()
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(entry["before"], "utf-8", newline="")
    entry["reverted"] = True
    _write_json(_changes_path(slug), items)
    return entry


def mark_reviewed(slug: str) -> dict:
    items = changes(slug)
    for entry in items:
        if not entry.get("reverted"):
            entry["reviewed"] = True
    _write_json(_changes_path(slug), items)
    st = state(slug)
    st["lastReview"] = now()
    _save_state(slug, st)
    return {"reviewed": sum(1 for c in items if c.get("reviewed") and not c.get("reverted")), "at": st["lastReview"]}


def _chats_root(slug: str) -> pathlib.Path:
    path = _state_dir(slug) / "chats"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _chats_index_path(slug: str) -> pathlib.Path:
    return _state_dir(slug) / "chats.json"


def _chat_file(slug: str, chat_id: str) -> pathlib.Path:
    if not re.fullmatch(r"[a-f0-9]{12}", str(chat_id or "")):
        raise ValueError("Invalid chat id")
    return _chats_root(slug) / f"{chat_id}.json"


def _chat_title(messages: list[dict]) -> str:
    for message in messages:
        if message.get("role") != "user":
            continue
        text = " ".join(str(message.get("content") or "").split())
        if text:
            return text[:70] + ("..." if len(text) > 70 else "")
    return "New chat"


def _save_chats_index(slug: str, index: dict) -> None:
    _write_json(_chats_index_path(slug), index)


def ensure_chats(slug: str) -> dict:
    path = _chats_index_path(slug)
    index = _read_json(path, None)
    if isinstance(index, dict) and isinstance(index.get("chats"), list) and index["chats"]:
        return index
    index = {"activeChat": None, "chats": []}
    legacy = _state_dir(slug) / "conversation.json"
    legacy_messages = []
    if legacy.is_file():
        try:
            legacy_messages = json.loads(legacy.read_text("utf-8"))
        except (OSError, ValueError):
            legacy_messages = []
        if not isinstance(legacy_messages, list):
            legacy_messages = []
    if legacy_messages:
        chat_id = uuid.uuid4().hex[:12]
        stamp = now()
        meta = {
            "id": chat_id,
            "title": _chat_title(legacy_messages),
            "createdAt": stamp,
            "updatedAt": stamp,
            "messageCount": len(legacy_messages),
        }
        _write_json(_chat_file(slug, chat_id), legacy_messages)
        index["chats"].append(meta)
        index["activeChat"] = chat_id
        try:
            legacy.rename(_state_dir(slug) / "conversation.legacy.json")
        except OSError:
            pass
    if not index["chats"]:
        chat_id = uuid.uuid4().hex[:12]
        stamp = now()
        meta = {
            "id": chat_id,
            "title": "New chat",
            "createdAt": stamp,
            "updatedAt": stamp,
            "messageCount": 0,
        }
        _write_json(_chat_file(slug, chat_id), [])
        index["chats"].append(meta)
        index["activeChat"] = chat_id
    _save_chats_index(slug, index)
    return index


def list_chats(slug: str) -> dict:
    index = ensure_chats(slug)
    chats = sorted(index["chats"], key=lambda c: c.get("updatedAt") or "", reverse=True)
    return {"chats": chats, "activeChat": index.get("activeChat")}


def create_chat(slug: str, title: str | None = None) -> dict:
    index = ensure_chats(slug)
    chat_id = uuid.uuid4().hex[:12]
    stamp = now()
    meta = {
        "id": chat_id,
        "title": (title or "New chat").strip()[:70] or "New chat",
        "createdAt": stamp,
        "updatedAt": stamp,
        "messageCount": 0,
    }
    _write_json(_chat_file(slug, chat_id), [])
    index["chats"].append(meta)
    index["activeChat"] = chat_id
    _save_chats_index(slug, index)
    return meta


def _plan_file(slug: str, chat_id: str) -> pathlib.Path:
    if not re.fullmatch(r"[a-f0-9]{12}", str(chat_id or "")):
        raise ValueError("Invalid chat id")
    return _chats_root(slug) / f"{chat_id}.plan.json"


def get_plan(slug: str, chat_id: str) -> dict:
    value = _read_json(_plan_file(slug, chat_id), {"steps": [], "updatedAt": None})
    if not isinstance(value, dict) or not isinstance(value.get("steps"), list):
        return {"steps": [], "updatedAt": None}
    return value


def save_plan(slug: str, chat_id: str, steps: list[dict]) -> dict:
    clean = []
    for step in steps[:12]:
        if not isinstance(step, dict):
            continue
        title = " ".join(str(step.get("title") or "").split())[:160]
        status = str(step.get("status") or "pending").lower()
        if status not in ("pending", "in_progress", "completed"):
            status = "pending"
        if title:
            clean.append({"title": title, "status": status})
    value = {"steps": clean, "updatedAt": now()}
    _write_json(_plan_file(slug, chat_id), value)
    return value


def get_chat(slug: str, chat_id: str) -> dict:
    index = ensure_chats(slug)
    meta = next((c for c in index["chats"] if c["id"] == chat_id), None)
    if meta is None:
        raise FileNotFoundError("Chat not found")
    messages = _read_json(_chat_file(slug, chat_id), [])
    if not isinstance(messages, list):
        messages = []
    return {**meta, "messages": messages, "plan": get_plan(slug, chat_id)}


def save_chat_messages(slug: str, chat_id: str, messages: list[dict]) -> dict:
    index = ensure_chats(slug)
    meta = next((c for c in index["chats"] if c["id"] == chat_id), None)
    if meta is None:
        raise FileNotFoundError("Chat not found")
    _write_json(_chat_file(slug, chat_id), messages)
    meta["messageCount"] = len(messages)
    meta["updatedAt"] = now()
    title = _chat_title(messages)
    if title != "New chat":
        meta["title"] = title
    _save_chats_index(slug, index)
    return meta


def set_active_chat(slug: str, chat_id: str) -> dict:
    index = ensure_chats(slug)
    meta = next((c for c in index["chats"] if c["id"] == chat_id), None)
    if meta is None:
        raise FileNotFoundError("Chat not found")
    index["activeChat"] = chat_id
    _save_chats_index(slug, index)
    return meta


def set_report(slug: str, report: dict) -> None:
    st = state(slug)
    st["lastReport"] = report
    st["lastStatus"] = report.get("status", "unverified")
    _save_state(slug, st)
    _write_json(_state_dir(slug) / "report.json", report)


def diff(before: str, after: str, rel: str) -> str:
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{rel}",
        tofile=f"b/{rel}",
    ))


def snapshot_hash(slug: str) -> str:
    digest = hashlib.sha256()
    root = ws_path(slug)
    for entry in sorted(tree(slug), key=lambda x: x["path"]):
        if entry["type"] != "file":
            continue
        path = root / entry["path"]
        if ".agent" in entry["path"].split("/"):
            continue
        digest.update(entry["path"].encode())
        try:
            digest.update(path.read_bytes())
        except OSError:
            pass
    return digest.hexdigest()
