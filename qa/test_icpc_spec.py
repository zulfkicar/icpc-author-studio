"""ICPC Problem Package Format audit tests."""
from __future__ import annotations

import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from author_studio.packages import icpc_spec
from author_studio.packages import workspace


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS {name}")
        return
    print(f"  FAIL {name} {detail}")
    raise AssertionError(name)


def base_package(slug: str) -> None:
    workspace.write_text(slug, "problem.yaml", "problem_format_version: legacy-icpc\nname: Spec Test\nauthor: QA\nlicense: educational\nrights_owner: QA\nlimits:\n  memory: 256\nvalidation: default\n", source="test")
    workspace.write_text(slug, "data/sample/01.in", "2 3\n", source="test")
    workspace.write_text(slug, "data/sample/01.ans", "5\n", source="test")
    workspace.write_text(slug, "data/secret/01.in", "4 5\n", source="test")
    workspace.write_text(slug, "data/secret/01.ans", "9\n", source="test")
    workspace.write_text(slug, "submissions/accepted/ref.py", "a,b=map(int,input().split());print(a+b)\n", source="test")
    workspace.write_text(slug, "input_validators/validate.py", "import sys\na,b=map(int,sys.stdin.read().split());sys.exit(42)\n", source="test")


def main() -> int:
    created = workspace.create("QA ICPC Spec", "spec audit")
    slug = created["slug"]
    try:
        base_package(slug)
        audit = icpc_spec.audit(slug)
        check("valid package passes", audit["status"] == "pass", audit)
        check("format version accepted", any(item["id"] == "format-version" and item["status"] == "pass" for item in audit["checks"]), audit)
        check("validator exit contract", any(item["id"] == "input-validator-exit" and item["status"] == "pass" for item in audit["checks"]), audit)

        workspace.write_text(slug, "data/secret/01.in", "", source="test")
        workspace.write_text(slug, "data/secret/01.ans", "", source="test")
        # Remove the secret test entirely to trigger the structural failure.
        (workspace.ws_path(slug) / "data" / "secret" / "01.in").unlink()
        (workspace.ws_path(slug) / "data" / "secret" / "01.ans").unlink()
        broken = icpc_spec.audit(slug)
        check("missing secret tests fail", broken["status"] == "fail" and any("Secret test data" in item for item in broken["errors"]), broken)

        base_package(slug)
        workspace.write_text(slug, "problem.yaml", "name: Spec Test\nlicense: not-a-license\nvalidation: custom\nlimits:\n  memory: 256\n", source="test")
        custom = icpc_spec.audit(slug)
        check("custom validator required", any("requires output_validators" in item for item in custom["errors"]), custom)
        check("invalid license rejected", any("License" in item for item in custom["errors"]), custom)

        base_package(slug)
        workspace.write_text(slug, "output_validators/checker.py", "import sys\nsys.exit(42)\n", source="test")
        custom = icpc_spec.audit(slug)
        # validation is default in base_package, so a stray validator is allowed.
        check("plural validator discovered", any(item["id"] == "custom-validator" for item in custom["checks"]) is False, custom)

        workspace.write_text(slug, "problem.yaml", "name: Spec Test\nlicense: educational\nrights_owner: QA\nvalidation: custom\nlimits:\n  memory: 256\n", source="test")
        custom = icpc_spec.audit(slug)
        check("custom package passes", custom["status"] == "pass", custom)

        workspace.write_text(slug, "interaction.txt", "hello\r\n", source="test")
        crlf = icpc_spec.audit(slug)
        check("CRLF reported", any("CRLF" in item for item in crlf["warnings"]), crlf)

        # Real standard package regression.
        if (ROOT / "workspaces" / "sum-test").is_dir():
            standard = icpc_spec.audit("sum-test")
            check("sum-test package passes spec", standard["status"] == "pass", standard)
    finally:
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)
    print("ICPC SPEC TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
