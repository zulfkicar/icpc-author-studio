"""Exercise server jobs on real threads with explicit synchronization."""
import threading
import time
import uuid
import zipfile

import package_workflow
import pytest
import server
import verify
import workspace


def observe(started, predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with server.JOB_LOCK:
            job = {**server.JOBS[started["id"]]}
        if predicate(job):
            return job
        time.sleep(0.01)
    raise AssertionError(f"Job did not reach expected state: {job}")


def test_cancel_queued_chat_releases_claim_before_workspace_unlock():
    slug = "queued-cancel-" + uuid.uuid4().hex[:8]
    ran = threading.Event()
    with server.workspace_lock(slug):
        with server.CHAT_LOCK:
            server.ACTIVE_CHATS.add(slug)
        started = server.start_job("test", slug, lambda *_: ran.set(), chat_id="test", owns_chat=True)
        assert started["phase"] == "queued"
        assert server.request_job_cancel(started["id"])["accepted"]
        stopped = observe(started, lambda job: job["phase"] == "cancelled")
        assert not stopped["workerActive"]
        assert not ran.is_set()
        with server.CHAT_LOCK:
            assert slug not in server.ACTIVE_CHATS


def test_expired_worker_cannot_replace_terminal_timeout(monkeypatch):
    monkeypatch.setattr(server, "JOB_TIMEOUT_SECONDS", 0.4)
    monkeypatch.setattr(server, "JOB_STOP_GRACE_SECONDS", 0.025)
    entered, release = threading.Event(), threading.Event()

    def work(emit, cancelled):
        entered.set()
        release.wait(5)
        emit("late-result", {})
        return {"wouldHaveSucceeded": True}

    started = server.start_job("test timeout", None, work)
    try:
        assert entered.wait(2)
        timed_out = observe(started, lambda job: job["phase"] == "timed_out")
        assert timed_out["state"] == "error" and timed_out["workerActive"]
        assert not server.request_job_cancel(started["id"])["accepted"]
    finally:
        release.set()
    settled = observe(started, lambda job: not job["workerActive"])
    assert settled["phase"] == "timed_out"
    assert settled["error"] == timed_out["error"]
    assert settled["result"] is None
    assert [row["kind"] for row in settled["events"]] == ["timeout"]


def test_late_cancel_keeps_success():
    started = server.start_job("test success", None, lambda *_: {"ok": True})
    completed = observe(started, lambda job: job["phase"] == "succeeded")
    assert completed["state"] == "done" and not completed["workerActive"]
    assert not server.request_job_cancel(started["id"])["accepted"]
    assert completed["result"] == {"ok": True}


def test_review_compatibility_requires_a_recorded_legacy_review():
    state = {"lastReport": {"status": "verified", "snapshot": "saved"}}
    assert package_workflow.evaluate("saved", state, 0)["phase"] == "review_required"
    state["lastReview"] = "legacy"
    assert package_workflow.evaluate("saved", state, 0)["canExport"]
    assert package_workflow.evaluate("changed", state, 0)["phase"] == "verification_stale"
    assert package_workflow.evaluate("saved", state, 1)["phase"] == "review_required"


def test_verify_rejects_revision_changed_in_checker_selftest(monkeypatch, tmp_path):
    monkeypatch.setattr(workspace, "WORKSPACES", tmp_path)
    slug = workspace.create("Verification Race")["slug"]

    def concurrent_edit(_slug):
        (workspace.ws_path(slug) / "NOTES.md").write_text("Edited during verification.", encoding="utf-8")
        return {"status": "skipped"}

    monkeypatch.setattr(verify.verification_modes, "checker_selftest", concurrent_edit)
    with pytest.raises(ValueError, match="changed during verification"):
        verify.verify(slug)
    assert workspace.summary(slug)["workflow"]["phase"] == "unverified"


def test_staged_export_cannot_replace_zip_after_an_outside_edit(monkeypatch, tmp_path):
    monkeypatch.setattr(workspace, "WORKSPACES", tmp_path)
    slug = workspace.create("Export Race")["slug"]
    root = workspace.ws_path(slug)
    ignored = root / "submissions" / "tmp"
    ignored.mkdir()
    (ignored / "scratch.py").write_text("print('internal scratch file')", encoding="utf-8")
    snapshot = workspace.snapshot_hash(slug)
    workspace.set_report(slug, {"status": "verified", "snapshot": snapshot})
    workspace.mark_reviewed(slug, snapshot)
    original = root / verify.export_package(slug)["path"]
    previous_bytes = original.read_bytes()
    with zipfile.ZipFile(original) as archive:
        assert "submissions/tmp/scratch.py" not in archive.namelist()
    summarize = workspace.summary
    calls = 0

    def summary_after_edit(slug):
        nonlocal calls
        calls += 1
        if calls == 2:
            (root / "NOTES.md").write_text("Edited while writing the archive.", encoding="utf-8")
        return summarize(slug)

    monkeypatch.setattr(workspace, "summary", summary_after_edit)
    with pytest.raises(ValueError, match="changed during export"):
        verify.export_package(slug)
    assert original.read_bytes() == previous_bytes
