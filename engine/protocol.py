"""Validated mapping from the existing Isolate HTTP result to engine cases.

The real `isolate_worker.py` source-run endpoint reports success as
``status="OK", exit=0`` (uppercase), compile failure as ``CE``, timeouts as
``TO``, and runtime/signal failures as ``RE``/``SG``.  The engine's internal
contract is lowercase and requires all of status, exit code, compile output and
timing fields to agree.  A textual "ok" alone is not success.
"""
from __future__ import annotations

import re
from typing import Any

MAX_DIAGNOSTIC = 2_000
MAX_OUTPUT = 64 * 1024

_SUCCESS = {"OK", "AC", "ACCEPTED", "SUCCESS"}
_COMPILE = {"CE", "COMPILE_ERROR", "COMPILATION_ERROR"}
_TIMEOUT = {"TO", "TIME_OUT", "TIMEOUT", "TLE"}
_MEMORY = {"ML", "MLE", "MEMORY_LIMIT", "MEMORY_LIMIT_EXCEEDED"}
_OUTPUT_LIMIT = {"OL", "OLE", "OUTPUT_LIMIT", "OUTPUT_LIMIT_EXCEEDED"}
_RUNTIME = {"RE", "SG", "RUNTIME_ERROR", "SIGNAL"}
_INFRA = {"XX", "INFRA", "INFRASTRUCTURE_ERROR", "JUDGE_ERROR"}
_PENDING = {"PENDING", "QUEUED", "RUNNING"}
_CANCELLED = {"CANCELLED", "CANCELED", "ABORTED"}
_UNKNOWN = {"UNKNOWN", "LOST", "OUTCOME_UNKNOWN"}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number >= 0 else default


def _bounded(text: Any, limit: int = MAX_DIAGNOSTIC) -> tuple[str, bool]:
    value = str(text or "")
    return (value[:limit], len(value) > limit)


def normalize_isolate_case(result: Any, *, output_limit: int = MAX_OUTPUT) -> dict:
    """Return one normalized case or an explicit protocol/infrastructure outcome."""
    if not isinstance(result, dict):
        return {
            "status": "worker_protocol_error", "classification": "worker_protocol_error",
            "error": "worker response is not an object", "retryability": "not_retryable",
        }
    status_raw = result.get("status") or result.get("verdict")
    if not isinstance(status_raw, str) or not status_raw.strip():
        return {
            "status": "worker_protocol_error", "classification": "worker_protocol_error",
            "error": "worker response lacks a textual status", "retryability": "not_retryable",
            "rawStatus": status_raw,
        }
    status = status_raw.strip().upper()
    exit_raw = result.get("exit", result.get("exitcode"))
    if exit_raw is None:
        exit_code = None
    else:
        try:
            exit_code = int(exit_raw)
        except (TypeError, ValueError):
            return {
                "status": "worker_protocol_error", "classification": "worker_protocol_error",
                "error": f"worker exit is not an integer: {exit_raw!r}",
                "retryability": "not_retryable", "rawStatus": status_raw,
            }
    ok_flag = result.get("ok")
    stdout_raw = str(result.get("stdout") or "")
    stdout = stdout_raw[:output_limit]
    output_truncated = len(stdout_raw) > output_limit
    stderr, stderr_truncated = _bounded(result.get("stderr"))
    message, message_truncated = _bounded(result.get("message"))
    compile_output, compile_truncated = _bounded(result.get("compileOutput"))
    time_seconds = _number(result.get("time"), 0.0)
    wall_seconds = _number(result.get("wallTime"), 0.0)
    memory_kb = int(_number(result.get("memory"), 0))
    message_lower = message.lower()

    def case(status: str, classification: str, *, retryability: str = "not_retryable",
             error: str | None = None) -> dict:
        return {
            "status": status,
            "classification": classification,
            "output": stdout.strip(),
            "exit": exit_code,
            "stderr": stderr,
            "stderrTruncated": stderr_truncated,
            "compileOutput": compile_output,
            "compileOutputTruncated": compile_truncated,
            "message": message,
            "messageTruncated": message_truncated,
            "outputTruncated": output_truncated,
            "rawStatus": status_raw,
            "usage": {
                "time_ms": round(time_seconds * 1000, 3),
                "wall_ms": round(wall_seconds * 1000, 3),
                "memory_mb": round(memory_kb / 1024, 3) if memory_kb else 0,
                "output_bytes": len(stdout_raw.encode("utf-8", "replace")),
                "unknown": False,
            },
            "retryability": retryability,
            "error": error,
        }

    # Infrastructure/protocol failures are distinct from candidate outcomes.
    if status in _INFRA:
        return case("infrastructure_error", "infrastructure_error",
                    retryability="resumable", error=message or "worker infrastructure error")
    if status in _CANCELLED:
        return case("cancelled", "cancelled_by_user", error=message or "worker cancelled")
    if status in _UNKNOWN:
        return case("outcome_unknown", "infrastructure_error",
                    retryability="resumable", error=message or "worker outcome unknown")
    if status in _PENDING:
        return case("pending", "pending", retryability="resumable")
    if status in _COMPILE:
        return case("compile_error", "compile_error",
                    error=compile_output or message or "compile failed")
    if status in _TIMEOUT:
        return case("time_limit", "time_limit", error=message or "time limit exceeded")
    if status in _MEMORY or "memory limit" in message_lower:
        return case("memory_limit", "memory_limit", error=message or "memory limit exceeded")
    if status in _OUTPUT_LIMIT or "output limit" in message_lower:
        return case("output_limit", "output_limit", error=message or "output limit exceeded")
    if status in _RUNTIME or exit_code not in (0, None):
        return case("candidate_runtime_error", "candidate_runtime_error",
                    error=message or f"nonzero exit {exit_code}")
    if status in _SUCCESS:
        if exit_code is None:
            return case("worker_protocol_error", "worker_protocol_error",
                        error="success status without an exit code")
        if exit_code != 0:
            return case("candidate_runtime_error", "candidate_runtime_error",
                        error=f"success status with nonzero exit {exit_code}")
        if ok_flag is False:
            return case("worker_protocol_error", "worker_protocol_error",
                        error="worker marked success status but ok=false")
        if output_truncated:
            return case("output_limit", "output_limit",
                        error="captured candidate output exceeded the adapter bound")
        return case("ok", "ok")
    # Unknown textual status must not be guessed into success.
    return case("worker_protocol_error", "worker_protocol_error",
                error=f"unrecognized worker status {status_raw!r}")


def aggregate(cases: list[dict], *, requested: int, completed: int,
              truncation: dict | None = None) -> dict:
    """Aggregate case outcomes without collapsing infrastructure into failure."""
    statuses = [case.get("status") for case in cases]
    if any(status == "worker_protocol_error" for status in statuses):
        return {"status": "failed", "classification": "worker_protocol_error"}
    if any(status == "infrastructure_error" for status in statuses):
        return {"status": "failed", "classification": "infrastructure_error"}
    if any(status == "compile_error" for status in statuses):
        return {"status": "failed", "classification": "compile_error"}
    if any(status == "cancelled" for status in statuses):
        return {"status": "cancelled", "classification": "cancelled_by_user"}
    if any(status == "outcome_unknown" for status in statuses):
        return {"status": "outcome_unknown", "classification": "infrastructure_error"}
    if any(status == "pending" for status in statuses):
        return {"status": "pending", "classification": "pending"}
    if truncation or completed < requested:
        return {"status": "incomplete", "classification": "resource_exhausted"}
    return {"status": "completed", "classification": "completed"}
