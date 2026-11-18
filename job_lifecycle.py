"""Transitions for in-process workspace jobs, independent of threads and HTTP."""

_TRANSITIONS = {
    "queued": {"start": "executing", "cancel": "cancel_pending", "deadline": "timeout_pending",
               "fail": "failed", "halted": "cancelled"},
    "executing": {"finish": "succeeded", "pause": "paused", "fail": "failed",
                  "cancel": "cancel_pending", "deadline": "timeout_pending", "halted": "cancelled"},
    "cancel_pending": {"halted": "cancelled", "deadline": "timeout_pending"},
    "timeout_pending": {"halted": "timed_out", "grace_elapsed": "timed_out"},
}

_PUBLIC_STATES = {"queued": "running", "executing": "running", "cancel_pending": "running",
                  "timeout_pending": "running", "succeeded": "done", "paused": "paused",
                  "failed": "error", "cancelled": "cancelled", "timed_out": "error"}


def transition(job: dict, event: str) -> bool:
    """Apply a legal transition under the caller's job lock."""
    following = _TRANSITIONS.get(job["phase"], {}).get(event)
    if following is None:
        return False
    job["phase"] = following
    job["state"] = _PUBLIC_STATES[following]
    if event in ("cancel", "deadline"):
        job["cancelRequested"] = True
    return True


def settle(job: dict, result=None, error: str | None = None) -> bool:
    if job["cancelRequested"]:
        return transition(job, "halted")
    event = "fail" if error else "pause" if isinstance(result, dict) and result.get("paused") else "finish"
    if not transition(job, event):
        return False
    job["result"] = result
    job["error"] = error
    return True
