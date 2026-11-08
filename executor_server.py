"""Isolated execution worker.

The authoring app never compiles or runs model-written code itself. It sends
bounded commands here over an internal Docker network. This process has no API
key, no app source, no host port and no external network. It sees only the
workspace volume, runs as an unprivileged user, and applies per-process rlimits.
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import resource
import signal
import subprocess
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WORKSPACES = pathlib.Path(os.environ.get("AUTHOR_AGENT_WORKSPACES", "/app/workspaces")).resolve()
TOKEN = os.environ.get("AUTHOR_AGENT_EXECUTOR_TOKEN", "")
ALLOWED = {"g++", "gcc", "python", "python3", "javac", "java", "pdflatex", "latexmk"}
SEMAPHORE = threading.Semaphore(int(os.environ.get("AUTHOR_AGENT_EXECUTOR_SLOTS", "4")))
MAX_TIMEOUT = 120.0
MAX_OUTPUT = 4 * 1024 * 1024


def _safe_cwd(value: str) -> pathlib.Path:
    path = pathlib.Path(value or str(WORKSPACES)).resolve()
    if not path.is_relative_to(WORKSPACES):
        raise ValueError("Working directory is outside the workspace volume")
    return path


def _safe_argv(argv: list[str]) -> list[str]:
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        raise ValueError("argv must be a non-empty string list")
    first = pathlib.Path(argv[0])
    if first.is_absolute():
        resolved = first.resolve()
        if (first.name in ALLOWED or resolved.name in ALLOWED) and resolved.is_file():
            pass
        elif not resolved.is_relative_to(WORKSPACES) or not resolved.is_file():
            raise ValueError("Executable is outside the workspace volume")
    elif first.name not in ALLOWED:
        raise ValueError(f"Command not allowed: {first.name}")
    for argument in argv[1:]:
        if argument.startswith("/"):
            resolved = pathlib.Path(argument).resolve()
            if not resolved.is_relative_to(WORKSPACES) and not resolved.is_relative_to("/tmp"):
                raise ValueError("Argument path is outside the workspace volume")
    return argv


def _safe_env(value) -> dict:
    allowed = {"TEXINPUTS", "PYTHONPATH", "PYTHONIOENCODING", "LANG", "LC_ALL"}
    env = os.environ.copy()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in allowed and isinstance(item, str):
                env[key] = item
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["HOME"] = "/tmp"
    return env


def _limits(timeout: float):
    cpu = max(1, int(timeout) + 2)

    def apply() -> None:
        os.setsid()
        os.umask(0o077)
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (256 * 1024 * 1024, 256 * 1024 * 1024))

    return apply


def run(body: dict) -> dict:
    argv = _safe_argv(body.get("argv") or [])
    cwd = _safe_cwd(str(body.get("cwd") or WORKSPACES))
    timeout = max(1.0, min(MAX_TIMEOUT, float(body.get("timeout") or 10.0)))
    stdin = base64.b64decode(body.get("stdin") or "")
    env = _safe_env(body.get("env"))
    measure = bool(body.get("measure"))
    started = time.perf_counter()
    process = subprocess.Popen(
        argv,
        cwd=str(cwd),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        preexec_fn=_limits(timeout),
    )
    peak = 0
    stop = threading.Event()

    def sample() -> None:
        nonlocal peak
        try:
            import psutil
            parent = psutil.Process(process.pid)
        except Exception:
            return
        while not stop.is_set() and process.poll() is None:
            try:
                total = parent.memory_info().rss
                for child in parent.children(recursive=True):
                    try:
                        total += child.memory_info().rss
                    except Exception:
                        pass
                peak = max(peak, total)
            except Exception:
                pass
            time.sleep(0.01)

    sampler = threading.Thread(target=sample, daemon=True)
    if measure:
        sampler.start()
    timed_out = False
    try:
        stdout, stderr = process.communicate(stdin, timeout=timeout)
        returncode = process.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            stdout, stderr = b"", b""
        returncode = None
    except Exception as exc:  # noqa: BLE001
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except Exception:
            pass
        stdout, stderr, returncode = b"", str(exc).encode("utf-8", "replace"), None
    finally:
        stop.set()
        if measure:
            sampler.join(timeout=0.5)
    return {
        "ok": not timed_out and (returncode == 0 if measure else True),
        "timedOut": timed_out,
        "returncode": returncode,
        "stdout": base64.b64encode(stdout[:MAX_OUTPUT]).decode("ascii"),
        "stderr": base64.b64encode(stderr[:MAX_OUTPUT]).decode("ascii"),
        "ms": (time.perf_counter() - started) * 1000,
        "peakRssBytes": peak,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "AuthorExecutor/0.1"

    def log_message(self, fmt, *args):
        pass

    def _json(self, value, status: int = 200) -> None:
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urllib.parse.urlparse(self.path).path == "/health":
            return self._json({"ok": True, "worker": "executor", "slots": SEMAPHORE._value})
        return self._json({"error": "Not found"}, 404)

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path != "/run":
            return self._json({"error": "Not found"}, 404)
        if TOKEN and self.headers.get("X-Executor-Token") != TOKEN:
            return self._json({"error": "Unauthorized"}, 403)
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0 or length > 12 * 1024 * 1024:
                raise ValueError("Invalid request size")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("Invalid request")
            with SEMAPHORE:
                return self._json(run(body))
        except Exception as exc:  # noqa: BLE001
            return self._json({"error": f"{type(exc).__name__}: {exc}"}, 400)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    WORKSPACES.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    print(f"Author executor {args.host}:{args.port} root={WORKSPACES}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
