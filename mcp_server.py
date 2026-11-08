"""Minimal scoped MCP stdio server for the authoring workspace.

The server exposes read-only inspection tools. It never exposes a shell, the
provider key, secret answers, or write/export operations. Hosts must obtain
explicit user consent before invoking any tool, as required by MCP.
"""
from __future__ import annotations

import argparse
import json
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
        "description": "List sample and secret test names.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_report",
        "description": "Read the last deterministic verification report.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _result(value):
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)[:200000]}]}


def call(slug: str, name: str, args: dict):
    if name == "list_files":
        return {"files": workspace.tree(slug)}
    if name == "read_file":
        return workspace.read_text(slug, str(args.get("path") or ""))
    if name == "search_workspace":
        query = str(args.get("query") or "")
        matches = []
        for row in workspace.tree(slug):
            if row["type"] != "file" or not row.get("text"):
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
            "secret": [r["path"] for r in rows if r["path"].startswith("data/secret/") and r["path"].endswith(".in")],
        }
    if name == "read_report":
        return workspace.state(slug).get("lastReport") or {"status": "none"}
    raise ValueError(f"Unknown tool: {name}")


def handle(slug: str, message: dict):
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": request_id, "result": {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "icpc-author-mcp", "version": "0.1"},
        }}
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = message.get("params") or {}
        try:
            value = call(slug, str(params.get("name") or ""), params.get("arguments") or {})
            return {"jsonrpc": "2.0", "id": request_id, "result": _result(value)}
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": request_id, "result": {"isError": True, "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}]}}
    if method in ("resources/list", "prompts/list"):
        key = "resources" if method.startswith("resources") else "prompts"
        return {"jsonrpc": "2.0", "id": request_id, "result": {key: []}}
    if request_id is None:
        return None
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    args = parser.parse_args()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
            response = handle(args.slug, message)
        except Exception as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
