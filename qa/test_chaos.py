"""Chaos depth: real file-size exhaustion, clock skew and event replay."""
from __future__ import annotations

import os
import pathlib
import shutil
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import schemas
import server
import winutil
import workspace


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS {name}")
        return
    print(f"  FAIL {name} {detail}")
    raise AssertionError(name)


def disk_full() -> None:
    if not os.environ.get("AUTHOR_AGENT_EXECUTOR_URL"):
        print("  SKIP disk-full: executor is not configured")
        return
    created = workspace.create("QA Chaos Disk", "disk full")
    slug = created["slug"]
    try:
        root = workspace.ws_path(slug)
        workspace.write_text(slug, "probe.py", "f=open('big.bin','wb'); f.write(b'x'*(2*1024*1024)); f.close(); print('wrote')\n", source="test")
        result = winutil.isolate_run(
            [sys.executable, str(root / "probe.py")],
            cwd=root,
            time_limit=10,
            wall_time=30,
            memory_mb=256,
            fsize_mb=1,
        )
        check("file-size limit trips", result.get("status") != "OK" or result.get("returncode") != 0, result)
        check("file-size failure is reported", bool(result.get("message")) or result.get("returncode") != 0, result)
        chat = workspace.ensure_chats(slug)["activeChat"]
        check("checkpoint still readable", isinstance(workspace.get_chat(slug, chat), dict))
    finally:
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)


def clock_skew() -> None:
    try:
        schemas.Event("run", 1, "2026-01-01T00:00:00", "plan", status="info", duration_ms=-1)
    except ValueError:
        print("  PASS negative duration rejected")
    else:
        raise AssertionError("negative duration should be rejected")
    ledger = schemas.EventLedger()
    ledger.add(schemas.Event("run", 2, "2026-01-01T00:00:01", "verify", status="passed"))
    ledger.add(schemas.Event("run", 1, "2026-01-01T00:00:09", "plan", status="info"))
    ledger.add(schemas.Event("run", 3, "2025-12-31T23:59:59", "export", status="info"))
    ordered = ledger.ordered()
    check("clock skew does not reorder events", [event.seq for event in ordered] == [1, 2, 3], [event.seq for event in ordered])
    check("timestamps may be out of order", ordered[0].at > ordered[2].at, [event.at for event in ordered])


def event_replay() -> None:
    created = workspace.create("QA Chaos Events", "event replay")
    slug = created["slug"]
    try:
        chat = workspace.ensure_chats(slug)["activeChat"]

        def work(emit, cancelled):
            emit("one", {"n": 1})
            emit("two", {"n": 2})
            emit("three", {"n": 3})
            return {"ok": True}

        job = server.start_job("Chaos replay", slug, work, chat_id=chat)
        for _ in range(50):
            if job["state"] != "running":
                break
            time.sleep(0.02)
        events = job["events"]
        check("events have sequence numbers", [event["seq"] for event in events] == [1, 2, 3], events)
        replay = [event for event in events if event["seq"] > 1]
        check("replay after loss", [event["seq"] for event in replay] == [2, 3], replay)
        ledger = schemas.EventLedger()
        for event in events + replay:
            ledger.add(schemas.Event(
                "run", event["seq"], "2026-01-01T00:00:00", "plan",
                status="info", summary=event["kind"],
            ))
        check("duplicate replay suppressed", len(ledger.ordered()) == 3, ledger.ordered())
        check("event loss is detectable", ledger.missing(4) == [4], ledger.missing(4))
    finally:
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)


def main() -> int:
    disk_full()
    clock_skew()
    event_replay()
    print("CHAOS TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
