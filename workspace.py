"""Safe file operations and change tracking for one problem workspace.

The agent never gets a raw shell rooted at the user's machine. Every path is
resolved inside a workspace, text writes are recorded as reviewable changes,
and the UI can inspect or revert each change.
"""
from __future__ import annotations

import contextlib
import difflib
import hashlib
import json
import pathlib
import re
import shutil
import threading
import time
import uuid
import unicodedata
import zipfile

import yaml

import package_workflow
from config import TEMPLATES, WORKSPACES
from problem_titles import latex_text, statement_title

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
    return (slug or "problem")[:48].rstrip("-")


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


def export_filename(slug: str, title: str | None = None) -> str:
    st = state(slug)
    meta = st.get("meta", {})
    title = title if title is not None else (meta.get("name") if st.get("titleOwner") else "")
    stem = re.sub(r"[\W_]+", "-", unicodedata.normalize("NFKC", title or "").casefold()).strip("-")[:48].rstrip("-")
    return f"{stem or safe_slug(slug)}-domjudge.zip"


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
        suffix = f"-{counter}"
        slug = base[:48 - len(suffix)].rstrip("-") + suffix
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

    def sub(text: str, suffix: str) -> str:
        values = {
            "{{PROBLEM_NAME}}": latex_text(name) if suffix == ".tex" else json.dumps(name, ensure_ascii=False)[1:-1],
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
        return re.sub("|".join(map(re.escape, values)), lambda match: values[match[0]], text)

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
        target.write_bytes(sub(src.read_text("utf-8"), target.suffix).encode("utf-8"))

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
        "- [ ] Time and memory limits are measured from the reference, not guessed",
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
        "reviewedSnapshot": None,
        "limitsMeasured": False,
        "measuredLimits": None,
    }
    _save_state(slug, st)
    _write_json(_state_dir(slug) / "changes.json", [])
    return summary(slug)


def summary(slug: str) -> dict:
    st = state(slug)
    report = st.get("lastReport")
    entries = tree(slug)
    workflow = package_workflow.evaluate(snapshot_hash(slug, entries=entries), st, sum(
        1 for change in changes(slug) if not change.get("reviewed") and not change.get("reverted")
    ))
    stale = workflow["phase"] == "verification_stale"
    status = "stale" if stale else st.get("lastStatus", "unverified")
    return {
        "slug": safe_slug(slug),
        "meta": st.get("meta", {}),
        "lastStatus": status,
        "lastReport": report,
        "lastReview": st.get("lastReview"),
        "previousVerification": st.get("previousVerification"),
        "limitsMeasured": bool(st.get("limitsMeasured")),
        "measuredLimits": st.get("measuredLimits"),
        "stale": stale,
        "unreviewed": workflow["unreviewedChanges"],
        "snapshot": workflow["snapshot"],
        "workflow": workflow,
        "tree": entries,
    }


def archive_status(slug: str, workflow: package_workflow.PackageWorkflow) -> dict:
    filename = export_filename(slug)
    folder = ws_path(slug) / ".agent" / "export"
    target = folder / filename
    archive_name = filename
    if not target.is_file():
        prior = sorted(folder.glob("*.zip"), key=lambda path: path.stat().st_mtime, reverse=True)
        if prior:
            target, archive_name = prior[0], prior[0].name
    if not target.is_file():
        return {"status": "not_generated" if workflow["canExport"] else "blocked", "filename": filename}
    try:
        with zipfile.ZipFile(target) as archive:
            manifest = json.loads(archive.read("problem_statement/manifest.json"))
        if not isinstance(manifest, dict):
            raise ValueError("Invalid archive manifest")
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        return {"status": "invalid", "filename": filename}
    ready = workflow["canExport"] and manifest.get("snapshot") == workflow["snapshot"] and archive_name == filename
    return {"status": "ready" if ready else "stale", "filename": filename,
            "archiveFilename": archive_name, "snapshot": manifest.get("snapshot"),
            "verifiedAt": manifest.get("verifiedAt"), "createdAt": manifest.get("createdAt"),
            "format": "DOMjudge ZIP"}


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


def _record(slug: str, action: str, rel: str, before: str | None, after: str | None, source: str,
            artifact_origin: dict | None = None) -> dict:
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
        if artifact_origin is not None:
            entry["artifactOrigin"] = artifact_origin
        items.append(entry)
        if len(items) > 400:
            items = items[-400:]
        _write_json(_changes_path(slug), items)
        return entry


def write_text(slug: str, rel: str, content: str, source: str = "agent", *, artifact_origin: dict | None = None) -> dict:
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
    entry = _record(slug, "write", rel, before, content, source, artifact_origin)
    return {"path": rel, "changed": True, "change": entry, "diff": diff(before or "", content, rel)}


def _yaml_problem_title(text: str, title: str) -> str:
    try:
        data = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError as exc:
        raise ValueError("Fix invalid problem.yaml before updating the title.") from exc
    quoted = json.dumps(title, ensure_ascii=False)
    if data is not None and not isinstance(data, yaml.MappingNode):
        raise ValueError("problem.yaml must be a mapping to update the title.")
    for key, value in (data.value if data is not None else []):
        if key.value != "name":
            continue
        if isinstance(value, yaml.ScalarNode) and value.tag == "tag:yaml.org,2002:str" and value.value == title:
            return text
        start, end = value.start_mark.index, value.end_mark.index
        if start < key.end_mark.index:
            raise ValueError("Replace the name alias in problem.yaml before updating the title.")
        if start == end:
            quoted = " " + quoted
        if text[start:end].endswith("\n"):
            quoted += "\n"
        return text[:start] + quoted + text[end:]
    if isinstance(data, yaml.MappingNode) and data.flow_style:
        prefix = data.start_mark.index + 1
        return text[:prefix] + "name: " + quoted + (", " if data.value else "") + text[prefix:]
    start = data.start_mark.index if data is not None else 0
    return text[:start] + "name: " + quoted + "\n" + text[start:]


def problem_title_edits(slug: str, title: str) -> tuple[list, bool]:
    updates = []
    statement_supported = False
    for rel in ("problem.yaml", "domjudge-problem.ini", "problem_statement/problem.en.tex", "statement/problem.en.tex"):
        path = resolve(slug, rel)
        if not path.is_file():
            if rel == "problem.yaml":
                updates.append((rel, path, None, "name: " + json.dumps(title, ensure_ascii=False) + "\n"))
            continue
        before = path.read_bytes()
        text = before.decode("utf-8")
        if rel.endswith(".yaml"):
            edited = _yaml_problem_title(text, title)
        elif rel.endswith(".ini"):
            line = "name = " + json.dumps(title, ensure_ascii=False)
            edited, count = re.subn(r"^name[ \t]*=[^\r\n]*", lambda _: line, text, count=1, flags=re.M)
            if not count:
                edited = line + "\n" + edited
        else:
            edited = statement_title(text, title)
            statement_supported |= edited != text or statement_title(text, title + " preview") != text
        if edited != text:
            updates.append((rel, path, before, edited))
    return updates, statement_supported


@contextlib.contextmanager
def use_problem_title(slug: str, title: str, run_id: str):
    """Apply tracked title edits and restore them if saving the link or run fails."""
    with _LOCK:
        st = state(slug)
        meta = st.setdefault("meta", {})
        if st.get("titleOwner") not in (None, run_id):
            raise ValueError("This package already follows the title of another conversation.")
        updates, _ = problem_title_edits(slug, title)
        state_dir = _state_dir(slug)
        backups = {path: path.read_bytes() if path.exists() else None
                   for path in (state_dir / "state.json", state_dir / "changes.json")}
        try:
            for rel, path, before, edited in updates:
                backups[path] = before
                write_text(slug, rel, edited, source="problem-title")
            if meta.get("name") != title or st.get("titleOwner") != run_id:
                meta["name"] = title
                st["titleOwner"] = run_id
                _save_state(slug, st)
            yield
        except Exception:
            for path, before in backups.items():
                if before is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(before)
            raise


def delete_file(slug: str, rel: str, source: str = "agent") -> dict:
    rel = validate_rel(rel)
    path = resolve(slug, rel)
    if not path.is_file():
        raise FileNotFoundError("File not found")
    before = path.read_text("utf-8", errors="replace")
    path.unlink()
    entry = _record(slug, "delete", rel, before, None, source)
    return {"path": rel, "changed": True, "change": entry, "diff": diff(before, "", rel)}



def create_folder(slug: str, rel: str) -> dict:
    rel = validate_rel(rel)
    path = resolve(slug, rel)
    if path.exists():
        raise ValueError("That path already exists")
    path.mkdir(parents=True)
    return {"path": rel, "type": "dir", "created": True}


def create_file(slug: str, rel: str, content: str = "") -> dict:
    rel = validate_rel(rel)
    path = resolve(slug, rel)
    if path.exists():
        raise ValueError("That path already exists")
    result = write_text(slug, rel, content, source="user")
    return {"path": rel, "type": "file", "created": True, **result}


def rename_entry(slug: str, rel: str, new_rel: str) -> dict:
    rel = validate_rel(rel)
    new_rel = validate_rel(new_rel)
    source = resolve(slug, rel)
    target = resolve(slug, new_rel)
    if not source.exists():
        raise FileNotFoundError("Path not found")
    if target.exists():
        raise ValueError("The target path already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)
    return {"path": new_rel, "oldPath": rel, "type": "dir" if target.is_dir() else "file"}


def delete_entry(slug: str, rel: str) -> dict:
    rel = validate_rel(rel)
    path = resolve(slug, rel)
    if path.is_file():
        return delete_file(slug, rel, source="user")
    if path.is_dir():
        shutil.rmtree(path)
        return {"path": rel, "type": "dir", "deleted": True}
    raise FileNotFoundError("Path not found")

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


class SnapshotConflict(ValueError):
    """The author or worker prepared an action for a different saved revision."""


def mark_reviewed(slug: str, expected_snapshot: str | None = None) -> dict:
    snapshot = require_snapshot(slug, expected_snapshot)
    baseline = _review_baseline(slug, snapshot)
    _write_json(_review_path(slug, snapshot), baseline)
    require_snapshot(slug, snapshot)
    items = changes(slug)
    for entry in items:
        if not entry.get("reverted"):
            entry["reviewed"] = True
    st = state(slug)
    st["lastReview"] = now()
    st["reviewedSnapshot"] = snapshot
    _save_state(slug, st)
    _write_json(_changes_path(slug), items)
    return {"reviewed": sum(1 for c in items if c.get("reviewed") and not c.get("reverted")),
            "at": st["lastReview"], "snapshot": snapshot}


def _review_path(slug: str, snapshot: str) -> pathlib.Path:
    return _state_dir(slug) / "reviews" / f"{snapshot}.json"


def _review_baseline(slug: str, snapshot: str) -> dict:
    """Keep all file identities and a bounded set of text for cumulative review."""
    root = ws_path(slug)
    digest = hashlib.sha256()
    budget = 768 * 1024
    files = {}
    for entry in sorted(tree(slug), key=lambda item: item["path"]):
        if entry["type"] != "file":
            continue
        rel = entry["path"]
        path = root / rel
        data = path.read_bytes()
        digest.update(rel.encode())
        digest.update(data)
        record = {"hash": hashlib.sha256(data).hexdigest()}
        if len(data) <= min(48 * 1024, budget) and b"\0" not in data and path.resolve().is_relative_to(root):
            try:
                record["text"] = data.decode("utf-8")
                budget -= len(data)
            except UnicodeDecodeError:
                pass
        files[rel] = record
    if digest.hexdigest() != snapshot:
        raise SnapshotConflict("Package changed while preparing the review. Refresh and try again.")
    return {"snapshot": snapshot, "files": files}


def studio_review(slug: str, expected: str | None, path: str | None = None) -> dict:
    snapshot = require_snapshot(slug, expected)
    approved = state(slug).get("reviewedSnapshot")
    baseline = (_read_json(_review_path(slug, approved), None)
                if isinstance(approved, str) and re.fullmatch(r"[a-f0-9]{64}", approved) else None)
    current = _review_baseline(slug, snapshot)["files"]
    previous = baseline["files"] if baseline else {}
    logged = {}
    for entry in changes(slug):
        if entry.get("reverted") or entry.get("reviewed"):
            continue
        logged.setdefault(entry["path"], []).append(entry)
    rows = []
    for rel in sorted(current.keys() | previous.keys()):
        before, after = previous.get(rel), current.get(rel)
        if baseline and (before or {}).get("hash") == (after or {}).get("hash"):
            continue
        entries = logged.get(rel, [])
        source = (entries[-1].get("source") or "workspace") if entries else "outside change or unrecorded source"
        if entries and isinstance(entries[-1].get("after"), str) and after and \
                hashlib.sha256(entries[-1]["after"].encode()).hexdigest() != after["hash"]:
            source = "outside change or unrecorded source"
        kind = "saved" if not baseline else "removed" if after is None else "added" if before is None else "modified"
        row = {"path": rel, "source": source, "kind": kind}
        if source == "artifact copy" and entries[-1].get("artifactOrigin"):
            row["artifactOrigin"] = entries[-1]["artifactOrigin"]
        rows.append(row)
    if path is None:
        return {"snapshot": snapshot, "baseline": approved if baseline else None, "files": rows}
    path = validate_rel(path)
    if not any(row["path"] == path for row in rows):
        raise FileNotFoundError("This file is not in the current review.")
    before = previous.get(path, {})
    after = current.get(path, {})
    complete = bool(baseline) and (not before or "text" in before) and (not after or "text" in after)
    return {"snapshot": snapshot, "path": path, "hasDiff": complete,
            "diff": diff(before.get("text", ""), after.get("text", ""), path) if complete else None,
            "current": after.get("text"), "present": bool(after), "hash": after.get("hash")}


def checkpoint_path(slug: str) -> pathlib.Path:
    path = _state_dir(slug) / "checkpoints.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _pending_file(slug: str, chat_id: str) -> pathlib.Path:
    if not re.fullmatch(r"[a-f0-9]{12}", str(chat_id or "")):
        raise ValueError("Invalid chat id")
    path = _state_dir(slug) / "pending"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{chat_id}.json"


def get_pending(slug: str, chat_id: str) -> list[dict]:
    value = _read_json(_pending_file(slug, chat_id), [])
    return value if isinstance(value, list) else []


def save_pending(slug: str, chat_id: str, approvals: list[dict]) -> None:
    _write_json(_pending_file(slug, chat_id), approvals)


def clear_pending(slug: str, chat_id: str) -> None:
    try:
        _pending_file(slug, chat_id).unlink()
    except FileNotFoundError:
        pass


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


def rename_chat(slug: str, chat_id: str, title: str) -> dict:
    index = ensure_chats(slug)
    meta = next((c for c in index["chats"] if c["id"] == chat_id), None)
    if meta is None:
        raise FileNotFoundError("Chat not found")
    clean = " ".join(str(title or "").split())[:70]
    if not clean:
        raise ValueError("A chat title is required")
    meta["title"] = clean
    meta["updatedAt"] = now()
    _save_chats_index(slug, index)
    return meta


def delete_chat(slug: str, chat_id: str) -> dict:
    index = ensure_chats(slug)
    meta = next((c for c in index["chats"] if c["id"] == chat_id), None)
    if meta is None:
        raise FileNotFoundError("Chat not found")
    index["chats"] = [c for c in index["chats"] if c["id"] != chat_id]
    if index.get("activeChat") == chat_id:
        index["activeChat"] = index["chats"][0]["id"] if index["chats"] else None
    _save_chats_index(slug, index)
    for path in (_chat_file(slug, chat_id), _plan_file(slug, chat_id)):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    try:
        _pending_file(slug, chat_id).unlink()
    except FileNotFoundError:
        pass
    return index


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


def _clarifications_file(slug: str, chat_id: str) -> pathlib.Path:
    if not re.fullmatch(r"[a-f0-9]{12}", str(chat_id or "")):
        raise ValueError("Invalid chat id")
    return _chats_root(slug) / f"{chat_id}.clarifications.json"


def get_clarifications(slug: str, chat_id: str) -> list[dict]:
    value = _read_json(_clarifications_file(slug, chat_id), [])
    return value if isinstance(value, list) else []


def save_clarifications(slug: str, chat_id: str, items: list[dict]) -> list[dict]:
    clean = [item for item in (items or []) if isinstance(item, dict)][-50:]
    _write_json(_clarifications_file(slug, chat_id), clean)
    return clean


def get_chat(slug: str, chat_id: str) -> dict:
    index = ensure_chats(slug)
    meta = next((c for c in index["chats"] if c["id"] == chat_id), None)
    if meta is None:
        raise FileNotFoundError("Chat not found")
    messages = _read_json(_chat_file(slug, chat_id), [])
    if not isinstance(messages, list):
        messages = []
    return {**meta, "messages": messages, "plan": get_plan(slug, chat_id), "pending": get_pending(slug, chat_id), "clarifications": get_clarifications(slug, chat_id)}


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


def set_limits(slug: str, time_limit_seconds: float, memory_mb: int, details: dict) -> dict:
    st = state(slug)
    meta = st.setdefault("meta", {})
    meta["timeLimit"] = str(time_limit_seconds)
    meta["memoryMb"] = str(memory_mb)
    st["limitsMeasured"] = True
    st["measuredLimits"] = {
        "timeLimitSeconds": time_limit_seconds,
        "memoryMb": memory_mb,
        **details,
    }
    _save_state(slug, st)
    return st["measuredLimits"]


def set_report(slug: str, report: dict) -> None:
    st = state(slug)
    previous = st.get("lastReport") or {}
    if report.get("snapshot") != previous.get("snapshot"):
        st.setdefault("reviewedSnapshot", None)
        if previous.get("status") == "verified":
            st["previousVerification"] = {key: previous.get(key) for key in ("status", "at", "snapshot", "counts")}
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


def parse_hunks(diff_text: str) -> list[dict]:
    """Parse a unified diff into selectable hunks."""
    hunks: list[dict] = []
    current = None
    for line in str(diff_text or "").splitlines(keepends=True):
        if line.startswith("@@"):
            match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if not match:
                continue
            current = {
                "index": len(hunks),
                "header": line.rstrip("\n"),
                "oldStart": int(match.group(1)),
                "oldCount": int(match.group(2) or 1),
                "newStart": int(match.group(3)),
                "newCount": int(match.group(4) or 1),
                "lines": [],
            }
            hunks.append(current)
        elif current is not None:
            current["lines"].append(line)
    return hunks


def apply_hunks(slug: str, change_id: str, selected: list[int] | None = None) -> dict:
    """Apply only selected hunks from a recorded change."""
    items = changes(slug)
    entry = next((item for item in items if item["id"] == change_id), None)
    if entry is None:
        raise FileNotFoundError("Change not found")
    if entry.get("reverted"):
        raise ValueError("Change was reverted")
    before = entry.get("before") or ""
    after = entry.get("after") or ""
    hunks = parse_hunks(diff(before, after, entry["path"]))
    if not hunks:
        raise ValueError("No hunks to apply")
    wanted = {int(item) for item in (selected if selected is not None else range(len(hunks)))}
    if any(item < 0 or item >= len(hunks) for item in wanted):
        raise ValueError("Selected hunk is out of range")
    before_lines = before.splitlines(keepends=True)
    result = []
    cursor = 0
    for hunk in hunks:
        start = max(0, hunk["oldStart"] - 1)
        if start < cursor or start > len(before_lines):
            raise ValueError("Hunk is out of order")
        result.extend(before_lines[cursor:start])
        old_segment = []
        new_segment = []
        for line in hunk["lines"]:
            if line.startswith(" "):
                old_segment.append(line[1:])
                new_segment.append(line[1:])
            elif line.startswith("-"):
                old_segment.append(line[1:])
            elif line.startswith("+"):
                new_segment.append(line[1:])
        result.extend(new_segment if hunk["index"] in wanted else old_segment)
        cursor = start + len(old_segment)
    result.extend(before_lines[cursor:])
    content = "".join(result)
    written = write_text(slug, entry["path"], content, source="user")
    return {"path": entry["path"], "applied": sorted(wanted), "hunks": len(hunks), "content": content, **written}


def _snapshots_root(slug: str, chat_id: str) -> pathlib.Path:
    if not re.fullmatch(r"[a-f0-9]{12}", str(chat_id or "")):
        raise ValueError("Invalid chat id")
    path = _state_dir(slug) / "snapshots" / chat_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def snapshot_turn(slug: str, chat_id: str) -> dict:
    """Create a workspace snapshot before a turn. Excludes app/build state."""
    root = ws_path(slug)
    folder = _snapshots_root(slug, chat_id)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    snapshot_id = f"{stamp}-{uuid.uuid4().hex[:8]}"
    target = folder / f"{snapshot_id}.zip"
    manifest = {"id": snapshot_id, "chatId": chat_id, "at": now(), "files": {}}
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in sorted(root.rglob("*")):
            if item.is_dir():
                continue
            rel = item.relative_to(root).as_posix()
            parts = set(item.relative_to(root).parts)
            if parts & {".agent", "__pycache__", ".git", "build", "tmp"}:
                continue
            if item.suffix.lower() in (".tmp", ".pyc"):
                continue
            zf.write(item, rel)
            manifest["files"][rel] = hashlib.sha256(item.read_bytes()).hexdigest()
        zf.writestr(".snapshot.json", json.dumps(manifest, indent=2))
    items = sorted(folder.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in items[20:]:
        try:
            old.unlink()
        except OSError:
            pass
    return {"id": snapshot_id, "path": target.relative_to(root).as_posix(), "files": len(manifest["files"])}


def list_snapshots(slug: str, chat_id: str) -> list[dict]:
    folder = _snapshots_root(slug, chat_id)
    out = []
    for path in sorted(folder.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            out.append({"id": path.stem, "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(path.stat().st_mtime)), "size": path.stat().st_size})
        except OSError:
            pass
    return out


def restore_snapshot(slug: str, chat_id: str, snapshot_id: str) -> dict:
    folder = _snapshots_root(slug, chat_id)
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", snapshot_id or ""):
        raise ValueError("Invalid snapshot id")
    archive = folder / f"{snapshot_id}.zip"
    if not archive.is_file():
        raise FileNotFoundError("Snapshot not found")
    root = ws_path(slug)
    staging = folder / f".restore-{uuid.uuid4().hex[:8]}"
    staging.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(archive) as zf:
            for member in zf.infolist():
                if member.is_dir():
                    continue
                target = (staging / member.filename).resolve()
                if not target.is_relative_to(staging):
                    raise ValueError("Snapshot contains an unsafe path")
            zf.extractall(staging)
        for item in list(root.iterdir()):
            if item.name == ".agent":
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        for item in staging.iterdir():
            if item.name == ".snapshot.json":
                continue
            target = root / item.name
            if item.is_dir():
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {"id": snapshot_id, "restored": True}


def snapshot_hash(slug: str, *, entries: list[dict] | None = None) -> str:
    digest = hashlib.sha256()
    root = ws_path(slug)
    for entry in sorted(tree(slug) if entries is None else entries, key=lambda x: x["path"]):
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


def require_snapshot(slug: str, expected: str | None) -> str:
    snapshot = snapshot_hash(slug)
    if expected is not None and expected != snapshot:
        raise SnapshotConflict("Package changed since this action was prepared. Refresh and try again.")
    return snapshot
