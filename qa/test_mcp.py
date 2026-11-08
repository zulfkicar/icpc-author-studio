"""MCP stdio handshake and scoping test."""
import json
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import workspace


def check(name, condition, detail=""):
    if condition:
        print("  PASS", name)
        return
    print("  FAIL", name, detail)
    raise AssertionError(name)


def main():
    created = workspace.create("QA MCP", "mcp test")
    slug = created["slug"]
    workspace.write_text(slug, "data/sample/01.in", "1 2\n", source="test")
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "mcp_server.py"), "--slug", slug],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )
    try:
        def request(value):
            process.stdin.write(json.dumps(value) + "\n")
            process.stdin.flush()
            return json.loads(process.stdout.readline())

        init = request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        check("mcp initialize", init["result"]["protocolVersion"] == "2025-06-18", init)
        tools = request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = {tool["name"] for tool in tools["result"]["tools"]}
        check("mcp tools", {"list_files", "read_file", "list_tests", "read_report"} <= names, names)
        result = request({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_tests", "arguments": {}}})
        check("mcp tool call", "sample" in result["result"]["content"][0]["text"], result)
        bad = request({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "read_file", "arguments": {"path": "data/secret/01.ans"}}})
        check("mcp rejects secret", bad["result"].get("isError") is True, bad)
    finally:
        process.terminate()
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)
    print("MCP TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
