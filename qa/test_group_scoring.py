"""Group scoring, dependencies and verifier integration."""
from __future__ import annotations

import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from author_studio.packages import package_model
from author_studio.judging import scoring
from author_studio.judging import verify
from author_studio.packages import workspace


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS {name}")
        return
    print(f"  FAIL {name} {detail}")
    raise AssertionError(name)


def main() -> int:
    created = workspace.create("QA Group Scoring", "group scoring")
    slug = created["slug"]
    try:
        workspace.write_text(slug, "problem.yaml", "name: QA Group Scoring\ntype: pass-fail\nlimits:\n  memory: 256\n", source="test")
        workspace.write_text(slug, "test_group.yaml", "easy:\n  points: 40\nmedium:\n  points: 30\n  depends: [easy]\nhard:\n  points: 30\n  dependencies: [medium]\n", source="test")
        workspace.write_text(slug, "data/sample/01.in", "2 3\n", source="test")
        workspace.write_text(slug, "data/sample/01.ans", "5\n", source="test")
        workspace.write_text(slug, "data/secret/easy/01.in", "1 2\n", source="test")
        workspace.write_text(slug, "data/secret/easy/01.ans", "3\n", source="test")
        workspace.write_text(slug, "data/secret/medium/01.in", "4 5\n", source="test")
        workspace.write_text(slug, "data/secret/medium/01.ans", "9\n", source="test")
        workspace.write_text(slug, "data/secret/hard/01.in", "10 20\n", source="test")
        workspace.write_text(slug, "data/secret/hard/01.ans", "30\n", source="test")
        package = package_model.load(slug)
        checks = package_model.group_errors(package)
        check("groups valid", checks == [], checks)

        verdicts = {
            "data/secret/easy/01.in": "AC",
            "data/secret/medium/01.in": "AC",
            "data/secret/hard/01.in": "AC",
        }
        result = scoring.evaluate(package, verdicts)
        check("full score", result["score"] == 100 and result["maxScore"] == 100, result)
        check("all groups pass", result["allPassed"] and all(item["passed"] for item in result["groups"]), result)

        verdicts["data/secret/easy/01.in"] = "WA"
        blocked = scoring.evaluate(package, verdicts)
        check("dependency blocks dependent points", blocked["score"] == 0, blocked)
        check("dependent groups blocked", all(item["blockedBy"] for item in blocked["groups"] if item["name"] != "easy"), blocked)

        verdicts["data/secret/easy/01.in"] = "AC"
        verdicts["data/secret/hard/01.in"] = "WA"
        partial = scoring.evaluate(package, verdicts)
        check("partial score", partial["score"] == 70 and partial["maxScore"] == 100, partial)
        check("hard blocked", next(item for item in partial["groups"] if item["name"] == "hard")["passed"] is False, partial)

        # Verifier integration: a fully correct package reports the group score.
        workspace.write_text(slug, "output_validators/.keep", "", source="test")
        workspace.write_text(slug, "submissions/accepted/ref.py", "a,b=map(int,input().split());print(a+b)\n", source="test")
        workspace.write_text(slug, "submissions/wrong_answer/wrong.py", "a,b=map(int,input().split());print(a-b)\n", source="test")
        workspace.write_text(slug, "input_validators/validate.py", "import sys\na,b=map(int,sys.stdin.read().split());sys.exit(42 if -10**9<=a<=10**9 and -10**9<=b<=10**9 else 1)\n", source="test")
        workspace.write_text(slug, "domjudge-problem.ini", "name = QA Group Scoring\ntimelimit = 1\nshort-name = G\n", source="test")
        workspace.set_limits(slug, 1.0, 256, {"measuredAt": "test", "slowestTest": "data/secret/hard/01.in"})
        report = verify.verify(slug, write_answers=True)
        check("package verifies", report["status"] == "verified", report.get("errors"))
        check("report contains group score", report.get("groups", {}).get("score") == 100, report.get("groups"))
        check("spec audit present", report.get("spec", {}).get("status") == "pass", report.get("spec"))
    finally:
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)
    print("GROUP SCORING TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
