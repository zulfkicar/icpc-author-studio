"""Isolate-style worker contract: limits, metadata and sandbox properties."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import winutil
import workspace


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS {name}")
        return
    print(f"  FAIL {name} {detail}")
    raise AssertionError(name)


def main() -> int:
    if not os.environ.get("AUTHOR_AGENT_EXECUTOR_URL"):
        print("SKIP isolate contract: AUTHOR_AGENT_EXECUTOR_URL is not set")
        return 0
    created = workspace.create("QA Isolate Contract", "isolate contract")
    slug = created["slug"]
    other = workspace.create("QA Isolate Other", "other workspace")["slug"]
    try:
        root = workspace.ws_path(slug)
        workspace.write_text(slug, "probe.py", "print('isolate-ok')\n", source="test")
        result = winutil.isolate_run([sys.executable, str(root / "probe.py")], cwd=root, time_limit=5, wall_time=10, memory_mb=256, processes=32)
        check("isolate run accepted", result.get("status") == "OK", result)
        check("isolate exit metadata", result.get("exit") == 0, result)
        check("isolate time metadata", isinstance(result.get("time"), (int, float)) and result["time"] > 0, result)
        check("isolate wall time metadata", isinstance(result.get("wallTime"), (int, float)), result)
        check("isolate rss metadata", result.get("maxRssKb", 0) > 0, result)
        check("isolate sandbox metadata", result.get("sandbox", {}).get("network") is False and result["sandbox"].get("readOnlyRoot") is True, result.get("sandbox"))
        check("isolate hides workspaces", "/app/workspaces" in result["sandbox"].get("hidden", []), result.get("sandbox"))

        workspace.write_text(other, "marker.txt", "other-secret", source="test")
        cross = (
            "try:\n"
            f"    open('/app/workspaces/{other}/marker.txt').read(); print('LEAKED')\n"
            "except Exception:\n"
            "    print('BLOCKED')\n"
        )
        workspace.write_text(slug, "cross.py", cross, source="test")
        result = winutil.isolate_run([sys.executable, str(root / "cross.py")], cwd=root, time_limit=5, wall_time=10)
        check("absolute cross-workspace read blocked", b"BLOCKED" in result["stdout"], result)

        workspace.write_text(slug, "readonly.py", "try:\n    open('/usr/isolate-write','w').write('x')\n    print('WROTE')\nexcept Exception:\n    print('READONLY')\n", source="test")
        result = winutil.isolate_run([sys.executable, str(root / "readonly.py")], cwd=root, time_limit=5, wall_time=10)
        check("read-only root enforced", b"READONLY" in result["stdout"], result)

        workspace.write_text(slug, "tle.py", "while True:\n    pass\n", source="test")
        result = winutil.isolate_run([sys.executable, str(root / "tle.py")], cwd=root, time_limit=1, wall_time=2)
        check("wall-time limit", result.get("status") == "TL", result)

        workspace.write_text(slug, "mle.py", "x = bytearray(512 * 1024 * 1024)\nprint(len(x))\n", source="test")
        result = winutil.isolate_run([sys.executable, str(root / "mle.py")], cwd=root, time_limit=5, wall_time=10, memory_mb=64)
        check("memory limit", result.get("status") in ("ML", "RE", "SG") and result.get("exit") != 0, result)

        pids = (
            "import subprocess, sys, time\n"
            "ps = []\n"
            "try:\n"
            "    for _ in range(60):\n"
            "        ps.append(subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(2)']))\n"
            "    print('NOCAP')\n"
            "except Exception:\n"
            "    print('PIDCAP')\n"
        )
        workspace.write_text(slug, "pids.py", pids, source="test")
        result = winutil.isolate_run([sys.executable, str(root / "pids.py")], cwd=root, time_limit=10, wall_time=20, processes=8)
        check("process cap", b"PIDCAP" in result["stdout"] or result.get("status") in ("RE", "SG"), result)
    finally:
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)
        shutil.rmtree(workspace.ws_path(other), ignore_errors=True)
    print("ISOLATE CONTRACT TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
