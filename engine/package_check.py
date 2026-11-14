"""Run a frozen reference draft against independent weighted-interval answers."""
from __future__ import annotations

import hashlib
import re

from .domain import (oracle_subset, render_instance, witness_duplicate_jobs,
                     witness_large_reward, witness_two_touching, witness_weighted_greedy)
from .schemas import sha256_text
from .worker import WorkerUnavailable

MAX_REPAIRS = 2
_CANDIDATE_FAILURES = {"compile_error", "candidate_runtime_error", "time_limit", "memory_limit", "output_limit"}


def _cases(files: list[dict], semantics: str) -> list[dict]:
    # Fixed discriminators catch an endpoint or overflow defect even if the
    # model's own tests happen to agree with its mistaken implementation.
    cases = []
    for name, factory in (("touching", witness_two_touching), ("64-bit", witness_large_reward),
                          ("greedy", witness_weighted_greedy), ("duplicates", witness_duplicate_jobs)):
        instance = factory()
        cases.append({"case_id": "oracle:" + name, "input": render_instance(instance),
                      "expected": oracle_subset(instance, semantics=semantics)["value"]})
    cases.extend({"case_id": file["path"], "input": file["text"], "expected": file["oracleExpected"]}
                 for file in files if file["kind"] == "test")
    return cases


def _compare(cases: list[dict], raw: dict) -> tuple[str, list[dict], dict | None]:
    if not isinstance(raw, dict):
        return "infrastructure_error", [], {"detail": "worker response is not an object"}
    rows = raw.get("cases") or []
    if not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get("case_id"), str) for row in rows):
        return "infrastructure_error", [], {"detail": "worker case receipt has invalid IDs"}
    ids = [row.get("case_id") for row in rows]
    known = {case["case_id"]: case for case in cases}
    if (len(set(ids)) != len(ids) or any(i not in known for i in ids)
            or raw.get("status") not in ("completed", "failed")
            or (raw.get("status") == "failed" and (raw.get("classification") != "compile_error"
                or not any(row.get("status") == "compile_error" for row in rows)))):
        return "infrastructure_error", [], {"detail": str(raw.get("error_code") or raw.get("classification"))[:500]}

    observations = []
    failure = None
    for row in rows:
        case = known[row["case_id"]]
        actual = str(row.get("output", "")).strip()
        status = row.get("status")
        observation = {**case, "actual": actual[:160], "status": status, "exit": row.get("exit"),
                       "matched": False}
        if status == "ok" and row.get("exit") == 0 and not row.get("outputTruncated"):
            observation["matched"] = bool(re.fullmatch(r"[+-]?[0-9]{1,24}", actual)) and int(actual) == case["expected"]
            if not observation["matched"]:
                observation["status"] = "wrong_answer"
        elif status in _CANDIDATE_FAILURES:
            observation["diagnostic"] = str(row.get("error") or row.get("stderr") or status)[:1500]
        else:
            return "infrastructure_error", observations, {"case_id": row["case_id"], "detail": str(status)}
        observations.append(observation)
        if not observation["matched"] and failure is None:
            failure = observation

    if len(observations) != len(cases) and not (failure and failure["status"] == "compile_error"):
        return "infrastructure_error", observations, {"detail": "worker returned an incomplete case set"}
    return ("candidate_failed" if failure else "pass"), observations, failure


def check_reference(runtime, ctx: dict, action_id: str, files: list[dict], semantics: str, round_number: int) -> dict:
    source = next(file["text"] for file in files if file["kind"] == "solution")
    digest = runtime.store.put_blob(source.encode("utf-8"), kind="package-check-candidate")
    cases = _cases(files, semantics)
    check_id = "pkgcheck-" + sha256_text({"action": action_id, "source": digest, "cases": cases})[:18]
    claimed, existing = runtime.store.start_package_check(
        ctx["run_id"], check_id=check_id, action_id=action_id, source_hash=digest,
        cases=len(cases), context=ctx,
    )
    if not claimed:
        return existing or {"id": check_id, "status": "outcome_unknown", "cases": []}
    job = {"job_id": check_id, "kind": "differential_search", "candidate": {"source": source, "language": "cpp"},
           "cases": [{"case_id": case["case_id"], "input": case["input"]} for case in cases],
           "budget": {"wall_ms": 1500 * len(cases), "memory_mib": 256}}
    try:
        raw = runtime.worker.submit(job)
    except WorkerUnavailable as exc:
        raw = {"status": "failed", "classification": "infrastructure_error", "error_code": str(exc)}
    status, observations, failure = _compare(cases, raw)
    worker_name = raw.get("worker_identity") if isinstance(raw, dict) else None
    receipt = {"id": check_id, "status": status, "round": round_number, "cases": observations, "failure": failure,
               "sourceHash": digest, "semantics": semantics,
               "inputHashes": {file["path"]: hashlib.sha256(file["text"].encode("utf-8")).hexdigest()
                               for file in files if file["kind"] == "test"},
               "worker": worker_name or runtime.worker.identity}
    runtime.store.finish_package_check(check_id, receipt)
    runtime.store.append_event(ctx["run_id"], "package_oracle_check", role="worker", payload=receipt)
    return receipt
