"""Pure delivery state for one saved package snapshot."""
from __future__ import annotations

from typing import Literal, TypedDict


class PackageWorkflow(TypedDict):
    phase: Literal["unverified", "verification_failed", "verification_stale", "review_required", "ready_to_export"]
    snapshot: str
    verifiedSnapshot: str | None
    reviewedSnapshot: str | None
    unreviewedChanges: int
    nextAction: Literal["verify", "review", "export"]
    requiresHuman: bool
    canExport: bool
    blocker: str | None


def evaluate(snapshot: str, state: dict, unreviewed: int) -> PackageWorkflow:
    report = state.get("lastReport")
    verified = report.get("snapshot") if report and report.get("status") == "verified" else None
    reviewed = state.get("reviewedSnapshot")
    if report and ((report.get("snapshot") and report["snapshot"] != snapshot)
                   or (report.get("status") == "verified" and verified != snapshot)):
        phase, action = "verification_stale", "verify"
        blocker = "The workspace changed after the last verification. Run Verify again before exporting."
    elif not report or report.get("status") != "verified":
        phase, action = ("verification_failed" if report else "unverified"), "verify"
        blocker = "Export is blocked until package verification passes"
    elif unreviewed or (reviewed != snapshot and
                        ("reviewedSnapshot" in state or not state.get("lastReview"))):
        phase, action = "review_required", "review"
        blocker = ("Mark all changes reviewed before exporting" if unreviewed else
                   "Review the current saved package before exporting.")
    else:
        phase, action, blocker = "ready_to_export", "export", None
    return {"phase": phase, "snapshot": snapshot, "verifiedSnapshot": verified, "reviewedSnapshot": reviewed,
            "unreviewedChanges": unreviewed, "nextAction": action, "requiresHuman": action == "review",
            "canExport": blocker is None, "blocker": blocker}
