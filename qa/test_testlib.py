"""Real C++ testlib fixtures: checker, interactor and transcript checker."""
from __future__ import annotations

import os
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import package_model
import verification_modes
import workspace

FIXTURES = ROOT / "qa" / "fixtures" / "testlib"


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS {name}")
        return
    print(f"  FAIL {name} {detail}")
    raise AssertionError(name)


def main() -> int:
    if not os.environ.get("AUTHOR_AGENT_EXECUTOR_URL"):
        print("SKIP testlib test: AUTHOR_AGENT_EXECUTOR_URL is not set")
        return 0
    checker_source = (FIXTURES / "checker.cpp").read_text("utf-8")
    interactor_source = (FIXTURES / "interactor.cpp").read_text("utf-8")
    transcript_source = (FIXTURES / "transcript_checker.cpp").read_text("utf-8")

    # --- checker -----------------------------------------------------------
    created = workspace.create("QA Testlib Checker", "testlib checker")
    slug = created["slug"]
    try:
        workspace.write_text(slug, "problem.yaml", "name: QA Testlib Checker\nvalidation: custom\nlimits:\n  memory: 256\nvalidator_flags: \"\"\n", source="test")
        workspace.write_text(slug, "output_validators/checker.cpp", checker_source, source="test")
        workspace.write_text(slug, "data/sample/01.in", "2 3\n", source="test")
        workspace.write_text(slug, "data/sample/01.ans", "5\n", source="test")
        workspace.write_text(slug, "data/secret/01.in", "4 5\n", source="test")
        workspace.write_text(slug, "data/valid_output/01.out", "5\n", source="test")
        workspace.write_text(slug, "data/invalid_output/01.out", "6\n", source="test")
        workspace.write_text(slug, "submissions/accepted/ref.cpp", "#include <cstdio>\nint main(){long long a,b;scanf(\"%lld %lld\",&a,&b);printf(\"%lld\\n\",a+b);}\n", source="test")
        package = package_model.load(slug)
        check("testlib checker discovered", package.output_validator_program is not None, package.output_validator_program)
        check("testlib contract detected", package.output_validator_program.contract == "testlib", package.output_validator_program)
        result = verification_modes.checker_selftest(slug)
        check("testlib checker selftest passes", result["status"] == "pass", result)
        check("testlib reference accepted", any(case["name"] == "reference accepted" and case["pass"] for case in result["cases"]), result["cases"])
        check("testlib wrong rejected", any(case["name"] == "wrong rejected" and case["pass"] for case in result["cases"]), result["cases"])
        check("testlib invalid fixture rejected", any(case["name"].startswith("invalid_output") and case["pass"] for case in result["cases"]), result["cases"])
    finally:
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)

    # --- interactive -------------------------------------------------------
    created = workspace.create("QA Testlib Interactive", "testlib interactor")
    slug = created["slug"]
    try:
        workspace.write_text(slug, "problem.yaml", "name: QA Testlib Interactive\ntype: interactive\nvalidation: custom interactive\nlimits:\n  memory: 256\n", source="test")
        workspace.write_text(slug, "output_validators/interactor.cpp", interactor_source, source="test")
        workspace.write_text(slug, "output_validators/transcript_checker.cpp", transcript_source, source="test")
        workspace.write_text(slug, "submissions/accepted/ref.cpp", "#include <iostream>\nint main(){long long n;std::cin>>n;std::cout<<2*n<<std::endl;}\n", source="test")
        workspace.write_text(slug, "submissions/wrong_answer/wrong.cpp", "#include <iostream>\nint main(){long long n;std::cin>>n;std::cout<<n+1<<std::endl;}\n", source="test")
        workspace.write_text(slug, "input_validators/validate.py", "import sys\nn=int(sys.stdin.read().strip());sys.exit(42 if 0<n<100 else 1)\n", source="test")
        workspace.write_text(slug, "data/sample/01.in", "21\n", source="test")
        workspace.write_text(slug, "data/sample/01.interaction", "< 21\n> 42\n", source="test")
        workspace.write_text(slug, "data/secret/01.in", "7\n", source="test")
        package = package_model.load(slug)
        check("testlib interactor contract", package.output_validator_program.contract == "testlib-interactive", package.output_validator_program)
        check("transcript checker discovered", package.transcript_checker_program is not None, package.transcript_checker_program)
        result = verification_modes.interactive_selftest(slug)
        check("testlib interactive selftest passes", result["status"] == "pass", result)
        check("testlib reference accepted", any(case["name"].startswith("reference") and case["pass"] for case in result["cases"]), result["cases"])
        check("testlib wrong rejected", any(case["name"].startswith("negative") and case["pass"] for case in result["cases"]), result["cases"])
        check("testlib transcript checker passes", any(case["name"].startswith("transcript checker reference") and case["pass"] for case in result["cases"]), result["cases"])
        check("testlib forged transcript rejected", any(case["name"] == "transcript checker rejects forged transcript" and case["pass"] for case in result["cases"]), result["cases"])
    finally:
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)
    print("TESTLIB FIXTURE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
