"""Real Isolate worker with source-run, argv-run and interactive endpoints.

The default compose points the app's executor at this service so the
deterministic verifier (compilers, validators, checkers, interactors and
solutions) runs through Isolate 1.8.1 rather than bwrap. The bwrap executor is
kept for the LaTeX statement step and as a fallback.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import shutil
import subprocess
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WORKSPACES = pathlib.Path(os.environ.get("AUTHOR_AGENT_WORKSPACES", "/app/workspaces")).resolve()
TEMPLATES = pathlib.Path("/app/templates")
BOX_ROOT = "/var/local/lib/isolate"
TOKEN = os.environ.get("AUTHOR_AGENT_ISOLATE_TOKEN", "")
PYTHON = "/usr/local/python-3.8.1/bin/python3"
PYTHON3 = "/usr/bin/python3"
GCC = "/usr/local/gcc-9.2.0/bin/g++"
GCC_C = "/usr/local/gcc-9.2.0/bin/gcc"
JAVAC = "/usr/local/bin/javac"
JAVA = "/usr/local/bin/java"
MAX_OUTPUT = 4 * 1024 * 1024
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


def _number(value, default: float = 0.0) -> float:
    """Parse isolate metadata without letting one bad line fail the request."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _limits(body: dict) -> dict:
    def number(name: str, default: float, low: float, high: float) -> float:
        try:
            value = float(body.get(name, default))
        except (TypeError, ValueError):
            value = default
        return max(low, min(high, value))

    return {
        "time": number("time", number("timeout", 5.0, 0.1, 120.0), 0.1, 120.0),
        "wall": number("wallTime", number("timeout", 10.0, 0.1, 150.0) + 2.0, 0.2, 150.0),
        "memory": int(number("memoryMb", 1024, 16, 4096)) * 1024,
        "fsize": int(number("fsizeMb", 64, 1, 256)) * 1024,
    }


def _isolate_args(box_id: int, work: str, limits: dict, cwd: str | None = None,
                  env: dict | None = None) -> list[str]:
    args = [
        "isolate", "-s", "-b", str(box_id),
        "-M", f"{work}/metadata.txt",
        "-t", f"{limits['time']:g}",
        "-w", f"{limits['wall']:g}",
        "-m", str(limits["memory"]),
        "-f", str(limits["fsize"]),
        "-k", "128000",
        "-p120",
        "-E", "HOME=/tmp",
        "-E", "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "-E", "LANG=en_US.UTF-8",
        "-E", "LC_ALL=en_US.UTF-8",
        "-d", "/etc:noexec",
    ]
    if TEMPLATES.is_dir():
        args.extend(["-d", "/app/templates"])
    for key, value in (env or {}).items():
        if key in ("TEXINPUTS", "PYTHONPATH", "PYTHONIOENCODING", "LANG", "LC_ALL") and isinstance(value, str):
            args.extend(["-E", f"{key}={value}"])
    if cwd:
        args.extend(["-c", cwd])
    args.append("--run")
    return args


def _copy_workspace(source: pathlib.Path, temp: pathlib.Path, include_data: bool = True) -> None:
    temp.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.name in (".agent", "__pycache__", ".git"):
            continue
        # Test data can be tens of megabytes. Validator and solution runs get
        # their input on stdin and never open data/; checkers and interactors
        # pass data paths in argv, so detect that case before the copy.
        if item.name == "data" and not include_data:
            continue
        target = temp / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
    build = source / ".agent" / "build"
    if build.is_dir():
        shutil.copytree(build, temp / ".agent" / "build")
    for binary in temp.rglob("*.exe"):
        try:
            binary.chmod(0o755)
        except OSError:
            pass


def _sync_workspace(box: pathlib.Path, source: pathlib.Path) -> None:
    for item in box.iterdir():
        if item.name in (".agent", ".harness.py", ".harness.json", ".harness-result.json"):
            continue
        target = source / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
    build = box / ".agent" / "build"
    if build.is_dir():
        target = source / ".agent" / "build"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(build, target)
        for binary in target.rglob("*.exe"):
            try:
                binary.chmod(0o755)
            except OSError:
                pass


def _workspace_root(cwd: pathlib.Path) -> pathlib.Path | None:
    try:
        relative = cwd.resolve().relative_to(WORKSPACES)
    except ValueError:
        return None
    if not relative.parts:
        return None
    return WORKSPACES / relative.parts[0]


def _rewrite(path: str, source: pathlib.Path) -> str:
    value = pathlib.Path(path)
    if value.is_absolute():
        try:
            return "/box/" + value.resolve().relative_to(source).as_posix()
        except ValueError:
            pass
    name = value.name
    if name == "g++":
        return GCC
    if name == "gcc":
        return GCC_C
    if name in ("python", "python3"):
        return PYTHON3
    if name == "javac":
        return JAVAC
    if name == "java":
        return JAVA
    return path


def _rewrite_argv(argv: list[str], source: pathlib.Path) -> list[str]:
    out = []
    for item in argv:
        if item == "-std=gnu++20":
            out.append("-std=gnu++2a")
            continue
        if item == "-std=c++20":
            out.append("-std=c++2a")
            continue
        if item.startswith("/") and not item.startswith("/box/") and not item.startswith("/usr/") and not item.startswith("/bin/") and not item.startswith("/lib"):
            try:
                target = pathlib.Path(item).resolve()
            except OSError:
                target = pathlib.Path(item)
            try:
                relative = target.relative_to(source)
            except ValueError:
                relative = None
            if relative is not None:
                out.append("/box/" + relative.as_posix())
                continue
            if str(item).startswith("/app/workspaces/"):
                raise ValueError("Argument path is outside the selected workspace")
        out.append(_rewrite(item, source))
    return out


def _needs_data(source: pathlib.Path, argv: list[str], cwd: pathlib.Path) -> bool:
    for value in [str(cwd)] + [item for item in argv if item.startswith("/")]:
        try:
            relative = pathlib.Path(value).resolve().relative_to(source)
        except (OSError, ValueError):
            continue
        if relative.parts and relative.parts[0] == "data":
            return True
    return False


def _new_box(source: pathlib.Path, cwd: pathlib.Path, argv: list[str] | None = None) -> tuple[int, pathlib.Path, pathlib.Path]:
    box_id = _box()
    work = pathlib.Path(f"/tmp/isolate-run-{box_id}")
    temp = work / "workspace"
    _copy_workspace(source, temp, include_data=_needs_data(source, argv or [], cwd))
    _write(f"{work}/stdin.txt", "", 0o644)
    _write(f"{work}/metadata.txt", "", 0o666)
    _write(f"{work}/stdout.txt", "", 0o666)
    _write(f"{work}/stderr.txt", "", 0o666)
    subprocess.run(["isolate", "-b", str(box_id), "--cleanup"], capture_output=True, timeout=10)
    init = subprocess.run(["isolate", "-b", str(box_id), "--init"], capture_output=True, text=True, timeout=10)
    if init.returncode != 0:
        shutil.rmtree(work, ignore_errors=True)
        raise RuntimeError((init.stderr or init.stdout or "isolate --init failed").strip()[:500])
    box = pathlib.Path(f"{BOX_ROOT}/{box_id}/box")
    os.chmod(box, 0o777)
    for item in temp.iterdir():
        target = box / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
    for binary in box.rglob("*.exe"):
        try:
            binary.chmod(0o755)
        except OSError:
            pass
    return box_id, work, box


def _cleanup(box_id: int, work: pathlib.Path) -> None:
    subprocess.run(["isolate", "-b", str(box_id), "--cleanup"], capture_output=True, timeout=10)
    shutil.rmtree(work, ignore_errors=True)


def _run_box(box_id: int, work: pathlib.Path, argv: list[str], cwd: str | None,
             limits: dict, env: dict | None) -> dict:
    started = time.perf_counter()
    with open(f"{work}/stdin.txt", "rb") as stdin_handle, \
            open(f"{work}/stdout.txt", "wb") as stdout_handle, \
            open(f"{work}/stderr.txt", "wb") as stderr_handle:
        try:
            process = subprocess.run(
                _isolate_args(box_id, str(work), limits, cwd, env) + ["--"] + argv,
                stdin=stdin_handle, stdout=stdout_handle, stderr=stderr_handle,
                timeout=limits["wall"] + 10,
            )
            returncode = process.returncode
            timed_out = False
        except subprocess.TimeoutExpired:
            returncode = None
            timed_out = True
    wall = time.perf_counter() - started
    meta = _meta(f"{work}/metadata.txt")
    status = meta.get("status", "OK" if returncode == 0 else "RE")
    if meta.get("status") == "TO":
        timed_out = True
    if timed_out:
        returncode = None
    try:
        exit_code = int(meta.get("exitcode", returncode if returncode is not None else -1))
    except ValueError:
        exit_code = returncode
    stdout = _read(f"{work}/stdout.txt")
    stderr = _read(f"{work}/stderr.txt")
    return {
        "ok": not timed_out and (returncode == 0 if returncode is not None else False),
        "meta": meta,
        "timedOut": timed_out,
        "returncode": returncode,
        "exit": exit_code,
        "status": status,
        "stdout": stdout,
        "stderr": stderr,
        "time": _number(meta.get("time"), 0.0),
        "wallTime": _number(meta.get("time-wall"), wall),
        "memoryKb": int(meta.get("max-rss", 0) or 0),
        "message": meta.get("message", ""),
    }


def run_argv(body: dict) -> dict:
    argv = body.get("argv") or []
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        raise ValueError("argv must be a non-empty string list")
    cwd_path = pathlib.Path(str(body.get("cwd") or WORKSPACES)).resolve()
    source = _workspace_root(cwd_path)
    if source is None:
        raise ValueError("Working directory is outside the workspace volume")
    relative = cwd_path.relative_to(source)
    rewritten = _rewrite_argv(argv, source)
    limits = _limits(body)
    stdin = base64.b64decode(body.get("stdin") or "")
    measure = bool(body.get("measure"))
    box_id = None
    work = None
    try:
        box_id, work, box = _new_box(source, cwd_path, argv)
        with open(f"{work}/stdin.txt", "wb") as handle:
            handle.write(stdin)
        cwd = "/box" if not relative.parts else "/box/" + relative.as_posix()
        result = _run_box(box_id, work, rewritten, cwd, limits, body.get("env"))
        _sync_workspace(box, source)
        return {
            "ok": (not result["timedOut"] and result["exit"] == 0) if measure else (not result["timedOut"]),
            "timedOut": result["timedOut"],
            "returncode": None if result["timedOut"] else result["exit"],
            "stdout": base64.b64encode(result["stdout"].encode("utf-8")[:MAX_OUTPUT]).decode("ascii"),
            "stderr": base64.b64encode(result["stderr"].encode("utf-8")[:MAX_OUTPUT]).decode("ascii"),
            "ms": result["wallTime"] * 1000,
            "peakRssBytes": result["memoryKb"] * 1024,
            "status": result["status"],
            "debugMeta": result.get("meta"),
            "isolate": _version(),
        }
    finally:
        if box_id is not None and work is not None:
            _cleanup(box_id, work)


HARNESS = r'''import base64, json, os, signal, subprocess, sys, threading, time
CFG = json.load(open("/box/.harness.json"))
RESULT = {"transcript": [], "validatorReturncode": None, "solutionReturncode": None, "timedOut": False}
LOCK = threading.Lock()
def log(direction, data):
    text = data.decode("utf-8", "replace")
    for line in text.splitlines() or [""]:
        with LOCK:
            RESULT["transcript"].append({"direction": direction, "text": line[:2000]})
def pump(source, target, direction):
    try:
        while True:
            chunk = os.read(source.fileno(), 4096)
            if not chunk:
                break
            log(direction, chunk)
            os.write(target.fileno(), chunk)
    except Exception:
        pass
    finally:
        try:
            target.close()
        except Exception:
            pass
validator = subprocess.Popen(CFG["validator"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
solution = subprocess.Popen(CFG["solution"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
threads = [threading.Thread(target=pump, args=(validator.stdout, solution.stdin, "judge"), daemon=True),
           threading.Thread(target=pump, args=(solution.stdout, validator.stdin, "solution"), daemon=True)]
for thread in threads:
    thread.start()
try:
    validator.wait(timeout=CFG["timeout"])
    solution.wait(timeout=2)
except subprocess.TimeoutExpired:
    RESULT["timedOut"] = True
    for process in (validator, solution):
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
for thread in threads:
    thread.join(timeout=1)
RESULT["validatorReturncode"] = validator.returncode
RESULT["solutionReturncode"] = solution.returncode
try:
    RESULT["validatorStderr"] = base64.b64encode(validator.stderr.read()).decode("ascii")
    RESULT["solutionStderr"] = base64.b64encode(solution.stderr.read()).decode("ascii")
except Exception:
    RESULT["validatorStderr"] = ""
    RESULT["solutionStderr"] = ""
json.dump(RESULT, open("/box/.harness-result.json", "w"))
'''


def run_interactive(body: dict) -> dict:
    solution = body.get("solution") or []
    validator = body.get("validator") or []
    for name, argv in (("solution", solution), ("validator", validator)):
        if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
            raise ValueError(f"{name} must be a non-empty string list")
    cwd_path = pathlib.Path(str(body.get("cwd") or WORKSPACES)).resolve()
    source = _workspace_root(cwd_path)
    if source is None:
        raise ValueError("Working directory is outside the workspace volume")
    relative = cwd_path.relative_to(source)
    timeout = max(1.0, min(120.0, _number(body.get("timeout"), 20.0)))
    accepted = {int(item) for item in (body.get("acceptedExitCodes") or [0])}
    limits = {"time": timeout, "wall": timeout + 5.0, "memory": 1024 * 1024, "fsize": 64 * 1024}
    box_id = None
    work = None
    try:
        box_id, work, box = _new_box(source, cwd_path, solution + validator)
        _write(f"{box}/.harness.py", HARNESS, 0o755)
        config = {
            "solution": _rewrite_argv(solution, source),
            "validator": _rewrite_argv(validator, source),
            "timeout": timeout,
        }
        _write(f"{box}/.harness.json", json.dumps(config), 0o644)
        result = _run_box(box_id, work, [PYTHON3, "/box/.harness.py"], "/box", limits, None)
        payload = {}
        try:
            payload = json.loads(_read(f"{box}/.harness-result.json"))
        except ValueError:
            payload = {}
        _sync_workspace(box, source)
        validator_returncode = payload.get("validatorReturncode")
        timed_out = bool(payload.get("timedOut")) or result["timedOut"]
        ok = not timed_out and validator_returncode in accepted
        return {
            "ok": ok,
            "timedOut": timed_out,
            "validatorReturncode": validator_returncode,
            "solutionReturncode": payload.get("solutionReturncode"),
            "acceptedExitCodes": sorted(accepted),
            "transcript": payload.get("transcript", [])[:5000],
            "validatorStderr": payload.get("validatorStderr", ""),
            "solutionStderr": payload.get("solutionStderr", ""),
            "status": result["status"],
            "isolate": _version(),
        }
    finally:
        if box_id is not None and work is not None:
            _cleanup(box_id, work)


# ------------------------- source-run API -------------------------
def run(body: dict) -> dict:
    language = str(body.get("language") or "cpp").lower()
    if language not in LANGUAGES:
        raise ValueError(f"unsupported language: {language}")
    source = str(body.get("source") or "")
    stdin_text = str(body.get("stdin") or "")
    time_limit = max(0.1, min(60.0, _number(body.get("time"), 2.0)))
    wall_time = max(time_limit + 0.5, min(120.0, _number(body.get("wallTime"), time_limit * 2 + 2)))
    memory_kb = max(16, min(4096, int(body.get("memoryMb") or 256))) * 1024
    fsize_kb = max(1, min(256, int(body.get("fsizeMb") or 4))) * 1024
    box_id = _box()
    work = f"/tmp/isolate-source-{box_id}"
    box_path = f"{BOX_ROOT}/{box_id}/box"
    source_name, compile_cmd, run_cmd = LANGUAGES[language]
    try:
        subprocess.run(["isolate", "-b", str(box_id), "--cleanup"], capture_output=True, timeout=10)
        init = subprocess.run(["isolate", "-b", str(box_id), "--init"], capture_output=True, text=True, timeout=10)
        if init.returncode != 0:
            raise RuntimeError((init.stderr or init.stdout or "isolate --init failed").strip()[:500])
        os.makedirs(work, exist_ok=True)
        os.chmod(box_path, 0o777)
        _write(f"{box_path}/{source_name}", source)
        _write(f"{work}/stdin.txt", stdin_text, 0o644)
        _write(f"{work}/metadata.txt", "", 0o666)
        _write(f"{work}/stdout.txt", "", 0o666)
        _write(f"{work}/stderr.txt", "", 0o666)
        compile_output = ""
        limits = {"time": 15.0, "wall": 20.0, "memory": max(memory_kb, 512000), "fsize": 4096}
        if compile_cmd:
            _write(f"{box_path}/compile", compile_cmd + "\n", 0o755)
            with open(f"{work}/compile-output.txt", "wb") as compile_handle:
                try:
                    compile_result = subprocess.run(
                        _isolate_args(box_id, work, limits) + ["--", "/bin/bash", "compile"],
                        stdin=subprocess.DEVNULL, stdout=compile_handle, stderr=subprocess.STDOUT, timeout=30,
                    )
                    compile_rc = compile_result.returncode
                except subprocess.TimeoutExpired:
                    compile_rc = None
            compile_output = _read(f"{work}/compile-output.txt")
            if compile_rc != 0:
                return _result("CE", compile_rc or 1, "", "", compile_output, {}, box_id)
        _write(f"{box_path}/run", run_cmd + "\n", 0o755)
        limits = {"time": time_limit, "wall": wall_time, "memory": memory_kb, "fsize": fsize_kb}
        with open(f"{work}/stdin.txt", "rb") as stdin_handle, \
                open(f"{work}/stdout.txt", "wb") as stdout_handle, \
                open(f"{work}/stderr.txt", "wb") as stderr_handle:
            try:
                result = subprocess.run(
                    _isolate_args(box_id, work, limits) + ["--", "/bin/bash", "run"],
                    stdin=stdin_handle, stdout=stdout_handle, stderr=stderr_handle,
                    timeout=wall_time + 10,
                )
                returncode = result.returncode
                timed_out = False
            except subprocess.TimeoutExpired:
                returncode = None
                timed_out = True
        stdout = _read(f"{work}/stdout.txt")
        stderr = _read(f"{work}/stderr.txt")
        meta = _meta(f"{work}/metadata.txt")
        status = "TO" if timed_out else meta.get("status", "OK" if returncode == 0 else "RE")
        exit_code = int(meta.get("exitcode", returncode if returncode is not None else -1))
        return {
            "ok": not timed_out and status == "OK" and exit_code == 0,
            "status": status,
            "exit": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "compileOutput": compile_output,
            "time": _number(meta.get("time"), 0.0),
            "wallTime": _number(meta.get("time-wall"), 0.0),
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
        shutil.rmtree(work, ignore_errors=True)


def _result(status: str, exit_code, stdout, stderr, compile_output, meta, box_id) -> dict:
    return {
        "ok": False,
        "status": status,
        "exit": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "compileOutput": compile_output,
        "time": _number(meta.get("time"), 0.0),
        "wallTime": _number(meta.get("time-wall"), 0.0),
        "memory": int(meta.get("max-rss", 0) or 0),
        "message": meta.get("message", ""),
        "isolate": _version(),
        "box": box_id,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "AuthorIsolate/0.4"

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
        path = urllib.parse.urlparse(self.path).path
        if path not in ("/run", "/interact", "/isolate/run"):
            return self._json({"error": "Not found"}, 404)
        if TOKEN and self.headers.get("X-Isolate-Token") != TOKEN:
            return self._json({"error": "Unauthorized"}, 403)
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0 or length > 12 * 1024 * 1024:
                raise ValueError("Invalid request size")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("Invalid request")
            if path == "/run":
                return self._json(run_argv(body))
            if path == "/interact":
                return self._json(run_interactive(body))
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
