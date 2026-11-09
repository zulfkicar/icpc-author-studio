"""Fast guard over the recorded full-verification timing.

The heavy measurement is qa/run_verification_timing.py (86 tests, measure
limits + verify). This guard fails when that evidence is missing, under-counts
the suite, regresses past the 15-minute budget, or records a non-verified run.
"""
from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARTIFACT = ROOT / "qa" / "verification-timing.json"
BUDGET_SECONDS = 900.0
MIN_TESTS = 80


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS {name}")
        return
    print(f"  FAIL {name} {detail}")
    raise AssertionError(name)


def main() -> int:
    check("timing artifact exists", ARTIFACT.exists(), str(ARTIFACT))
    data = json.loads(ARTIFACT.read_text("utf-8"))
    verify_seconds = data.get("verifySeconds")
    check("verification time was measured", isinstance(verify_seconds, (int, float)), str(verify_seconds))
    check("test count is representative", (data.get("tests") or 0) >= MIN_TESTS, str(data.get("tests")))
    check("verification is within the budget", verify_seconds <= BUDGET_SECONDS, f"{verify_seconds}s > {BUDGET_SECONDS}s")
    check("withinBudget flag agrees", data.get("withinBudget") is True)
    check("limits were measured", bool(data.get("measuredLimits")), str(data.get("measuredLimits")))
    check("verification passed", data.get("status") == "verified", str(data.get("status")))
    print("VERIFICATION TIMING TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
