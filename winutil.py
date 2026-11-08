"""Windows process helpers.

All authoring commands are console programs. When the server runs under
pythonw, Windows gives each child a new console window. We suppress that with
CREATE_NO_WINDOW + a hidden STARTUPINFO, and suppress the Windows error dialogs
that would otherwise block a run (for example a missing DLL).
"""
from __future__ import annotations

import base64
import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
SEM_FAILCRITICALERRORS = 0x0001
SEM_NOGPFAULTERRORBOX = 0x0002
SEM_NOOPENFILEERRORBOX = 0x8000


def prepare() -> None:
    """Call once in the server process. Child processes inherit the error mode."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetErrorMode(
            SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX
        )
    except Exception:
        pass


def hidden_kwargs() -> dict:
    """Keyword arguments for subprocess.Popen/run that hide the console window."""
    if os.name != "nt":
        return {}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": CREATE_NO_WINDOW, "startupinfo": startup}


def python_env() -> dict:
    """Environment for child Python processes.

    sandbox/sitecustomize.py makes their own subprocesses headless too, so a
    script like generators/crosscheck.py cannot spawn visible consoles.
    """
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    sandbox = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sandbox")
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = sandbox + (os.pathsep + existing if existing else "")
    return env


def _tree_kwargs() -> dict:
    kwargs = hidden_kwargs()
    if os.name == "nt":
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return kwargs


def terminate_tree(process: subprocess.Popen) -> None:
    """Kill the process and its children. subprocess.run only kills the direct child on Windows."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                **hidden_kwargs(),
            )
        except Exception:
            pass
        try:
            process.kill()
        except Exception:
            pass
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass


def _executor_url() -> str:
    return (os.environ.get("AUTHOR_AGENT_EXECUTOR_URL") or "").rstrip("/")


def _executor_headers() -> dict:
    token = os.environ.get("AUTHOR_AGENT_EXECUTOR_TOKEN") or ""
    return {"X-Executor-Token": token} if token else {}


def _safe_env(env: dict | None) -> dict:
    allowed = {"TEXINPUTS", "PYTHONPATH", "PYTHONIOENCODING", "LANG", "LC_ALL"}
    return {key: value for key, value in (env or {}).items() if key in allowed and isinstance(value, str)}


def _remote_run(argv: list[str], cwd, data: bytes, timeout: float, env: dict | None, measure: bool) -> dict:
    url = _executor_url()
    if not url:
        raise RuntimeError("Code execution requires the isolated executor; set AUTHOR_AGENT_EXECUTOR_URL")
    body = json.dumps({
        "argv": [str(item) for item in argv],
        "cwd": str(cwd),
        "stdin": base64.b64encode(data or b"").decode("ascii"),
        "timeout": float(timeout),
        "env": _safe_env(env),
        "measure": bool(measure),
    }).encode("utf-8")
    request = urllib.request.Request(
        url + "/run",
        data=body,
        headers={"Content-Type": "application/json", **_executor_headers()},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=float(timeout) + 30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"Executor HTTP {exc.code}: {detail[:2000]}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Executor request failed: {exc}") from exc
    if not isinstance(payload, dict) or "stdout" not in payload:
        raise RuntimeError("Executor returned an invalid response")
    return {
        "ok": bool(payload.get("ok")),
        "timedOut": bool(payload.get("timedOut")),
        "returncode": payload.get("returncode"),
        "stdout": base64.b64decode(payload.get("stdout") or ""),
        "stderr": base64.b64decode(payload.get("stderr") or ""),
        "ms": float(payload.get("ms") or 0.0),
        **({"peakRssBytes": int(payload.get("peakRssBytes") or 0)} if measure else {}),
    }


def _require_local_or_executor() -> bool:
    if _executor_url():
        return True
    if os.environ.get("AUTHOR_AGENT_REQUIRE_EXECUTOR") == "1":
        raise RuntimeError("Code execution is disabled locally; the isolated executor is required")
    return False


def run_captured(argv: list[str], cwd, data: bytes = b"", timeout: float = 10.0, env: dict | None = None) -> dict:
    """Run a bounded command and always reap its process tree on timeout."""
    if _require_local_or_executor():
        return _remote_run(argv, cwd, data, timeout, env, measure=False)
    started = time.perf_counter()
    process = subprocess.Popen(
        argv,
        cwd=str(cwd),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        **_tree_kwargs(),
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(data, timeout=timeout)
        returncode = process.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        terminate_tree(process)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            stdout, stderr = b"", b""
        returncode = None
    except Exception as exc:  # noqa: BLE001
        terminate_tree(process)
        return {
            "ok": False,
            "timedOut": False,
            "returncode": None,
            "stdout": b"",
            "stderr": str(exc).encode("utf-8", "replace"),
            "ms": (time.perf_counter() - started) * 1000,
        }
    return {
        "ok": not timed_out,
        "timedOut": timed_out,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "ms": (time.perf_counter() - started) * 1000,
    }


def run_measured(argv: list[str], cwd, data: bytes = b"", timeout: float = 30.0, env: dict | None = None) -> dict:
    """Like run_captured, but samples peak RSS for the process tree."""
    if _require_local_or_executor():
        return _remote_run(argv, cwd, data, timeout, env, measure=True)
    import threading
    import psutil

    started = time.perf_counter()
    process = subprocess.Popen(
        argv,
        cwd=str(cwd),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        **_tree_kwargs(),
    )
    peak = 0
    stop = threading.Event()

    def sample() -> None:
        nonlocal peak
        try:
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

    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    timed_out = False
    try:
        stdout, stderr = process.communicate(data, timeout=timeout)
        returncode = process.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        terminate_tree(process)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            stdout, stderr = b"", b""
        returncode = None
    except Exception as exc:  # noqa: BLE001
        terminate_tree(process)
        stdout, stderr, returncode = b"", str(exc).encode("utf-8", "replace"), None
    finally:
        stop.set()
        thread.join(timeout=0.5)
    return {
        "ok": not timed_out and returncode == 0,
        "timedOut": timed_out,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "ms": (time.perf_counter() - started) * 1000,
        "peakRssBytes": peak,
    }


def diagnostic(returncode: int | None) -> str | None:
    if returncode is None or os.name != "nt":
        return None
    code = returncode & 0xFFFFFFFF
    known = {
        0xC0000135: "The program could not start: a DLL or dependency was not found.",
        0xC0000142: "The program could not start: DLL initialization failed.",
        0xC0000139: "The program could not start: a required entry point was not found.",
        0xC0000005: "The program crashed with an access violation.",
        0xC0000409: "The program crashed with a stack buffer overrun or fast-fail.",
    }
    return known.get(code)
