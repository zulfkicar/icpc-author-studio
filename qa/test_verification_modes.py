"""Checker/self-test and package model tests."""
from __future__ import annotations
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import package_model
import verification_modes
import verify
import workspace


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS {name}")
        return
    print(f"  FAIL {name} {detail}")
    raise AssertionError(name)


CHECKER = """import sys
inp, out, ans = sys.argv[1], sys.argv[2], sys.argv[3]
expected = open(ans, "rb").read().split()
actual = open(out, "rb").read().split()
if actual != expected:
    print("wrong answer")
    sys.exit(1)
print("ok")
"""


def main() -> int:
    created = workspace.create("QA Verification Modes", "checker selftest")
    slug = created["slug"]
    try:
        workspace.write_text(slug, "problem.yaml", "name: QA Verification\ntype: checker\nlimits:\n  memory: 256\n", source="test")
        workspace.write_text(slug, "output_validator/checker.py", CHECKER, source="test")
        workspace.write_text(slug, "data/sample/01.in", "2 3\n", source="test")
        workspace.write_text(slug, "data/sample/01.ans", "5\n", source="test")
        workspace.write_text(slug, "data/secret/01.in", "4 5\n", source="test")
        workspace.write_text(slug, "data/valid_output/01.out", "5\n", source="test")
        workspace.write_text(slug, "data/invalid_output/01.out", "6\n", source="test")
        package = package_model.load(slug)
        check("checker discovered", package.output_validator is not None, package.output_validator)
        check("tests discovered", len(package.tests) == 2, package.tests)
        result = verification_modes.checker_selftest(slug)
        check("checker selftest passes", result["status"] == "pass", result)
        check("matrix has reference", any(case["name"] == "reference accepted" and case["pass"] for case in result["cases"]), result["cases"])
        check("matrix rejects invalid", any(case["name"].startswith("invalid_output") and case["pass"] for case in result["cases"]), result["cases"])
        workspace.write_text(slug, "output_validator/checker.py", "import sys\nsys.exit(0)\n", source="test")
        bad = verification_modes.checker_selftest(slug)
        check("accepts-everything checker fails", bad["status"] == "fail", bad)

        # Full check: accepted Python reference, wrong negative, checker comparator.
        workspace.write_text(slug, "output_validator/checker.py", CHECKER, source="test")
        workspace.write_text(slug, "submissions/accepted/ref.py", "a,b=map(int,input().split());print(a+b)\n", source="test")
        workspace.write_text(slug, "submissions/wrong_answer/wrong.py", "a,b=map(int,input().split());print(a-b)\n", source="test")
        workspace.write_text(slug, "input_validators/validate.py", "import sys\na,b=map(int,sys.stdin.read().split());sys.exit(42 if 0<=a<=10 and 0<=b<=10 else 1)\n", source="test")
        workspace.write_text(slug, "domjudge-problem.ini", "name = QA Verification\ntimelimit = 1\nshort-name = QV\n", source="test")
        workspace.set_limits(slug, 1.0, 256, {"measuredAt": "test", "slowestTest": "data/sample/01.in"})
        report = verify.verify(slug, write_answers=True)
        check("checker package verifies", report["status"] == "verified", report)
    finally:
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)
    print("VERIFICATION MODE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
