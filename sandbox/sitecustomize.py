"""Loaded automatically by child Python processes (via PYTHONPATH).

It forces every subprocess started by an authoring script to be headless. This
matters when a generated script (for example a cross-check harness) launches
compiled binaries in a loop: without this, each one opens a console window.
"""
import os
import subprocess

CREATE_NO_WINDOW = 0x08000000

if os.name == "nt":
    try:
        import ctypes
        ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    except Exception:
        pass

    _RealPopen = subprocess.Popen

    def _hidden():
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        return startup

    class Popen(_RealPopen):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("creationflags", CREATE_NO_WINDOW)
            kwargs.setdefault("startupinfo", _hidden())
            super().__init__(*args, **kwargs)

    subprocess.Popen = Popen

    _real_system = os.system

    def system(command):
        process = _RealPopen(
            command, shell=True, creationflags=CREATE_NO_WINDOW, startupinfo=_hidden()
        )
        return process.wait()

    os.system = system
