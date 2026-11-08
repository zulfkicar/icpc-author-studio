"""Stale report and export gating tests."""
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import verify
import workspace


def main():
    created = workspace.create("QA Stale Export", "stale report")
    slug = created["slug"]
    try:
        workspace.write_text(slug, "problem.yaml", "name: QA Stale\ntype: pass-fail\nlimits:\n  memory: 256\n", source="test")
        workspace.write_text(slug, "domjudge-problem.ini", "name = QA Stale\ntimelimit = 1\nshort-name = QS\n", source="test")
        workspace.write_text(slug, "submissions/accepted/ref.py", "a,b=map(int,input().split());print(a+b)\n", source="test")
        workspace.write_text(slug, "submissions/wrong_answer/wrong.py", "a,b=map(int,input().split());print(a-b)\n", source="test")
        workspace.write_text(slug, "input_validators/validate.py", "import sys\na,b=map(int,sys.stdin.read().split());sys.exit(42)\n", source="test")
        workspace.write_text(slug, "data/sample/01.in", "2 3\n", source="test")
        workspace.write_text(slug, "data/secret/01.in", "4 5\n", source="test")
        workspace.set_limits(slug, 1.0, 256, {"measuredAt": "test", "slowestTest": "data/sample/01.in"})
        report = verify.verify(slug, write_answers=True)
        assert report["status"] == "verified", report
        workspace.mark_reviewed(slug)
        workspace.write_text(slug, "NOTES.md", "changed after verify\n", source="user")
        try:
            verify.export_package(slug)
        except ValueError as exc:
            print("  PASS stale export blocked", str(exc))
        else:
            raise AssertionError("export should be blocked after a workspace change")
        print("STALE EXPORT TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
