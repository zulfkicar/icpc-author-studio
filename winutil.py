"""Windows process helpers.

All authoring commands are console programs. When the server runs under
pythonw, Windows gives each child a new console window. We suppress that with
CREATE_NO_WINDOW + a hidden STARTUPINFO, and suppress the Windows error dialogs
that would otherwise block a run (for example a missing DLL).
"""
from __future__ import annotations

import os
import subprocess

CREATE_NO_WINDOW = 0x08000000
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
