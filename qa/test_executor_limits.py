"""Executor limit/network tests. Run inside the app container."""
import os
import pathlib
import shutil
import sys
import time

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
    other = workspace.create("QA Executor Other", "other")["slug"]
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

        pids = run_code(slug, "import subprocess, sys\nps=[subprocess.Popen(['/bin/sleep','5']) for _ in range(300)]\nprint(len(ps))", timeout=20)
        assert not pids["ok"] or pids["returncode"] != 0, pids
        print("  PASS PID limit enforced", pids["returncode"])

        child_log = workspace.ws_path(slug) / "child.log"
        child_log.write_text("", "utf-8")
        code = (
            "import subprocess, sys\n"
            f"subprocess.Popen([sys.executable, '-c', \"import time; open(r'{child_log}', 'a').write('x'); time.sleep(60)\"])\n"
            "print('spawned')\n"
        )
        run_code(slug, code, timeout=10)
        time.sleep(0.5)
        first = child_log.stat().st_size
        time.sleep(2.0)
        second = child_log.stat().st_size
        assert first == second, (first, second)
        print("  PASS orphan process tree killed")

        workspace.write_text(other, "marker.txt", "other-secret", source="test")
        cross = run_code(slug, f"import os\ntry:\n open('/app/workspaces/{other}/marker.txt').read(); print('LEAKED')\nexcept Exception: print('BLOCKED')\nprint(os.getcwd())")
        assert b"BLOCKED" in cross["stdout"], cross
        print("  PASS absolute cross-workspace path blocked")
    finally:
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)
        shutil.rmtree(workspace.ws_path(other), ignore_errors=True)
    print("EXECUTOR LIMIT TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
