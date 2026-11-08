"""Executor limit/network tests. Run inside the app container."""
import os
import pathlib
import shutil
import sys

sys.path.insert(0, "/app")
import winutil
import workspace


def run_code(slug, code, timeout=10, measured=False):
    workspace.write_text(slug, "qa_probe.py", code, source="test")
    runner = winutil.run_measured if measured else winutil.run_captured
    return runner([sys.executable, str(workspace.ws_path(slug) / "qa_probe.py")], cwd=workspace.ws_path(slug), timeout=timeout)


def main():
    created = workspace.create("QA Executor Limits", "limits")
    slug = created["slug"]
    try:
        key = run_code(slug, "import os; print('KEY' if os.environ.get('AUTHOR_AGENT_API_KEY') else 'NO_KEY')")
        assert key["returncode"] == 0 and b"NO_KEY" in key["stdout"], key
        print("  PASS executor has no provider key")

        net = run_code(slug, "import socket, sys\ns=socket.socket(); s.settimeout(2)\ntry:\n s.connect(('1.1.1.1',80)); print('NETWORK_OPEN')\nexcept Exception: print('NETWORK_BLOCKED')")
        assert b"NETWORK_BLOCKED" in net["stdout"], net
        print("  PASS executor external network blocked")

        flood = run_code(slug, "print('x' * 10_000_000)")
        assert len(flood["stdout"]) <= 4 * 1024 * 1024 + 1024, len(flood["stdout"])
        print("  PASS output flood capped", len(flood["stdout"]))

        memory = run_code(slug, "x = bytearray(3_000_000_000); x[::4096] = b'x' * (len(x)//4096 + 1)", timeout=20, measured=True)
        assert not memory["ok"] or memory["returncode"] != 0, memory
        print("  PASS memory limit enforced", memory["returncode"])
    finally:
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)
    print("EXECUTOR LIMIT TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
