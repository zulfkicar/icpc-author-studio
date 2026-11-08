"""HTTP wrapper around a real Isolate installation.

Runs inside the Judge0 CE image (which ships Isolate 1.8.1 and compilers) as a
dedicated privileged worker. It is deliberately independent of the bwrap
executor: the deterministic verifier can be pointed at this service with
``AUTHOR_AGENT_ISOLATE_URL``.

Contract:
    POST /isolate/run
    {"source": "...", "language": "cpp", "stdin": "...", "time": 2,
     "wallTime": 5, "memoryMb": 256, "fsizeMb": 4}

    -> {"ok": true, "status": "OK", "exit": 0, "stdout": "...",
        "stderr": "", "compileOutput": "", "time": 0.01,
        "wallTime": 0.02, "memory": 3200, "isolate": "1.8.1"}
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BOX_ROOT = "/var/local/lib/isolate"
TOKEN = os.environ.get("AUTHOR_AGENT_ISOLATE_TOKEN", "")
PYTHON = "/usr/local/python-3.8.1/bin/python3"
GCC = "/usr/local/gcc-9.2.0/bin/g++"
GCC_C = "/usr/local/gcc-9.2.0/bin/gcc"
JAVAC = "/usr/local/openjdk13/bin/javac"
JAVA = "/usr/local/openjdk13/bin/java"
LANGUAGES = {
    "cpp": ("main.cpp", f"{GCC} -O2 -o a.out main.cpp", "LD_LIBRARY_PATH=/usr/local/gcc-9.2.0/lib64 ./a.out"),
    "c": ("main.c", f"{GCC_C} -O2 -o a.out main.c", "./a.out"),
    "py": ("script.py", "", f"{PYTHON} script.py"),
    "python": ("script.py", "", f"{PYTHON} script.py"),
    "java": ("Main.java", f"{JAVAC} Main.java", f"{JAVA} Main"),
}
COUNT = 0
COUNT_LOCK = threading.Lock()


def _version() -> str:
    try:
        return subprocess.run(["isolate", "--version"], capture_output=True, text=True, timeout=5).stdout.splitlines()[0]
    except Exception:
        return "unknown"


def _box() -> int:
    global COUNT
    with COUNT_LOCK:
        COUNT = (COUNT % 100000) + 1
        return COUNT


def _read(path: str) -> str:
    try:
        return open(path, "r", encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


def _write(path: str, text: str, mode: int = 0o644) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.chmod(path, mode)


def _meta(path: str) -> dict:
    data = {}
    for line in _read(path).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip()
    return data


def _args(box_id: int, work: str, *, time_limit: float, wall_time: float,
          memory_kb: int, fsize_kb: int) -> list[str]:
    return [
        "isolate", "-s", "-b", str(box_id),
        "-M", f"{work}/metadata.txt",
        "-t", f"{time_limit:g}",
        "-w", f"{wall_time:g}",
        "-m", str(memory_kb),
        "-f", str(fsize_kb),
        "-k", "128000",
        "-p120",
        "-E", "HOME=/tmp",
        "-E", "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "-E", "LANG=en_US.UTF-8",
        "-E", "LC_ALL=en_US.UTF-8",
        "-d", "/etc:noexec",
        "--run",
    ]


def run(body: dict) -> dict:
    language = str(body.get("language") or "cpp").lower()
    if language not in LANGUAGES:
        raise ValueError(f"unsupported language: {language}")
    source = str(body.get("source") or "")
    stdin_text = str(body.get("stdin") or "")
    time_limit = max(0.1, min(60.0, float(body.get("time") or 2.0)))
    wall_time = max(time_limit + 0.5, min(120.0, float(body.get("wallTime") or time_limit * 2 + 2)))
    memory_kb = max(16, min(4096, int(body.get("memoryMb") or 256))) * 1024
    fsize_kb = max(1, min(256, int(body.get("fsizeMb") or 4))) * 1024
    box_id = _box()
    box = f"{BOX_ROOT}/{box_id}/box"
    work = f"/tmp/isolate-{box_id}"
    source_name, compile_cmd, run_cmd = LANGUAGES[language]
    try:
        subprocess.run(["isolate", "-b", str(box_id), "--cleanup"], capture_output=True, timeout=10)
        init = subprocess.run(["isolate", "-b", str(box_id), "--init"], capture_output=True, text=True, timeout=10)
        if init.returncode != 0:
            raise RuntimeError((init.stderr or init.stdout or "isolate --init failed").strip()[:500])
        os.makedirs(work, exist_ok=True)
        os.chmod(box, 0o777)
        _write(f"{box}/{source_name}", source)
        _write(f"{work}/stdin.txt", stdin_text, 0o644)
        _write(f"{work}/metadata.txt", "", 0o666)
        _write(f"{work}/stdout.txt", "", 0o666)
        _write(f"{work}/stderr.txt", "", 0o666)
        compile_output = ""
        if compile_cmd:
            _write(f"{box}/compile", compile_cmd + "\n", 0o755)
            with open(f"{work}/compile-output.txt", "wb") as compile_handle:
                compile_result = subprocess.run(
                    _args(box_id, work, time_limit=15.0, wall_time=20.0,
                          memory_kb=max(memory_kb, 512000), fsize_kb=4096)
                    + ["--", "/bin/bash", "compile"],
                    stdin=subprocess.DEVNULL, stdout=compile_handle, stderr=subprocess.STDOUT,
                    timeout=30,
                )
            compile_output = _read(f"{work}/compile-output.txt")
            if compile_result.returncode != 0:
                return _result("CE", compile_result.returncode, "", "", compile_output, {}, box_id)
        _write(f"{box}/run", run_cmd + "\n", 0o755)
        started = time.perf_counter()
        with open(f"{work}/stdin.txt", "rb") as stdin_handle, \
                open(f"{work}/stdout.txt", "wb") as stdout_handle, \
                open(f"{work}/stderr.txt", "wb") as stderr_handle:
            result = subprocess.run(
                _args(box_id, work, time_limit=time_limit, wall_time=wall_time,
                      memory_kb=memory_kb, fsize_kb=fsize_kb)
                + ["--", "/bin/bash", "run"],
                stdin=stdin_handle, stdout=stdout_handle, stderr=stderr_handle,
                timeout=wall_time + 10,
            )
        wall = time.perf_counter() - started
        stdout = _read(f"{work}/stdout.txt")
        stderr = _read(f"{work}/stderr.txt")
        meta = _meta(f"{work}/metadata.txt")
        status = meta.get("status", "OK" if result.returncode == 0 else "RE")
        exit_code = int(meta.get("exitcode", result.returncode if result.returncode is not None else -1))
        return {
            "ok": status == "OK" and exit_code == 0,
            "status": status,
            "exit": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "compileOutput": compile_output,
            "time": float(meta.get("time", 0) or 0),
            "wallTime": float(meta.get("time-wall", wall) or wall),
            "memory": int(meta.get("max-rss", 0) or 0),
            "message": meta.get("message", ""),
            "isolate": _version(),
            "box": box_id,
            "limits": {
                "time": time_limit,
                "wallTime": wall_time,
                "memoryMb": memory_kb // 1024,
                "fsizeMb": fsize_kb // 1024,
            },
        }
    finally:
        subprocess.run(["isolate", "-b", str(box_id), "--cleanup"], capture_output=True, timeout=10)


def _result(status: str, exit_code, stdout, stderr, compile_output, meta, box_id) -> dict:
    return {
        "ok": False,
        "status": status,
        "exit": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "compileOutput": compile_output,
        "time": float(meta.get("time", 0) or 0),
        "wallTime": float(meta.get("time-wall", 0) or 0),
        "memory": int(meta.get("max-rss", 0) or 0),
        "message": meta.get("message", ""),
        "isolate": _version(),
        "box": box_id,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "AuthorIsolate/0.2"

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
            return self._json({"ok": True, "isolate": _version(), "service": "isolate-worker"})
        return self._json({"error": "Not found"}, 404)

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path != "/isolate/run":
            return self._json({"error": "Not found"}, 404)
        if TOKEN and self.headers.get("X-Isolate-Token") != TOKEN:
            return self._json({"error": "Unauthorized"}, 403)
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0 or length > 4 * 1024 * 1024:
                raise ValueError("Invalid request size")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("Invalid request")
            return self._json(run(body))
        except Exception as exc:  # noqa: BLE001
            return self._json({"error": f"{type(exc).__name__}: {exc}"}, 400)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    print(f"Author isolate worker {args.host}:{args.port} isolate={_version()}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
