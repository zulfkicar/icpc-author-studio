"""MCP stdio handshake, consent and roots test."""
import json
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import mcp_consent
import workspace


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS {name}")
        return
    print(f"  FAIL {name} {detail}")
    raise AssertionError(name)


def request(process, value):
    process.stdin.write(json.dumps(value) + "\n")
    process.stdin.flush()
    return json.loads(process.stdout.readline())


def main():
    created = workspace.create("QA MCP", "mcp test")
    slug = created["slug"]
    workspace.write_text(slug, "data/sample/01.in", "1 2\n", source="test")
    workspace.write_text(slug, "data/sample/01.ans", "3\n", source="test")
    workspace.write_text(slug, "data/secret/01.in", "3 4\n", source="test")
    workspace.write_text(slug, "NOTES.md", "hello\n", source="test")
    consent = mcp_consent.update(slug, {
        "enabled": True,
        "tools": {"list_files": True, "read_file": True, "search_workspace": True, "list_tests": True, "read_report": True},
        "roots": ["data/sample", "NOTES.md"],
    })
    check("consent enabled", consent["enabled"] and consent["tools"]["read_file"], consent)
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "mcp_server.py"), "--slug", slug, "--consent", mcp_consent.consent_path(slug)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )
    try:
        init = request(process, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        check("mcp initialize", init["result"]["protocolVersion"] == "2025-06-18", init)
        tools = request(process, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = {tool["name"] for tool in tools["result"]["tools"]}
        check("mcp tools", {"list_files", "read_file", "list_tests", "read_report"} <= names, names)
        result = request(process, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_tests", "arguments": {}}})
        check("mcp tool call", "sample" in result["result"]["content"][0]["text"], result)
        check("secret names hidden", "secret/" not in result["result"]["content"][0]["text"], result)
        bad = request(process, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "read_file", "arguments": {"path": "data/secret/01.ans"}}})
        check("mcp rejects secret", bad["result"].get("isError") is True, bad)
        outside = request(process, {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "read_file", "arguments": {"path": "problem.yaml"}}})
        check("mcp enforces roots", outside["result"].get("isError") is True, outside)
        inside = request(process, {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "read_file", "arguments": {"path": "data/sample/01.in"}}})
        check("mcp reads consented root", inside["result"].get("isError") is not True, inside)
        resources = request(process, {"jsonrpc": "2.0", "id": 7, "method": "resources/list", "params": {}})
        check("mcp exposes roots", len(resources["result"]["resources"]) == 2, resources)
    finally:
        process.terminate()

    # Default consent: a fresh workspace is enabled with every tool and "." root.
    fresh = workspace.create("QA MCP Default", "mcp default")["slug"]
    workspace.write_text(fresh, "data/sample/01.in", "1 2\n", source="test")
    workspace.write_text(fresh, "problem.yaml", "name: QA MCP Default\n", source="test")
    default_state = mcp_consent.state(fresh)
    check("mcp default enabled", default_state["enabled"] and all(default_state["tools"].values()), default_state)
    check("mcp default root", default_state["roots"] == ["."], default_state)
    default_process = subprocess.Popen(
        [sys.executable, str(ROOT / "mcp_server.py"), "--slug", fresh, "--consent", mcp_consent.consent_path(fresh)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )
    try:
        response = request(default_process, {"jsonrpc": "2.0", "id": 20, "method": "tools/call", "params": {"name": "read_file", "arguments": {"path": "problem.yaml"}}})
        check("mcp default relative path", response["result"].get("isError") is not True and "QA MCP Default" in response["result"]["content"][0]["text"], response)
        response = request(default_process, {"jsonrpc": "2.0", "id": 21, "method": "tools/call", "params": {"name": "search_workspace", "arguments": {"query": "QA MCP"}}})
        check("mcp default search", response["result"].get("isError") is not True, response)
    finally:
        default_process.terminate()
        shutil.rmtree(workspace.ws_path(fresh), ignore_errors=True)

    # Deny-by-default: a fresh consent file with the server disabled.
    mcp_consent.update(slug, {"enabled": False})
    denied = subprocess.Popen(
        [sys.executable, str(ROOT / "mcp_server.py"), "--slug", slug, "--consent", mcp_consent.consent_path(slug)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )
    try:
        response = request(denied, {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "list_tests", "arguments": {}}})
        check("mcp denies without consent", response["result"].get("isError") is True, response)
    finally:
        denied.terminate()
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)
    print("MCP TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
