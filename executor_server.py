"""Isolated execution worker with an Isolate-style contract.

The authoring app never compiles or runs model-written code itself. It sends
bounded commands here over an internal Docker network. This process has no API
key, no app source, no host port and no external network. It sees only the
workspace volume.

Each run is copied into a private temporary directory and executed under a
bubblewrap mount namespace. The child gets:

* a read-only system root,
* only ``/work`` (the per-run copy) writable,
* no network namespace (``--unshare-all``),
* no access to ``/app/workspaces`` (absolute cross-workspace reads fail),
* resource limits for CPU, address space, process count, stack, file size and
  open files.

``POST /isolate/run`` exposes the same limits with Isolate-style names
(``time``, ``wallTime``, ``memory``, ``processes``, ``stack``, ``fsize``,
``openFiles``) and returns Isolate-style metadata (``status``, ``exit``,
``time``, ``wallTime``, ``maxRssKb``, ``message``).
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import resource
import shutil
import signal
import subprocess
import sys
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
BWRAP = shutil.which("bwrap")

# RLIMIT_NPROC applies to the real UID. Setting it before bwrap makes bwrap's
# own clone fail because the container already has many threads for uid 1000.
# Apply it inside the user namespace instead, then exec the target.
NPROC_WRAPPER = (
    "import os,resource,sys\n"
    "try:\n"
    "    n=int(sys.argv[1]); resource.setrlimit(resource.RLIMIT_NPROC,(n,n))\n"
    "except Exception:\n"
    "    pass\n"
    "os.execv(sys.argv[2], sys.argv[2:])\n"
)

MIB = 1024 * 1024
DEFAULT_LIMITS = {
    "time": 10.0,
    "wallTime": 20.0,
    "memoryMb": 1024,
    "processes": 64,
    "stackMb": 64,
    "fsizeMb": 64,
    "openFiles": 256,
}


def _workspace_root(cwd: pathlib.Path) -> pathlib.Path | None:
    try:
        relative = cwd.resolve().relative_to(WORKSPACES)
    except ValueError:
        return None
    if not relative.parts:
        return None
    return WORKSPACES / relative.parts[0]


def _copy_workspace(source: pathlib.Path, temp: pathlib.Path) -> None:
    temp.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.name in (".agent", "__pycache__", ".git"):
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


def _sync_workspace(temp: pathlib.Path, source: pathlib.Path) -> None:
    for item in temp.iterdir():
        if item.name == ".agent":
            continue
        target = source / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
    build = temp / ".agent" / "build"
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


def _rewrite_path(value: str, source: pathlib.Path, target_root: pathlib.Path) -> str:
    path = pathlib.Path(value)
    if not path.is_absolute():
        return value
    try:
        relative = path.resolve().relative_to(source)
    except ValueError:
        return value
    return str(target_root / relative)


def _rewrite_argv(argv: list[str], source: pathlib.Path, target_root: pathlib.Path) -> list[str]:
    return [_rewrite_path(item, source, target_root) for item in argv]


def _bwrap_command(
    argv: list[str],
    cwd: pathlib.Path,
    source: pathlib.Path,
    temp: pathlib.Path,
    *,
    processes: int | None = None,
) -> list[str]:
    relative = cwd.relative_to(source)
    work_cwd = "/work" if not relative.parts else "/work/" + relative.as_posix()
    command = [
        str(BWRAP),
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        # Read-only system root. /app is intentionally not bound, so the child
        # cannot see /app/workspaces or the app's config.
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/usr/local", "/usr/local",
        "--ro-bind", "/bin", "/bin",
        "--ro-bind", "/lib", "/lib",
        "--ro-bind", "/lib64", "/lib64",
        "--ro-bind", "/etc", "/etc",
        "--ro-bind", "/var", "/var",
        "--ro-bind", "/sys", "/sys",
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--bind", str(temp), "/work",
        "--chdir", work_cwd,
        "--cap-drop", "ALL",
    ]
    for optional in ("/app/templates", "/app/sandbox"):
        if pathlib.Path(optional).is_dir():
            command.extend(["--ro-bind", optional, optional])
    command.append("--")
    child = _rewrite_argv(argv, source, pathlib.Path("/work"))
    if processes:
        child = [sys.executable, "-c", NPROC_WRAPPER, str(int(processes)), *child]
    command.extend(child)
    return command


def _safe_cwd(value: str) -> pathlib.Path:
    path = pathlib.Path(value or str(WORKSPACES)).resolve()
    if not path.is_relative_to(WORKSPACES):
        raise ValueError("Working directory is outside the workspace volume")
    return path


def _safe_argv(argv: list[str], *, allow_workspace_exec: bool = True) -> list[str]:
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        raise ValueError("argv must be a non-empty string list")
    first = pathlib.Path(argv[0])
    if first.is_absolute():
        resolved = first.resolve()
        if (first.name in ALLOWED or resolved.name in ALLOWED) and resolved.is_file():
            pass
        elif not allow_workspace_exec or not resolved.is_relative_to(WORKSPACES) or not resolved.is_file():
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


def _limits(
    timeout: float,
    memory_bytes: int | None = None,
    *,
    processes: int | None = None,
    stack_bytes: int | None = None,
    fsize_bytes: int | None = None,
    nofile: int | None = None,
):
    cpu = max(1, int(timeout) + 2)

    def apply() -> None:
        os.setsid()
        os.umask(0o077)
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (fsize_bytes or 256 * MIB, fsize_bytes or 256 * MIB))
        if memory_bytes:
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        if processes:
            resource.setrlimit(resource.RLIMIT_NPROC, (max(16, processes), max(16, processes)))
        if stack_bytes:
            resource.setrlimit(resource.RLIMIT_STACK, (stack_bytes, stack_bytes))
        if nofile:
            resource.setrlimit(resource.RLIMIT_NOFILE, (max(16, nofile), max(16, nofile)))

    return apply


def _limit_values(body: dict) -> dict:
    def number(name: str, default: float, minimum: float, maximum: float) -> float:
        try:
            value = float(body.get(name, default))
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    return {
        "time": number("time", float(body.get("timeout") or DEFAULT_LIMITS["time"]), 0.1, MAX_TIMEOUT),
        "wallTime": number("wallTime", float(body.get("timeout") or DEFAULT_LIMITS["wallTime"]), 0.1, MAX_TIMEOUT),
        "memoryMb": int(number("memory", float(body.get("memory") or DEFAULT_LIMITS["memoryMb"]), 16, 4096)),
        "processes": int(number("processes", DEFAULT_LIMITS["processes"], 1, 512)),
        "stackMb": int(number("stack", DEFAULT_LIMITS["stackMb"], 1, 256)),
        "fsizeMb": int(number("fsize", DEFAULT_LIMITS["fsizeMb"], 1, 256)),
        "openFiles": int(number("openFiles", DEFAULT_LIMITS["openFiles"], 16, 1024)),
    }


def _status(timed_out: bool, returncode: int | None, peak: int, memory_bytes: int, stderr: bytes = b"") -> str:
    if timed_out:
        return "TL"
    if returncode is None:
        return "XX"
    text = stderr.decode("utf-8", "replace").lower()
    if any(token in text for token in ("memoryerror", "cannot allocate memory", "out of memory", "std::bad_alloc")):
        return "ML"
    if memory_bytes and peak >= int(memory_bytes * 0.92):
        return "ML"
    if returncode < 0:
        return "SG"
    if returncode != 0:
        return "RE"
    return "OK"


def _execute(body: dict, *, isolate_style: bool = False) -> dict:
    argv = _safe_argv(body.get("argv") or [])
    cwd = _safe_cwd(str(body.get("cwd") or WORKSPACES))
    limits = _limit_values(body)
    timeout = limits["wallTime"]
    stdin = base64.b64decode(body.get("stdin") or "")
    env = _safe_env(body.get("env"))
    measure = bool(body.get("measure")) or isolate_style
    memory_bytes = limits["memoryMb"] * MIB
    command = argv
    popen_cwd = cwd
    source = _workspace_root(cwd)
    temp = None
    if source is not None:
        temp = pathlib.Path("/tmp") / f"author-run-{os.getpid()}-{threading.get_ident()}-{time.time_ns()}"
        _copy_workspace(source, temp)
        if BWRAP:
            command = _bwrap_command(argv, cwd, source, temp, processes=limits["processes"])
            popen_cwd = temp
        else:
            command = _rewrite_argv(argv, source, temp)
            popen_cwd = temp / cwd.relative_to(source)
    started = time.perf_counter()
    try:
        process = subprocess.Popen(
            command,
            cwd=str(popen_cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            preexec_fn=_limits(
                timeout,
                memory_bytes if measure else None,
                processes=None if BWRAP else limits["processes"],
                stack_bytes=limits["stackMb"] * MIB,
                fsize_bytes=limits["fsizeMb"] * MIB,
                nofile=limits["openFiles"],
            ),
        )
    except Exception:
        if temp is not None:
            shutil.rmtree(temp, ignore_errors=True)
        raise
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
        cpu_time = None
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
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except Exception:
            pass
        if source is not None and temp is not None:
            try:
                _sync_workspace(temp, source)
            finally:
                shutil.rmtree(temp, ignore_errors=True)
    wall = time.perf_counter() - started
    status = _status(timed_out, returncode, peak, memory_bytes, stderr)
    message = stderr.decode("utf-8", "replace").strip().splitlines()[-1][:500] if stderr else ""
    payload = {
        "ok": not timed_out and (returncode == 0 if measure else True),
        "timedOut": timed_out,
        "returncode": returncode,
        "stdout": base64.b64encode(stdout[:MAX_OUTPUT]).decode("ascii"),
        "stderr": base64.b64encode(stderr[:MAX_OUTPUT]).decode("ascii"),
        "ms": wall * 1000,
        "peakRssBytes": peak,
    }
    if isolate_style:
        payload.update({
            "status": status,
            "exit": returncode,
            "time": wall,
            "wallTime": wall,
            "maxRssKb": peak // 1024,
            "message": message,
            "limits": limits,
            "sandbox": {
                "bwrap": bool(BWRAP),
                "network": False,
                "readOnlyRoot": True,
                "writable": ["/work", "/tmp"],
                "hidden": ["/app/workspaces"],
            },
        })
    return payload


def run(body: dict) -> dict:
    return _execute(body)


def isolate_run(body: dict) -> dict:
    """Isolate-compatible run endpoint. See the module docstring."""
    return _execute(body, isolate_style=True)


def run_interactive(body: dict) -> dict:
    """Run a validator/interactor and a solution with connected pipes."""
    validator = _safe_argv(body.get("validator") or [])
    solution = _safe_argv(body.get("solution") or [])
    cwd = _safe_cwd(str(body.get("cwd") or WORKSPACES))
    limits = _limit_values(body)
    timeout = max(1.0, min(MAX_TIMEOUT, float(body.get("timeout") or 20.0)))
    accepted = {int(item) for item in (body.get("acceptedExitCodes") or [0])}
    source = _workspace_root(cwd)
    temp = None
    validator_cmd = validator
    solution_cmd = solution
    popen_cwd = cwd
    if source is not None:
        temp = pathlib.Path("/tmp") / f"author-int-{os.getpid()}-{threading.get_ident()}-{time.time_ns()}"
        _copy_workspace(source, temp)
        if BWRAP:
            validator_cmd = _bwrap_command(validator, cwd, source, temp, processes=limits["processes"])
            solution_cmd = _bwrap_command(solution, cwd, source, temp, processes=limits["processes"])
            popen_cwd = temp
        else:
            validator_cmd = _rewrite_argv(validator, source, temp)
            solution_cmd = _rewrite_argv(solution, source, temp)
            popen_cwd = temp / cwd.relative_to(source)
    transcript: list[dict] = []
    lock = threading.Lock()

    def log(direction: str, data: bytes) -> None:
        if not data:
            return
        text = data.decode("utf-8", "replace")
        for line in text.splitlines() or [""]:
            with lock:
                transcript.append({"direction": direction, "text": line[:2000]})

    try:
        validator_proc = subprocess.Popen(
            validator_cmd, cwd=str(popen_cwd), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=_limits(
                timeout,
                limits["memoryMb"] * MIB,
                processes=None if BWRAP else limits["processes"],
                stack_bytes=limits["stackMb"] * MIB,
                fsize_bytes=limits["fsizeMb"] * MIB,
                nofile=limits["openFiles"],
            ),
        )
        solution_proc = subprocess.Popen(
            solution_cmd, cwd=str(popen_cwd), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=_limits(
                timeout,
                limits["memoryMb"] * MIB,
                processes=None if BWRAP else limits["processes"],
                stack_bytes=limits["stackMb"] * MIB,
                fsize_bytes=limits["fsizeMb"] * MIB,
                nofile=limits["openFiles"],
            ),
        )
    except Exception:
        if temp is not None:
            shutil.rmtree(temp, ignore_errors=True)
        raise

    def pump(source_fd: int, target_fd: int, direction: str) -> None:
        try:
            while True:
                chunk = os.read(source_fd, 4096)
                if not chunk:
                    break
                log(direction, chunk)
                os.write(target_fd, chunk)
        except Exception:
            pass
        finally:
            try:
                os.close(target_fd)
            except Exception:
                pass

    threads = [
        threading.Thread(target=pump, args=(validator_proc.stdout.fileno(), solution_proc.stdin.fileno(), "judge"), daemon=True),
        threading.Thread(target=pump, args=(solution_proc.stdout.fileno(), validator_proc.stdin.fileno(), "solution"), daemon=True),
    ]
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        validator_proc.wait(timeout=timeout)
        solution_proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        timed_out = True
        for proc in (validator_proc, solution_proc):
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
    for thread in threads:
        thread.join(timeout=1)
    for proc in (validator_proc, solution_proc):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            pass
    validator_err = validator_proc.stderr.read() if validator_proc.stderr else b""
    solution_err = solution_proc.stderr.read() if solution_proc.stderr else b""
    if source is not None and temp is not None:
        try:
            _sync_workspace(temp, source)
        finally:
            shutil.rmtree(temp, ignore_errors=True)
    return {
        "ok": not timed_out and validator_proc.returncode in accepted,
        "timedOut": timed_out,
        "validatorReturncode": validator_proc.returncode,
        "solutionReturncode": solution_proc.returncode,
        "acceptedExitCodes": sorted(accepted),
        "transcript": transcript[:5000],
        "validatorStderr": base64.b64encode(validator_err[:MAX_OUTPUT]).decode("ascii"),
        "solutionStderr": base64.b64encode(solution_err[:MAX_OUTPUT]).decode("ascii"),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "AuthorExecutor/0.2"

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
            return self._json({
                "ok": True,
                "worker": "executor",
                "slots": SEMAPHORE._value,
                "bwrap": bool(BWRAP),
                "contract": "isolate-compatible",
            })
        return self._json({"error": "Not found"}, 404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path not in ("/run", "/interact", "/isolate/run"):
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
                if path == "/interact":
                    return self._json(run_interactive(body))
                if path == "/isolate/run":
                    return self._json(isolate_run(body))
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
