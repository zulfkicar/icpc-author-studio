"""Single-owner controller runtime: OS lock, durable epoch, wake outbox.

HTTP handlers only append ledger records.  This owner is the sole caller of the
graph for a run; a second controller cannot acquire the local lock, and a stale
in-memory owner cannot publish because publication checks the run's current
controller epoch (see ``graph._publication_fence``).
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3
import threading
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from .clock import CrashInjected
from .graph import Runtime, _operation_expired, build_parent
from .lockfile import FileLock
from .store import ApplicationStore


class OwnerError(RuntimeError):
    pass


class RunOwner:
    def __init__(self, runtime: Runtime, *, max_steps: int = 80):
        self.runtime = runtime
        self.store: ApplicationStore = runtime.store
        self.max_steps = max_steps
        self._conn = sqlite3.connect(str(self.store.checkpoint_path), check_same_thread=False)
        self.saver = SqliteSaver(self._conn)
        self.saver.setup()
        self.graph = build_parent(runtime, self.saver)
        self._lock = FileLock(str(self.store.root / "owner.lock"))
        self._lifecycle = threading.Lock()
        self._pumping = False
        self._closing = False
        self.epoch = 0

    @property
    def config(self) -> dict:
        run = self.store.get_run(self._run_id)
        return {
            "configurable": {"thread_id": run["thread_id"]},
            "recursion_limit": max(120, self.max_steps * 8),
        }

    def set_run(self, run_id: str) -> None:
        self._run_id = run_id

    def close(self) -> None:
        with self._lifecycle:
            if self._closing:
                return
            self._closing = True
            # LangGraph may be completing a checkpoint on an executor thread.
            # Keep both the connection and the OS lease until invoke returns.
            if not self._pumping:
                self._conn.close()

    # ------------------------------------------------------------------ pump
    def pump(self, run_id: str, *, max_steps: int | None = None) -> dict:
        with self._lifecycle:
            if self._closing:
                return {"status": "closed", "runId": run_id}
            if self._pumping or not self._lock.acquire():
                return {"status": "locked", "runId": run_id,
                        "detail": "another controller owns this run"}
            self._run_id = run_id
            self._pumping = True
        try:
            epoch = self._acquire_epoch(run_id)
            steps = 0
            limit = int(max_steps or self.max_steps)
            while steps < limit:
                snapshot = self.graph.get_state(self.config)
                values = snapshot.values or {}
                if not values.get("run_id"):
                    self.graph.invoke({"run_id": run_id, "controller_epoch": epoch}, self.config)
                elif snapshot.next:
                    next_nodes = tuple(snapshot.next or ())
                    if "await_human" in next_nodes or "await_operation" in next_nodes:
                        if "await_human" in next_nodes and self.store.pending_interaction(run_id) is None:
                            self.graph.invoke(None, self.config)
                            steps += 1
                            continue
                        if "await_operation" in next_nodes and self._operation_terminal(run_id):
                            self.graph.invoke(None, self.config)
                            steps += 1
                            continue
                        wake = self.store.next_pending_wake(run_id)
                        if wake is None:
                            wake = self._receipt_wake(run_id)
                        if wake is None:
                            self._set_wait_status(run_id, next_nodes)
                            return {"status": "waiting", "runId": run_id,
                                    "next": list(next_nodes)}
                        self.store.mark_wake_delivered(wake["wake_id"], epoch)
                        self.graph.invoke(Command(resume=wake), self.config)
                    else:
                        # A crash inside a normal node leaves pending tasks; resume
                        # them without supplying a new graph command.
                        self.graph.invoke(None, self.config)
                else:
                    if self._has_new_work(run_id):
                        self.graph.invoke({"run_id": run_id, "controller_epoch": epoch,
                                           "resume_after_handoff": True}, self.config)
                    else:
                        return {"status": "idle", "runId": run_id,
                                "run": self.store.projection(run_id)}
                steps += 1
                snapshot = self.graph.get_state(self.config)
                if snapshot.next:
                    next_nodes = tuple(snapshot.next or ())
                    if "await_human" in next_nodes or "await_operation" in next_nodes:
                        wake = self.store.next_pending_wake(run_id) or self._receipt_wake(run_id)
                        if wake is not None:
                            continue
                        self._set_wait_status(run_id, next_nodes)
                        return {"status": "waiting", "runId": run_id, "next": list(next_nodes)}
                    continue
                if not self._has_new_work(run_id):
                    return {"status": "done", "runId": run_id,
                            "run": self.store.projection(run_id)}
            return {"status": "step_limit", "runId": run_id}
        except CrashInjected as exc:
            self.store.append_event(run_id, "controller_crash", role="host",
                                   payload={"failpoint": exc.name, "known": True})
            raise
        except Exception as exc:  # noqa: BLE001
            self.store.append_event(run_id, "controller_error", role="host",
                                    payload={"error": f"{type(exc).__name__}: {exc}"[:2000]})
            try:
                self.store.update_run(run_id, status="blocked",
                                      stop_reason="controller_error")
            except Exception:  # noqa: BLE001
                pass
            return {"status": "error", "runId": run_id,
                    "error": f"{type(exc).__name__}: {exc}"}
        finally:
            with self._lifecycle:
                self._lock.release()
                self._pumping = False
                if self._closing:
                    self._conn.close()

    def _acquire_epoch(self, run_id: str) -> int:
        run = self.store.get_run(run_id)
        epoch = int(run["controller_epoch"]) + 1
        self.store.update_run(run_id, controller_epoch=epoch)
        self.store.log_controller(run_id, epoch, "owner_acquired")
        self.epoch = epoch
        return epoch

    def _receipt_wake(self, run_id: str) -> dict | None:
        run = self.store.get_run(run_id)
        continuation = json.loads(run["continuation_json"] or "null") or {}
        operation_id = continuation.get("operation_id")
        if not operation_id:
            return None
        try:
            operation = self.store.get_operation(operation_id)
        except Exception:  # noqa: BLE001
            return None
        if operation["status"] not in ("completed", "failed", "incomplete", "cancelled",
                                       "outcome_unknown"):
            if _operation_expired(self.runtime, operation):
                return self.store.enqueue_wake(
                    run_id, wait_id="operation:" + operation_id, reason="deadline",
                    durable_record_ref=operation_id,
                )
            return None
        return self.store.enqueue_wake(
            run_id, wait_id="operation:" + operation_id, reason="worker_receipt",
            durable_record_ref=operation_id,
        )

    def _set_wait_status(self, run_id: str, next_nodes: tuple) -> None:
        status = "waiting_worker" if "await_operation" in next_nodes else "waiting_human"
        self.store.update_run(run_id, status=status)

    def _operation_terminal(self, run_id: str) -> bool:
        run = self.store.get_run(run_id)
        continuation = json.loads(run["continuation_json"] or "null") or {}
        operation_id = continuation.get("operation_id")
        if not operation_id:
            return True
        try:
            operation = self.store.get_operation(operation_id)
        except Exception:  # noqa: BLE001
            return True
        return operation["status"] in ("completed", "failed", "incomplete", "cancelled",
                                       "outcome_unknown")

    def _has_new_work(self, run_id: str) -> bool:
        if self.store.received_inputs(run_id):
            return True
        return bool(self.store.pending_wakes(run_id))


class OwnerRegistry:
    """One owner object per run root; the OS lock is the real exclusion."""

    def __init__(self) -> None:
        self._owners: dict[str, RunOwner] = {}

    def owner(self, runtime: Runtime, run_id: str) -> RunOwner:
        key = str(runtime.store.root)
        owner = self._owners.get(key)
        if owner is None:
            owner = RunOwner(runtime)
            owner.set_run(run_id)
            self._owners[key] = owner
        return owner

    def close(self, runtime: Runtime) -> None:
        key = str(runtime.store.root)
        owner = self._owners.pop(key, None)
        if owner:
            owner.close()
