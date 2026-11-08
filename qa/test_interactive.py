"""Interactive harness test. Requires the executor (run inside the app container)."""
from __future__ import annotations

import os
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import verification_modes
import verify
import workspace


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS {name}")
        return
    print(f"  FAIL {name} {detail}")
    raise AssertionError(name)


INTERACTOR = """import sys
n = int(open(sys.argv[1]).read().strip())
print(n, flush=True)
line = sys.stdin.readline().strip()
try:
    value = int(line)
except ValueError:
    print("bad integer", file=sys.stderr)
    sys.exit(1)
sys.exit(0 if value == 2 * n else 1)
"""


def main() -> int:
    if not os.environ.get("AUTHOR_AGENT_EXECUTOR_URL"):
        print("SKIP interactive test: AUTHOR_AGENT_EXECUTOR_URL is not set")
        return 0
    created = workspace.create("QA Interactive", "interactive selftest")
    slug = created["slug"]
    try:
        workspace.write_text(slug, "problem.yaml", "name: QA Interactive\ntype: interactive\nlimits:\n  memory: 256\n", source="test")
        workspace.write_text(slug, "output_validator/interactor.py", INTERACTOR, source="test")
        workspace.write_text(slug, "submissions/accepted/ref.py", "n=int(input());print(2*n)\n", source="test")
        workspace.write_text(slug, "submissions/wrong_answer/wrong.py", "n=int(input());print(n+1)\n", source="test")
        workspace.write_text(slug, "input_validators/validate.py", "import sys\nn=int(sys.stdin.read().strip());sys.exit(42 if 0<n<100 else 1)\n", source="test")
        workspace.write_text(slug, "data/sample/01.in", "21\n", source="test")
        workspace.write_text(slug, "data/secret/01.in", "7\n", source="test")
        result = verification_modes.interactive_selftest(slug)
        check("interactive selftest passes", result["status"] == "pass", result)
        check("reference accepted", any(case["name"].startswith("reference") and case["pass"] for case in result["cases"]), result["cases"])
        check("wrong rejected", any(case["name"].startswith("negative") and case["pass"] for case in result["cases"]), result["cases"])
        check("transcript captured", any(case.get("transcript") for case in result["cases"]), result["cases"])
        report = verify.verify(slug)
        check("interactive package verifies", report["status"] == "verified", report)
    finally:
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)
    print("INTERACTIVE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
