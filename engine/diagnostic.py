"""Bounded, independently derived diagnostic for weighted interval scheduling.

Oracle and candidate are distinct producers: the oracle enumerates subsets in
the trusted engine (independently of the DP), the candidate is executed only by
the worker boundary.  A stored answer or a renamed candidate is never accepted
as an independent oracle.
"""
from __future__ import annotations

import re

from .domain import (
    Instance,
    InvalidInput,
    oracle_subset,
    parse_instance,
    render_instance,
)
from .worker import WorkerUnavailable

MAX_ORACLE_JOBS = 20


def build_cases(instances: list[Instance], case_limit: int) -> list[dict]:
    return [
        {"case_id": f"case-{index:05d}", "input": render_instance(instance)}
        for index, instance in enumerate(instances[:case_limit])
    ]


def oracle_for(instance: Instance, *, semantics: str = "half_open") -> dict:
    if instance.n > MAX_ORACLE_JOBS:
        raise InvalidInput(f"oracle is bounded to {MAX_ORACLE_JOBS} jobs; got {instance.n}")
    return oracle_subset(instance, semantics=semantics)


def first_division_error(candidate_output: str, oracle_value: int) -> str | None:
    if candidate_output is None:
        return "candidate produced no output"
    text = str(candidate_output).strip()
    if not re.fullmatch(r"-?\d+", text):
        return f"candidate output {text[:80]!r} is not a single integer"
    try:
        value = int(text)
    except ValueError:
        return "candidate output is not an integer"
    if value != oracle_value:
        return f"expected {oracle_value}, candidate returned {value}"
    return None


def code_spans(source: str) -> list[dict]:
    """Locate endpoint comparison evidence in the candidate source.

    This is a text scan for reviewable spans, not an execution claim.
    """
    spans = []
    for number, line in enumerate((source or "").splitlines(), start=1):
        if re.search(r"finish\s*<\s*start|finish\s*<=\s*start|upper_bound|lower_bound", line):
            spans.append({"line": number, "text": line.strip()[:200]})
    return spans


def run_diagnostic(
    worker,
    *,
    candidate_source: str,
    instance: Instance,
    budget: dict,
    oracle_semantics: str = "half_open",
    candidate_language: str = "cpp",
    job_id: str = "job-diagnostic",
) -> dict:
    """Validate one bounded witness against the oracle and the worker candidate."""
    try:
        canonical = parse_instance(render_instance(instance))
    except InvalidInput as exc:
        return {
            "status": "failed",
            "classification": "invalid_input",
            "error_code": str(exc),
            "oracle": None,
            "candidate": None,
            "legal": False,
        }
    oracle = oracle_for(canonical, semantics=oracle_semantics)
    job = {
        "job_id": job_id,
        "kind": "replay_diagnostic",
        "candidate": {"source": candidate_source, "language": candidate_language},
        "cases": build_cases([canonical], int(budget.get("cases", 1))),
        "budget": budget,
    }
    try:
        receipt = worker.submit(job)
    except WorkerUnavailable as exc:
        return {
            "status": "failed",
            "classification": "infrastructure_error",
            "error_code": str(exc),
            "oracle": oracle,
            "candidate": None,
            "legal": True,
        }
    cases = receipt.get("cases") or []
    if receipt.get("status") == "outcome_unknown":
        return {
            "status": "outcome_unknown",
            "classification": "infrastructure_error",
            "oracle": oracle,
            "candidate": None,
            "legal": True,
            "worker_identity": receipt.get("worker_identity"),
        }
    if receipt.get("status") != "completed" or not cases:
        return {
            "status": "failed",
            "classification": receipt.get("classification") or "worker_error",
            "error_code": receipt.get("error_code"),
            "oracle": oracle,
            "candidate": None,
            "legal": True,
            "worker_identity": receipt.get("worker_identity"),
        }
    case = cases[0]
    if case.get("status") != "ok":
        return {
            "status": "failed",
            "classification": case.get("status"),
            "error_code": case.get("error"),
            "oracle": oracle,
            "candidate": None,
            "legal": True,
            "worker_identity": receipt.get("worker_identity"),
        }
    candidate_value = case.get("output")
    disagreement = first_division_error(candidate_value, oracle["value"])
    classification = "counterexample" if disagreement else "agreement"
    return {
        "status": "completed",
        "classification": classification,
        "legal": True,
        "input": render_instance(canonical),
        "oracle": oracle,
        "candidate": {"value": candidate_value, "raw": case},
        "disagreement": disagreement,
        "code_spans": code_spans(candidate_source),
        "worker_identity": receipt.get("worker_identity"),
        "usage": receipt.get("usage") or {},
        "artifacts": {"candidate_case_receipt": case, "worker_raw": receipt.get("raw")},
    }


def run_campaign(
    worker,
    *,
    candidate_source: str,
    instances: list[Instance],
    budget: dict,
    case_limit: int,
    candidate_language: str = "cpp",
    job_id: str = "job-campaign",
) -> dict:
    """Compare the candidate against the oracle over a declared finite domain.

    ``agreement`` is only returned when every declared case completed.  A
    truncated or failed campaign is ``incomplete`` and never a success.
    """
    declared = min(len(instances), int(case_limit))
    cases = build_cases(instances, declared)
    oracle_map: dict[str, dict] = {}
    for entry, instance in zip(cases, instances):
        try:
            oracle_map[entry["case_id"]] = oracle_for(parse_instance(entry["input"]))
        except InvalidInput as exc:  # an oracle-side invalid input is an engine defect
            return {
                "status": "failed", "classification": "invalid_input",
                "error_code": str(exc), "attempted": 0, "declared": declared,
            }
    job = {
        "job_id": job_id,
        "kind": "differential_search",
        "candidate": {"source": candidate_source, "language": candidate_language},
        "cases": cases,
        "budget": budget,
    }
    try:
        receipt = worker.submit(job)
    except WorkerUnavailable as exc:
        return {
            "status": "failed", "classification": "infrastructure_error",
            "error_code": str(exc), "attempted": 0, "declared": declared,
        }
    if receipt.get("status") == "outcome_unknown":
        return {
            "status": "outcome_unknown", "classification": "infrastructure_error",
            "attempted": 0, "declared": declared,
            "worker_identity": receipt.get("worker_identity"),
        }
    results = receipt.get("cases") or []
    attempted = len(results)
    valid = 0
    completed = 0
    first_mismatch = None
    for case in results:
        case_id = case["case_id"]
        if case.get("status") != "ok":
            if first_mismatch is None:
                first_mismatch = {
                    "case_id": case_id, "input": next(
                        (e["input"] for e in cases if e["case_id"] == case_id), ""),
                    "classification": case.get("status"), "error": case.get("error"),
                }
            continue
        valid += 1
        completed += 1
        expected = oracle_map[case_id]["value"]
        mismatch = first_division_error(case.get("output"), expected)
        if mismatch and first_mismatch is None:
            first_mismatch = {
                "case_id": case_id,
                "input": next((e["input"] for e in cases if e["case_id"] == case_id), ""),
                "classification": "counterexample",
                "expected": expected,
                "actual": case.get("output"),
                "comparison": mismatch,
            }
    if receipt.get("status") != "completed":
        return {
            "status": "failed",
            "classification": receipt.get("classification") or "worker_error",
            "error_code": receipt.get("error_code"),
            "attempted": attempted, "valid": valid, "completed": completed,
            "declared": declared,
        }
    truncation = receipt.get("truncation") or {}
    if attempted < declared or truncation:
        status = "incomplete"
        classification = "resource_exhausted"
    elif first_mismatch is not None:
        status = "completed"
        classification = (
            first_mismatch.get("classification")
            if first_mismatch.get("classification") in (
                "compile_error", "candidate_runtime_error", "invalid_output", "invalid_input"
            )
            else "counterexample"
        )
    else:
        status = "completed"
        classification = "agreement"
    return {
        "status": status,
        "classification": classification,
        "attempted": attempted,
        "valid": valid,
        "completed": completed,
        "declared": declared,
        "complete": status == "completed" and completed == declared,
        "first_mismatch": first_mismatch,
        "worker_identity": receipt.get("worker_identity"),
        "usage": receipt.get("usage") or {},
        "truncation": truncation,
    }


def touching_witness_report(instance: Instance) -> dict:
    """Hand-checkable expected values for the shared-semantics probe."""
    half = oracle_subset(instance, semantics="half_open")["value"]
    closed = oracle_subset(instance, semantics="closed")["value"]
    return {"half_open": half, "closed": closed, "input": render_instance(instance)}
