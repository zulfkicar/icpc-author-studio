"""Host-side consent and roots for the scoped MCP server.

MCP requires explicit user consent before a client invokes a tool or expands the
server's filesystem roots. Consent is stored per workspace in
``.agent/mcp.json`` and never in the provider configuration.
"""
from __future__ import annotations

import json
import pathlib

from author_studio.packages import workspace

FILENAME = "mcp.json"
DEFAULT_TOOLS = {
    "list_files": False,
    "read_file": False,
    "search_workspace": False,
    "list_tests": False,
    "read_report": False,
}


def _path(slug: str) -> pathlib.Path:
    folder = workspace.ws_path(slug) / ".agent"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / FILENAME


def _default() -> dict:
    return {"enabled": True, "tools": {name: True for name in DEFAULT_TOOLS}, "roots": ["."], "updatedAt": ""}


def state(slug: str) -> dict:
    path = _path(slug)
    if not path.is_file():
        default = _default()
        path.write_text(json.dumps(default, indent=2) + "\n", "utf-8")
        return default
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return _default()
    if not isinstance(data, dict):
        return _default()
    merged = _default()
    merged.update({key: data.get(key, merged[key]) for key in ("enabled", "roots", "updatedAt")})
    tools = dict(DEFAULT_TOOLS)
    if isinstance(data.get("tools"), dict):
        tools.update({key: bool(value) for key, value in data["tools"].items() if key in DEFAULT_TOOLS})
    merged["tools"] = tools
    merged["roots"] = _clean_roots(merged.get("roots"))
    return merged


def _clean_roots(value) -> list[str]:
    roots = []
    for item in value if isinstance(value, list) else ["."]:
        text = str(item or "").strip().replace("\\", "/")
        if not text:
            continue
        # Roots are workspace-relative. Reject absolute paths and traversal.
        if text.startswith("/") or text.startswith("~") or ".." in text.split("/"):
            continue
        if text not in roots:
            roots.append(text)
    return roots or ["."]


def update(slug: str, body: dict) -> dict:
    current = state(slug)
    if "enabled" in body:
        current["enabled"] = bool(body["enabled"])
    if "roots" in body:
        current["roots"] = _clean_roots(body["roots"])
    if "tools" in body and isinstance(body["tools"], dict):
        tools = dict(current["tools"])
        for key, value in body["tools"].items():
            if key in DEFAULT_TOOLS:
                tools[key] = bool(value)
        current["tools"] = tools
    current["updatedAt"] = workspace.now()
    path = _path(slug)
    path.write_text(json.dumps(current, indent=2) + "\n", "utf-8")
    return current


def allowed(slug: str, tool: str) -> bool:
    data = state(slug)
    return bool(data["enabled"] and data["tools"].get(tool))


def consent_path(slug: str) -> str:
    state(slug)
    return str(_path(slug))
