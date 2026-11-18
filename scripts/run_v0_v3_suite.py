"""Run the deterministic V0-V3 suite and write dated evidence.

Usage:  python scripts/run_v0_v3_suite.py [--no-browser] [--out DIR]

Exit code 0 only when the deterministic engine suite passes and, if an
available headless browser is present, the rendered-browser smoke also passes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = ROOT / "docs" / "implementation" / "v0-v3" / "evidence"


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def wait_http(url: str, timeout: float = 30.0) -> bool:
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return response.status == 200
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = pathlib.Path(args.out) if args.out else EVIDENCE_ROOT / stamp
    out.mkdir(parents=True, exist_ok=True)

    summary: dict = {
        "startedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "root": str(ROOT),
        "python": sys.version,
        "commands": [],
        "results": {},
    }

    # 1. Deterministic engine suite.
    pytest_cmd = [sys.executable, "-m", "pytest", "qa/engine_contracts", "-q"]
    completed = subprocess.run(pytest_cmd, cwd=ROOT, text=True, capture_output=True,
                               encoding="utf-8", errors="replace")
    (out / "pytest.txt").write_text(completed.stdout + "\n" + completed.stderr, encoding="utf-8")
    summary["commands"].append({"command": " ".join(pytest_cmd), "exitCode": completed.returncode})
    summary["results"]["engineSuite"] = {
        "passed": completed.returncode == 0,
        "tail": (completed.stdout or "").splitlines()[-3:],
    }

    # 2. Reproducible fake-model/fake-worker demonstration.
    demo_cmd = [sys.executable, "scripts/demo_v0_v3.py", "--json"]
    demo = subprocess.run(demo_cmd, cwd=ROOT, text=True, capture_output=True,
                          encoding="utf-8", errors="replace")
    (out / "demo.json").write_text(demo.stdout + "\n" + demo.stderr, encoding="utf-8")
    summary["commands"].append({"command": " ".join(demo_cmd), "exitCode": demo.returncode})
    summary["results"]["demo"] = {"passed": demo.returncode == 0}

    # 3. Identity snapshot.
    identity_cmd = [sys.executable, "scripts/capture_engine_identity.py", "--json"]
    identity = subprocess.run(identity_cmd, cwd=ROOT, text=True, capture_output=True,
                              encoding="utf-8", errors="replace")
    (out / "identity.json").write_text(identity.stdout, encoding="utf-8")
    summary["commands"].append({"command": " ".join(identity_cmd), "exitCode": identity.returncode})
    summary["results"]["identity"] = {"passed": identity.returncode == 0}

    # 4. Rendered-browser smoke (headless Chrome + CDP, no installs).
    chrome = pathlib.Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    node = shutil.which("node")
    browser_available = bool(node and chrome.is_file() and not args.no_browser)
    if browser_available:
        port = free_port()
        engine_root = pathlib.Path(tempfile.mkdtemp(prefix="engine-suite-server-"))
        env = dict(os.environ)
        env["AUTHOR_AGENT_ENGINE_ROOT"] = str(engine_root)
        env["AUTHOR_AGENT_ENGINE_DEMO"] = "1"
        server = subprocess.Popen([sys.executable, "server.py", "--port", str(port)], cwd=ROOT,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
        try:
            ready = wait_http(f"http://127.0.0.1:{port}/api/health")
            if ready:
                browser_results = []
                browser_ok = True
                for script, screenshot_name, env_name in (
                    ("qa/engine_contracts/browser_smoke.mjs", "ui-collab.png",
                     "ENGINE_UI_SCREENSHOT"),
                    ("qa/engine_contracts/browser_repair.mjs", "ui-chat-repair.png",
                     "ENGINE_UI_SCREENSHOT_REPAIR"),
                ):
                    screenshot = out / screenshot_name
                    browser_env = dict(os.environ)
                    browser_env["ENGINE_UI_BASE"] = f"http://127.0.0.1:{port}"
                    browser_env[env_name] = str(screenshot)
                    browser = subprocess.run([node, script],
                                             cwd=ROOT, text=True, capture_output=True, env=browser_env,
                                             timeout=240, encoding="utf-8", errors="replace")
                    (out / (screenshot.stem + ".json")).write_text(
                        browser.stdout + "\n" + browser.stderr, encoding="utf-8")
                    summary["commands"].append({
                        "command": f"node {script} (server port {port})",
                        "exitCode": browser.returncode,
                    })
                    browser_results.append({
                        "script": script,
                        "status": "passed" if browser.returncode == 0 else "failed",
                        "screenshot": str(screenshot),
                    })
                    browser_ok = browser_ok and browser.returncode == 0
                summary["results"]["browser"] = {
                    "status": "passed" if browser_ok else "failed",
                    "screenshot": str(out / "ui-collab.png"),
                    "journeys": browser_results,
                }
            else:
                summary["results"]["browser"] = {"status": "unavailable", "detail": "server did not start"}
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except Exception:  # noqa: BLE001
                server.kill()

        # Decision-layer browser fixture: hostile admission + exhausted budget.
        decision_port = free_port()
        decision_server = subprocess.Popen(
            [sys.executable, "qa/engine_contracts/decision_browser_server.py",
             "--port", str(decision_port), "--mode", "hostile"],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            if wait_http(f"http://127.0.0.1:{decision_port}/api/health"):
                screenshot = out / "ui-chat-decision.png"
                browser_env = dict(os.environ)
                browser_env["ENGINE_UI_BASE"] = f"http://127.0.0.1:{decision_port}"
                browser_env["ENGINE_UI_SCREENSHOT_DECISION"] = str(screenshot)
                browser = subprocess.run(
                    [node, "qa/engine_contracts/browser_decision.mjs"],
                    cwd=ROOT, text=True, capture_output=True, env=browser_env,
                    timeout=300, encoding="utf-8", errors="replace")
                (out / "ui-chat-decision.json").write_text(
                    browser.stdout + "\n" + browser.stderr, encoding="utf-8")
                summary["commands"].append({
                    "command": f"node qa/engine_contracts/browser_decision.mjs "
                               f"(decision server port {decision_port})",
                    "exitCode": browser.returncode,
                })
                summary["results"]["decisionBrowser"] = {
                    "status": "passed" if browser.returncode == 0 else "failed",
                    "screenshot": str(screenshot),
                }
            else:
                summary["results"]["decisionBrowser"] = {
                    "status": "unavailable", "detail": "decision server did not start"}
        finally:
            decision_server.terminate()
            try:
                decision_server.wait(timeout=10)
            except Exception:  # noqa: BLE001
                decision_server.kill()

        # Recovery browser fixture: controlled interpretation failure, reload,
        # explicit Retry through the real chat endpoint.
        recovery_port = free_port()
        recovery_server = subprocess.Popen(
            [sys.executable, "qa/engine_contracts/decision_browser_server.py",
             "--port", str(recovery_port), "--mode", "fail-once"],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            if wait_http(f"http://127.0.0.1:{recovery_port}/api/health"):
                screenshot = out / "ui-chat-recovery.png"
                browser_env = dict(os.environ)
                browser_env["ENGINE_UI_BASE"] = f"http://127.0.0.1:{recovery_port}"
                browser_env["ENGINE_UI_SCREENSHOT_RECOVERY"] = str(screenshot)
                browser = subprocess.run(
                    [node, "qa/engine_contracts/browser_recovery.mjs"],
                    cwd=ROOT, text=True, capture_output=True, env=browser_env,
                    timeout=300, encoding="utf-8", errors="replace")
                (out / "ui-chat-recovery.json").write_text(
                    browser.stdout + "\n" + browser.stderr, encoding="utf-8")
                summary["commands"].append({
                    "command": "node qa/engine_contracts/browser_recovery.mjs "
                               f"(recovery server port {recovery_port})",
                    "exitCode": browser.returncode,
                })
                summary["results"]["recoveryBrowser"] = {
                    "status": "passed" if browser.returncode == 0 else "failed",
                    "screenshot": str(screenshot),
                }
            else:
                summary["results"]["recoveryBrowser"] = {
                    "status": "unavailable", "detail": "recovery server did not start"}
        finally:
            recovery_server.terminate()
            try:
                recovery_server.wait(timeout=10)
            except Exception:  # noqa: BLE001
                recovery_server.kill()
    else:
        summary["results"]["browser"] = {
            "status": "skipped",
            "detail": "node or headless Chrome is not available; rendered checks are unqualified",
        }

    # 5. Legacy regression checks that are runnable on this platform.
    legacy = [
        [sys.executable, "qa/test_skills.py"],
        [sys.executable, "qa/test_icpc_spec.py"],
        [sys.executable, "qa/test_ui_contracts.py"],
        [sys.executable, "qa/test_adversarial_manifest.py"],
        [sys.executable, "qa/test_hunks.py"],
    ]
    legacy_results = []
    for command in legacy:
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True,
                                encoding="utf-8", errors="replace")
        legacy_results.append({"command": " ".join(command), "exitCode": result.returncode})
    (out / "legacy.txt").write_text(json.dumps(legacy_results, indent=2), encoding="utf-8")
    summary["results"]["legacy"] = {
        "passed": all(item["exitCode"] == 0 for item in legacy_results),
        "commands": legacy_results,
    }

    summary["finishedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
    required = [summary["results"]["engineSuite"]["passed"],
                summary["results"]["demo"]["passed"],
                summary["results"]["legacy"]["passed"]]
    if summary["results"]["browser"]["status"] == "failed":
        required.append(False)
    if summary["results"].get("decisionBrowser", {}).get("status") == "failed":
        required.append(False)
    if summary["results"].get("recoveryBrowser", {}).get("status") == "failed":
        required.append(False)
    summary["ok"] = all(required)
    (out / "run-v0-v3.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (EVIDENCE_ROOT / "LATEST.json").write_text(json.dumps({
        "directory": out.name, "ok": summary["ok"], "finishedAt": summary["finishedAt"],
        "results": {key: value.get("status", value.get("passed"))
                    for key, value in summary["results"].items()},
    }, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
