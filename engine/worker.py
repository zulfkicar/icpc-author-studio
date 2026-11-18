"""Worker boundary.

Generated candidate programs run only through this interface.  ``FakeWorker``
is an explicitly labelled simulator used for deterministic contract tests;
``IsolateWorker`` is the real adapter and fails closed when unavailable.
"""
from __future__ import annotations

import re
import time
from typing import Any

from .domain import Instance, InvalidInput, parse_instance, render_instance
from .domain import candidates


class WorkerUnavailable(RuntimeError):
    pass


class WorkerProtocolError(RuntimeError):
    pass


MARKER = re.compile(r"//\s*fake-behavior:\s*([a-z_]+)")


def fake_behavior_name(source: str) -> str:
    match = MARKER.search(source or "")
    if not match:
        raise WorkerProtocolError("fake worker source has no behavior marker")
    name = match.group(1)
    if name not in candidates.BEHAVIORS:
        raise WorkerProtocolError(f"unknown fake behavior {name}")
    return name


class FakeWorker:
    """Deterministic worker simulator.  Not a containment boundary."""

    identity = "fake-worker-v1 (simulation; no compilation, no isolation)"
    is_real = False

    def __init__(self, *, failure: dict | None = None, deferred: bool = False):
        self.failure = failure or {}
        self.deferred = deferred
        self.jobs: list[dict] = []
        self._pending: dict[str, dict] = {}
        self._calls = 0

    def describe(self) -> dict:
        return {
            "identity": self.identity,
            "real": False,
            "configured": False,
            "qualified": False,
            "qualification": "simulated",
            "note": "Behavior is derived from a source marker; outputs are not from compiled C++.",
        }

    def submit(self, job: dict) -> dict:
        self.jobs.append(job)
        self._calls += 1
        fail_after = self.failure.get("fail_after")
        if fail_after is not None and self._calls > int(fail_after):
            raise WorkerUnavailable("simulated worker outage after dispatch")
        if self.failure.get("outcome_unknown"):
            return {
                "status": "outcome_unknown",
                "classification": "infrastructure_error",
                "worker_identity": self.identity,
                "cases": [],
                "usage": {"unknown": True},
                "artifact": {"job_id": job.get("job_id")},
            }
        if self.deferred:
            job_id = str(job.get("job_id"))
            self._pending[job_id] = job
            return {"status": "pending", "classification": "pending",
                    "worker_identity": self.identity, "job_id": job_id,
                    "usage": {"unknown": True}}
        return self._compute(job)

    def settle(self, job_id: str) -> dict:
        job = self._pending.pop(job_id, None)
        if job is None:
            raise WorkerUnavailable(f"unknown or already settled job {job_id}")
        return self._compute(job)

    def cancel(self, job_id: str) -> bool:
        """Simulated worker cancellation acknowledgement."""
        if job_id in self._pending:
            self._pending.pop(job_id, None)
            return True
        return False

    def _compute(self, job: dict) -> dict:
        if self.failure.get("compile_error"):
            return {
                "status": "failed",
                "classification": "compile_error",
                "worker_identity": self.identity,
                "cases": [],
                "usage": {},
                "error_code": "compile_error",
            }
        try:
            behavior = candidates.BEHAVIORS[fake_behavior_name(job["candidate"]["source"])]
        except (WorkerProtocolError, KeyError) as exc:
            return {
                "status": "failed",
                "classification": "worker_protocol_error",
                "worker_identity": self.identity,
                "cases": [],
                "usage": {},
                "error_code": str(exc),
            }
        cases_out = []
        for entry in job["cases"]:
            started = time.monotonic()
            try:
                instance = parse_instance(entry["input"])
                value = behavior(instance)
                cases_out.append({
                    "case_id": entry["case_id"],
                    "status": "ok",
                    "exit": 0,
                    "output": str(int(value)),
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
                })
            except InvalidInput as exc:
                cases_out.append({"case_id": entry["case_id"], "status": "invalid_input",
                                  "error": str(exc)})
            except candidates.CandidateFailure as exc:
                cases_out.append({"case_id": entry["case_id"], "status": exc.code,
                                  "error": str(exc)})
            except Exception as exc:  # noqa: BLE001 - classify, never crash the test host
                cases_out.append({"case_id": entry["case_id"], "status": "candidate_runtime_error",
                                  "error": f"{type(exc).__name__}: {exc}"})
        return {
            "status": "completed",
            "classification": "completed",
            "worker_identity": self.identity,
            "cases": cases_out,
            "usage": {"cases": len(cases_out), "cpu_ms": 0, "unknown": False},
            "raw": {"job_id": job.get("job_id")},
        }


class IsolateWorker:
    """Real Isolate client adapter.  Fails closed when the endpoint is absent."""

    identity = "isolate-client (qualified only when AUTHOR_AGENT_ISOLATE_URL is set)"
    is_real = True

    def __init__(self, *, batch_limit: int = 50):
        self.batch_limit = batch_limit

    def describe(self) -> dict:
        import isolate_client

        return {
            "identity": self.identity,
            "real": True,
            "configured": isolate_client.configured(),
            "qualified": False,
            "qualification": "pending live-worker qualification",
        }

    def submit(self, job: dict) -> dict:
        from .protocol import aggregate, normalize_isolate_case

        import isolate_client
        if not isolate_client.configured():
            raise WorkerUnavailable(
                "No isolated worker is configured (AUTHOR_AGENT_ISOLATE_URL); "
                "generated code is never executed on the host"
            )
        source = job["candidate"]["source"]
        cases = job["cases"][: self.batch_limit]
        campaign = bool(job.get("campaign"))
        wall_seconds = float(job["budget"].get("wall_ms", 60000)) / 1000
        deadline = time.monotonic() + wall_seconds
        out: list[dict] = []
        stop = "batch_limit" if len(job["cases"]) > len(cases) else None
        for entry in cases:
            remaining = deadline - time.monotonic()
            if campaign and remaining <= 0:
                stop = "deadline"
                break
            cpu_limit = wall_seconds / max(1, len(cases))
            timeout_args = {}
            if campaign:
                cpu_limit = min(2.0, cpu_limit, remaining)
                timeout_args = {"request_timeout": remaining, "wall_time": remaining}
            try:
                result = isolate_client.run(
                    source, job["candidate"].get("language", "cpp"), entry["input"],
                    time_limit=cpu_limit,
                    memory_mb=int(job["budget"].get("memory_mib", 256)),
                    fsize_mb=1 if campaign else 4,
                    **timeout_args,
                )
            except Exception as exc:  # noqa: BLE001
                return {
                    "status": "outcome_unknown" if campaign else "failed",
                    "classification": "outcome_unknown" if campaign else "infrastructure_error",
                    "worker_identity": self.identity,
                    "protocolVersion": 1,
                    "cases": out,
                    "usage": {"cases": len(out), "unknown": True},
                    "error_code": f"{type(exc).__name__}: {exc}"[:1000],
                }
            normalized = (normalize_isolate_case(result, output_limit=job["budget"]["output_bytes"])
                          if campaign else normalize_isolate_case(result))
            normalized["case_id"] = entry["case_id"]
            out.append(normalized)
            if campaign and time.monotonic() >= deadline:
                stop = "deadline"
                break
            if campaign and normalized["status"] == "compile_error":
                stop = "compile_error" if len(out) < len(cases) else stop
                break
        truncation = ({"requested": len(job["cases"]), "completed": len(out),
                       "reason": stop} if stop else {})
        aggregate_result = aggregate(out, requested=len(job["cases"]),
                                     completed=len(out), truncation=truncation)
        aggregate_result.update({
            "worker_identity": self.identity if campaign else json_identity(),
            "protocolVersion": 1,
            "cases": out,
            "usage": {
                "cases": len(out),
                "cpu_ms": round(sum((case.get("usage") or {}).get("time_ms", 0) for case in out), 3),
                "unknown": False,
            },
            "truncation": truncation,
        })
        return aggregate_result

    def cancel(self, job_id: str) -> bool:
        """The current Isolate HTTP surface has no job-cancel endpoint.

        Returning False makes cancellation unconfirmed, so the ledger records
        outcome_unknown rather than claiming the worker stopped.
        """
        return False


def json_identity() -> str:
    try:
        import isolate_client

        return isolate_client.health().get("version", "isolate-client")
    except Exception:  # noqa: BLE001
        return "isolate-client"


def available_worker(force_fake: FakeWorker | None = None) -> Any:
    """Prefer an explicit fake for deterministic tests, else the real adapter."""
    if force_fake is not None:
        return force_fake
    return IsolateWorker()
