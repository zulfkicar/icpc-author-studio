"""Windows process helpers.

All authoring commands are console programs. When the server runs under
pythonw, Windows gives each child a new console window. We suppress that with
CREATE_NO_WINDOW + a hidden STARTUPINFO, and suppress the Windows error dialogs
that would otherwise block a run (for example a missing DLL).
"""
from __future__ import annotations

import os
import signal
import subprocess
import time

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


def run_captured(argv: list[str], cwd, data: bytes = b"", timeout: float = 10.0, env: dict | None = None) -> dict:
    """Run a bounded command and always reap its process tree on timeout."""
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
