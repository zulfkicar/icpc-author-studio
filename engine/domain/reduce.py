"""Replay and reduce weighted-scheduling witnesses without changing their predicate."""
from __future__ import annotations

from typing import Callable

from ..schemas import sha256_text
from . import Instance, InvalidInput, Job, parse_instance, render_instance
from .differential import CampaignError, checked_oracle, evaluate_receipt, qualify_oracle


def _instance(rows) -> Instance:
    return Instance(tuple(Job(start, finish, reward, label)
                          for label, (start, finish, reward) in enumerate(rows)))


def _simplifications(instance: Instance):
    rows = [(job.start, job.finish, job.reward) for job in instance.jobs]
    if len(rows) > 1:
        for i in range(len(rows)):
            yield "remove booking", _instance(rows[:i] + rows[i + 1:])
    rank = {value: i for i, value in enumerate(sorted({value for start, finish, _ in rows
                                                        for value in (start, finish)}))}
    compact = [(rank[start], rank[finish], reward) for start, finish, reward in rows]
    if compact != rows:
        yield "compact endpoints", _instance(compact)
    for i, (start, finish, reward) in enumerate(rows):
        if reward > 1:
            yield "simplify reward", _instance(rows[:i] + [(start, finish, 1)] + rows[i + 1:])


def check_witness(original: dict, semantics: str, *, reduce: bool, limits: dict,
                  execute: Callable[[str, str], dict]) -> dict:
    """Use exact replay as a gate, then keep only legal, independently checked simplifications."""
    report = {"original": original, "replay": None, "reduced": None, "predicate": None,
              "trials": [], "oracleSubsets": 0, "oracleControls": [], "worker": None}
    seen: set[str] = set()
    alternate = "closed" if semantics == "half_open" else "half_open"

    def oracle(instance, rule):
        cost = 1 << instance.n
        if report["oracleSubsets"] + cost > limits["oracle_subsets"]:
            raise CampaignError("oracle_budget", "The oracle budget has been used.")
        report["oracleSubsets"] += cost
        return checked_oracle(instance, rule)

    def probe(text, method, *, compare_alternate=False, expected_original=None):
        if len(report["trials"]) >= limits["cases"]:
            raise CampaignError("case_budget", "The case budget has been used.")
        try:
            instance = parse_instance(text)
        except InvalidInput as exc:
            raise CampaignError("invalid_input", "Witness failed scheduling input validation.") from exc
        if instance.n > 12 or render_instance(instance) != text:
            raise CampaignError("invalid_input", "Witness did not pass canonical input validation.")
        expected = oracle(instance, semantics)
        if expected_original is not None and expected != expected_original:
            raise CampaignError("oracle_changed", "The independent oracle no longer agrees with the original receipt.")
        alt = oracle(instance, alternate) if compare_alternate else None
        case_id = f"witness-{len(report['trials']):03d}"
        item = {"case_id": case_id, "input": text, "inputHash": sha256_text(text),
                "expected": expected, "legal": True, "method": method}
        seen.add(text)
        raw = execute(case_id, text)
        report["worker"] = raw.get("worker_identity") or report["worker"]
        result = evaluate_receipt({"cases": [item], "declared": 1, "selectionStop": None,
                                   "spec": {"mode": "seeded"}}, raw)
        status = result["classification"]
        if raw.get("status") in ("cancelled", "outcome_unknown", "pending"):
            status = "outcome_unknown"
        actual = None
        if result["complete"]:
            actual = result["firstMismatch"]["actual"] if status == "counterexample" else expected
        truncation = raw.get("truncation")
        if isinstance(truncation, dict) and truncation.get("reason") == "deadline":
            status = "wall_budget"
        report["trials"].append({"method": method, "inputHash": item["inputHash"], "jobs": instance.n,
                                 "expected": expected, "actual": actual, "status": status})
        if actual is None:
            raise CampaignError(status if status not in ("agreement", "counterexample") else "worker_incomplete",
                                "The worker did not return a complete numeric result.")
        return {**item, "actual": actual, "alternateExpected": alt}

    try:
        controls, usage = qualify_oracle(semantics, limits["oracle_subsets"])
        report.update(oracleControls=controls, oracleSubsets=usage)
        first = report["replay"] = probe(original["input"], "exact replay", expected_original=original["expected"])
        if first["actual"] != original["actual"]:
            return {**report, "status": "not_reproduced", "termination": "answer_changed"}
        if not reduce:
            return {**report, "status": "reproduced", "termination": "exact_replay"}

        starting = parse_instance(first["input"])
        controls, usage = qualify_oracle(alternate, limits["oracle_subsets"] - report["oracleSubsets"])
        report["oracleControls"] += [{**c, "semantics": alternate} for c in controls]
        report["oracleSubsets"] += usage
        endpoint_sensitive = oracle(starting, alternate) == first["actual"]
        under = first["actual"] < first["expected"]
        report["predicate"] = {"kind": "endpoint_signature", "alternateRule": alternate,
                               "direction": "under" if under else "over"} if endpoint_sensitive else {
                                   "kind": "exact_numeric_mismatch", "expected": first["expected"],
                                   "actual": first["actual"]}
        current = starting
        while True:
            for method, candidate in _simplifications(current):
                text = render_instance(candidate)
                if text in seen:
                    continue
                trial = probe(text, method, compare_alternate=endpoint_sensitive)
                expected, actual = trial["expected"], trial["actual"]
                matches = (actual == trial["alternateExpected"] and actual != expected
                           and (actual < expected) == under) if endpoint_sensitive else (
                               expected == first["expected"] and actual == first["actual"])
                if matches:
                    report["reduced"] = trial
                    current = candidate
                    break
            else:
                return {**report, "status": "reduced" if report["reduced"] else "no_reduction",
                        "termination": "checks_exhausted"}
    except CampaignError as exc:
        return {**report, "status": "reduced" if report["reduced"] else exc.kind,
                "termination": exc.kind, "detail": str(exc)}
