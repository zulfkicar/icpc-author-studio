"""Measure limits, then verify the 86-test eval workspace under the budget.

This is the heavy, explicit timing run. The light guard in
qa/test_verification_timing.py consumes the JSON produced here, so a normal CI
gate stays fast while the budget evidence remains reproducible.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from author_studio.judging import verify  # noqa: E402
from author_studio.packages import workspace  # noqa: E402

SLUG = "eval-claim-or-concede-2"
BUDGET_SECONDS = 900.0


def main() -> int:
    if not workspace.ws_path(SLUG).exists():
        print(json.dumps({"error": f"workspace {SLUG} is missing"}))
        return 1

    started = time.time()
    limits = verify.measure_limits(SLUG)
    measured = time.time()
    report = verify.verify(SLUG, write_answers=False)
    finished = time.time()

    counts = report.get("counts") or {}
    result = {
        "slug": SLUG,
        "limitsSeconds": round(measured - started, 1),
        "verifySeconds": round(finished - measured, 1),
        "elapsedSeconds": round(finished - started, 1),
        "budgetSeconds": BUDGET_SECONDS,
        # The budget is the verifier itself. Measure-limits is a separate
        # pre-step and its time is recorded but not counted against the
        # 15-minute verification budget.
        "withinBudget": (finished - measured) <= BUDGET_SECONDS,
        "status": report.get("status"),
        "tests": counts.get("tests"),
        "accepted": counts.get("accepted"),
        "negative": counts.get("negative"),
        "limits": report.get("limits"),
        "errors": (report.get("errors") or [])[:10],
        "measuredLimits": limits,
    }
    out = ROOT / "qa" / "verification-timing.json"
    out.write_text(json.dumps(result, indent=2) + "\n", "utf-8")
    print("TIMING " + json.dumps(result))
    return 0 if result["withinBudget"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
