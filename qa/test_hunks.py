"""Hunk parsing and partial application tests."""
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from author_studio.packages import workspace


def check(name, cond, detail=""):
    if cond:
        print("  PASS", name)
        return
    print("  FAIL", name, detail)
    raise AssertionError(name)


def main():
    created = workspace.create("QA Hunks", "hunk test")
    slug = created["slug"]
    try:
        before = "a\nb\nc\nd\ne\nf\ng\nh\ni\nj\n"
        after = "a\nB\nc\nd\ne\nf\ng\nh\ni\nJ\n"
        workspace.write_text(slug, "notes.txt", before, source="test")
        result = workspace.write_text(slug, "notes.txt", after, source="test")
        change = result["change"]
        hunks = workspace.parse_hunks(result["diff"])
        check("two hunks", len(hunks) == 2, hunks)
        applied = workspace.apply_hunks(slug, change["id"], [0])
        content = (workspace.ws_path(slug) / "notes.txt").read_text("utf-8")
        check("first hunk applied", "B" in content and "J" not in content, content)
        check("hunk result", applied["applied"] == [0], applied)
    finally:
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)
    print("HUNK TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
