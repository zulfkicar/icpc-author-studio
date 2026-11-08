"""Executor allowlist/path checks. Run inside the app container."""
import sys

sys.path.insert(0, "/app")
import executor_server


def check(name, fn, expected_error=False):
    try:
        fn()
    except Exception:
        if expected_error:
            print(f"  PASS {name}")
            return
        raise
    if expected_error:
        raise AssertionError(name)
    print(f"  PASS {name}")


def main():
    check("allowed compiler", lambda: executor_server._safe_argv(["g++", "--version"]))
    check("reject /etc executable", lambda: executor_server._safe_argv(["/etc/passwd"]), True)
    check("reject shell", lambda: executor_server._safe_argv(["sh", "-c", "id"]), True)
    check("reject cwd escape", lambda: executor_server._safe_cwd("/etc"), True)
    check("workspace cwd", lambda: executor_server._safe_cwd("/app/workspaces"))
    print("EXECUTOR SECURITY TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
