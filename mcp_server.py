"""Minimal scoped MCP stdio server for the authoring workspace.

The server exposes read-only inspection tools. It never exposes a shell, the
provider key, secret answers, or write/export operations.

MCP requires explicit user consent before a client invokes a tool or expands the
server's filesystem roots. Pass ``--consent <path>`` to the consent file written
by the host UI. Without consent every tool call is denied.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import workspace

PROTOCOL = "2025-06-18"
TOOLS = [
    {
        "name": "list_files",
        "description": "List authoring files in the selected workspace.",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}},
    },
    {
        "name": "read_file",
        "description": "Read a non-secret text file in the selected workspace.",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
    {
        "name": "search_workspace",
        "description": "Search authoring text files for a literal query.",
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
    {
        "name": "list_tests",
        "description": "List sample tests and the secret test count.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_report",
        "description": "Read the last deterministic verification report.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

DENY = {"enabled": False, "tools": {}, "roots": ["."]}


def _load_consent(path: str | None) -> dict:
    if not path:
        return dict(DENY)
    try:
        data = json.loads(pathlib.Path(path).read_text("utf-8"))
    except (OSError, ValueError):
        return dict(DENY)
    if not isinstance(data, dict):
        return dict(DENY)
    roots = [str(item) for item in data.get("roots") or ["."]]
    tools = data.get("tools") if isinstance(data.get("tools"), dict) else {}
    return {"enabled": bool(data.get("enabled")), "tools": tools, "roots": roots or ["."]}


def _allowed(consent: dict, name: str) -> bool:
    return bool(consent.get("enabled") and consent.get("tools", {}).get(name))


def _roots(slug: str, consent: dict) -> list[pathlib.Path]:
    roots = []
    for item in consent.get("roots") or ["."]:
        try:
            roots.append(workspace.resolve(slug, str(item)))
        except (ValueError, FileNotFoundError):
            continue
    return roots or [workspace.ws_path(slug)]


def _safe_path(slug: str, path: str, consent: dict) -> str:
    rel = str(path or "").replace("\\", "/").lstrip("/")
    if rel.startswith("data/secret/") or rel.endswith(".ans"):
        raise ValueError("Secret test data is not exposed over MCP")
    target = workspace.resolve(slug, rel)
    for root in _roots(slug, consent):
        if target == root or root in target.parents:
            return rel
    raise ValueError("Path is outside the consented MCP roots")


def _visible(slug: str, path: str, consent: dict) -> bool:
    rel = str(path or "").replace("\\", "/")
    if rel.startswith("data/secret/") or rel.endswith(".ans"):
        return False
    try:
        _safe_path(slug, rel, consent)
        return True
    except (ValueError, FileNotFoundError):
        return False


def _result(value):
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)[:200000]}]}


def call(slug: str, name: str, args: dict, consent: dict):
    if not _allowed(consent, name):
        raise PermissionError(f"Tool {name!r} has not been consented to by the host")
    if name == "list_files":
        rows = [row for row in workspace.tree(slug) if _visible(slug, row["path"], consent)]
        return {"files": rows, "roots": consent.get("roots", ["."])}
    if name == "read_file":
        rel = _safe_path(slug, str(args.get("path") or ""), consent)
        return workspace.read_text(slug, rel)
    if name == "search_workspace":
        query = str(args.get("query") or "")
        matches = []
        for row in workspace.tree(slug):
            if row["type"] != "file" or not row.get("text") or not _visible(slug, row["path"], consent):
                continue
            try:
                text = workspace.read_text(slug, row["path"]).get("content") or ""
            except Exception:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if query.lower() in line.lower():
                    matches.append({"path": row["path"], "line": number, "text": line.strip()[:240]})
                    if len(matches) >= 50:
                        return {"matches": matches, "truncated": True}
        return {"matches": matches, "truncated": False}
    if name == "list_tests":
        rows = workspace.tree(slug)
        return {
            "sample": [r["path"] for r in rows if r["path"].startswith("data/sample/") and r["path"].endswith(".in")],
            "secretCount": sum(1 for r in rows if r["path"].startswith("data/secret/") and r["path"].endswith(".in")),
        }
    if name == "read_report":
        return workspace.state(slug).get("lastReport") or {"status": "none"}
    raise ValueError(f"Unknown tool: {name}")


def handle(slug: str, message: dict, consent: dict):
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": request_id, "result": {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {}, "resources": {}},
            "serverInfo": {"name": "icpc-author-mcp", "version": "0.2"},
            "instructions": "Read-only workspace inspection. Tool calls require host consent.",
        }}
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = message.get("params") or {}
        try:
            value = call(slug, str(params.get("name") or ""), params.get("arguments") or {}, consent)
            return {"jsonrpc": "2.0", "id": request_id, "result": _result(value)}
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": request_id, "result": {"isError": True, "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}]}}
    if method == "resources/list":
        resources = [
            {"uri": f"file:///{slug}/{root}", "name": root, "mimeType": "inode/directory"}
            for root in consent.get("roots", ["."])
        ]
        return {"jsonrpc": "2.0", "id": request_id, "result": {"resources": resources}}
    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"prompts": []}}
    if request_id is None:
        return None
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--consent", default="", help="Path to the host consent JSON")
    args = parser.parse_args()
    consent = _load_consent(args.consent)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
            response = handle(args.slug, message, consent)
        except Exception as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
