"""Interactive harness test. Requires the executor (run inside the app container)."""
from __future__ import annotations

import os
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from author_studio.judging import verification_modes
from author_studio.judging import verify
from author_studio.packages import workspace


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS {name}")
        return
    print(f"  FAIL {name} {detail}")
    raise AssertionError(name)


INTERACTOR = """import sys
# ICPC spec contract: input, answer, feedback_dir; interaction on stdin/stdout.
n = int(open(sys.argv[1]).read().strip())
answer = int(open(sys.argv[2]).read().strip())
print(n, flush=True)
line = sys.stdin.readline().strip()
try:
    value = int(line)
except ValueError:
    print("bad integer", file=sys.stderr)
    sys.exit(43)
sys.exit(42 if value == answer else 43)
"""

TRANSCRIPT_CHECKER = """import sys
# ICPC spec contract over the captured interaction transcript.
inp, ans, feedback = sys.argv[1], sys.argv[2], sys.argv[3]
n = int(open(inp).read().strip())
lines = [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]
expected = ["< %d" % n, "> %d" % (2 * n)]
sys.exit(42 if lines == expected else 43)
"""

INTERACTION = """< 21
> 42
"""


def main() -> int:
    if not os.environ.get("AUTHOR_AGENT_EXECUTOR_URL"):
        print("SKIP interactive test: AUTHOR_AGENT_EXECUTOR_URL is not set")
        return 0
    created = workspace.create("QA Interactive", "interactive selftest")
    slug = created["slug"]
    try:
        workspace.write_text(slug, "problem.yaml", "name: QA Interactive\ntype: interactive\nvalidation: custom interactive\nlimits:\n  memory: 256\n", source="test")
        workspace.write_text(slug, "output_validators/interactor.py", INTERACTOR, source="test")
        workspace.write_text(slug, "output_validators/transcript_checker.py", TRANSCRIPT_CHECKER, source="test")
        workspace.write_text(slug, "submissions/accepted/ref.py", "n=int(input());print(2*n)\n", source="test")
        workspace.write_text(slug, "submissions/wrong_answer/wrong.py", "n=int(input());print(n+1)\n", source="test")
        workspace.write_text(slug, "input_validators/validate.py", "import sys\nn=int(sys.stdin.read().strip());sys.exit(42 if 0<n<100 else 1)\n", source="test")
        workspace.write_text(slug, "data/sample/01.in", "21\n", source="test")
        workspace.write_text(slug, "data/sample/01.interaction", INTERACTION, source="test")
        workspace.write_text(slug, "data/secret/01.in", "7\n", source="test")
        workspace.write_text(slug, "data/secret/01.ans", "14\n", source="test")
        workspace.write_text(slug, "data/sample/01.ans", "42\n", source="test")
        result = verification_modes.interactive_selftest(slug)
        check("interactive selftest passes", result["status"] == "pass", result)
        check("reference accepted", any(case["name"].startswith("reference") and case["pass"] for case in result["cases"]), result["cases"])
        check("wrong rejected", any(case["name"].startswith("negative") and case["pass"] for case in result["cases"]), result["cases"])
        check("transcript captured", any(case.get("transcript") for case in result["cases"]), result["cases"])
        check("transcript checker ran", any(case["name"].startswith("transcript checker") and case["pass"] for case in result["cases"]), result["cases"])
        check("forged transcript rejected", any(case["name"] == "transcript checker rejects forged transcript" and case["pass"] for case in result["cases"]), result["cases"])
        check("spec contract detected", result["program"]["contract"] == "spec", result["program"])
        report = verify.verify(slug)
        check("interactive package verifies", report["status"] == "verified", report)
        check("spec audit present", report.get("spec", {}).get("status") == "pass", report.get("spec"))
    finally:
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)
    print("INTERACTIVE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
