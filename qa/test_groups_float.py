"""Test-group discovery/validation and float comparison."""
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from author_studio.packages import package_model
from author_studio.judging import verify
from author_studio.packages import workspace


def check(name, condition, detail=""):
    if condition:
        print("  PASS", name)
        return
    print("  FAIL", name, detail)
    raise AssertionError(name)


def main():
    created = workspace.create("QA Groups Float", "groups and float")
    slug = created["slug"]
    try:
        workspace.write_text(slug, "problem.yaml", "name: QA Groups\ntype: pass-fail\nlimits:\n  memory: 256\n", source="test")
        workspace.write_text(slug, "test_group.yaml", "easy:\n  points: 50\nhard:\n  points: 50\n  depends: [easy]\n", source="test")
        workspace.write_text(slug, "data/secret/easy/01.in", "1\n", source="test")
        workspace.write_text(slug, "data/secret/hard/01.in", "2\n", source="test")
        package = package_model.load(slug)
        groups = {test.group for test in package.tests if test.kind == "secret"}
        check("nested groups discovered", {"easy", "hard"} <= groups, groups)
        check("groups valid", package_model.group_errors(package) == [], package_model.group_errors(package))
        workspace.write_text(slug, "test_group.yaml", "a:\n  depends: [b]\nb:\n  depends: [a]\n", source="test")
        check("cycle rejected", any("cycle" in item for item in package_model.group_errors(package_model.load(slug))))
        check("float tolerance accepts", verify._compare(b"1.000001\n", b"1.000000\n", tolerance=1e-3))
        check("float tolerance rejects", not verify._compare(b"1.1\n", b"1.0\n", tolerance=1e-6))
        check("nan rejected", not verify._compare(b"nan\n", b"1.0\n", tolerance=1e-3))
    finally:
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)
    print("GROUP/FLOAT TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
