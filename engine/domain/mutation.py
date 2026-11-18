"""Bounded test-by-mutant adjudication for weighted interval scheduling."""
from __future__ import annotations

from ..schemas import sha256_text
from . import InvalidInput, parse_instance, render_instance
from .differential import CampaignError, checked_oracle, exact_integer_output, qualify_oracle

# Quadratic DP for the control. The independently enumerated subset oracle
# decides every expected answer, including the control answers.
_PROGRAM = r"""
#include <algorithm>
#include <array>
#include <iostream>
#include <vector>

int main() {
    int n;
    if (!(std::cin >> n)) return 1;
    std::vector<std::array<long long, 3>> jobs(n);
    for (auto &job : jobs) std::cin >> job[1] >> job[0] >> job[2];
    std::stable_sort(jobs.begin(), jobs.end(), [](const auto &a, const auto &b) {
        return a[0] != b[0] ? a[0] < b[0] : a[1] < b[1];
    });
    auto compatible = [](long long end, long long start) {
        return end < start || (TOUCHING && end == start);
    };
#if GREEDY
    long long total = 0, end = -1;
    for (const auto &job : jobs) {
        if (!compatible(end, job[1])) continue;
        total += job[2];
        end = job[0];
    }
#else
    std::vector<long long> best(n + 1);
    for (int i = 0; i < n; ++i) {
        int prior = i;
        while (prior > 0 && !compatible(jobs[prior - 1][0], jobs[i][1])) --prior;
        best[i + 1] = std::max(best[i], best[prior] + jobs[i][2]);
    }
    long long total = best[n];
#endif
    if (NARROW) total %= 2147483648LL;
    std::cout << total << '\n';
}
"""


def registered_candidates(semantics: str) -> list[dict]:
    half_open = semantics == "half_open"
    variants = [
        ("control", "Correct scheduling DP", half_open, False, False, "dp_correct" if half_open else "dp_strict"),
        ("endpoint", "Reversed touching rule", not half_open, False, False, "dp_strict" if half_open else "dp_correct"),
        ("greedy", "Earliest finish greedy", half_open, True, False, "earliest_finish_greedy" if half_open else "greedy_closed"),
        ("narrow", "31-bit reward total", half_open, False, True, "narrow_half_open" if half_open else "narrow_closed"),
    ]
    return [
        {"id": name, "label": label, "role": "control" if name == "control" else "mutant",
         "source": f"// fake-behavior: {simulator}\n#define TOUCHING {int(touching)}\n"
                   f"#define GREEDY {int(greedy)}\n#define NARROW {int(narrow)}\n" + _PROGRAM}
        for name, label, touching, greedy, narrow, simulator in variants
    ]


def _cell(case: dict, status: str, *, actual=None, detail=None) -> dict:
    return {"caseId": case["case_id"], "status": status, "expected": case["expected"],
            "actual": actual, "detail": detail}


def _evaluate_batch(cases: list[dict], raw: dict, *, control: bool) -> list[dict]:
    rows = raw.get("cases")
    valid_ids = {case["case_id"] for case in cases}
    if (not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get("case_id"), str)
                                         for row in rows)):
        return [_cell(case, "worker_failure", detail="malformed worker receipt") for case in cases]
    by_id = {row["case_id"]: row for row in rows}
    if len(by_id) != len(rows) or not by_id.keys() <= valid_ids:
        return [_cell(case, "worker_failure", detail="duplicate or unexpected case receipt") for case in cases]
    if raw.get("classification") == "compile_error" or any(row.get("status") == "compile_error" for row in rows):
        return [_cell(case, "compile_error") for case in cases]
    # Partial or contradictory batches do not establish numeric results.
    if raw.get("status") != "completed" or raw.get("truncation") or raw.get("classification") not in (None, "completed"):
        return [_cell(case, "worker_failure", detail=str(raw.get("classification") or raw.get("status"))[:120])
                for case in cases]
    cells = []
    for case in cases:
        row = by_id.get(case["case_id"]) or {}
        actual = exact_integer_output(row)
        reason = row.get("status")
        if actual is not None:
            status = "matched" if actual == case["expected"] else ("control_mismatch" if control else "killed")
            cells.append(_cell(case, status, actual=actual))
        elif reason in ("candidate_runtime_error", "time_limit", "memory_limit", "output_limit"):
            cells.append(_cell(case, reason))
        elif reason == "ok":
            cells.append(_cell(case, "invalid_output"))
        else:
            cells.append(_cell(case, "worker_failure", detail=str(reason or "missing case receipt")[:120]))
    return cells


def evaluate_matrix(cases: list[dict], candidates: list[dict], semantics: str, limits: dict, execute) -> dict:
    report = {"status": "partial", "termination": "complete", "semantics": semantics,
              "tests": cases, "columns": [], "worker": None, "oracleSubsets": 0,
              "oracleControls": [], "controlPassed": False}
    cap = limits["cases"] // len(candidates)
    selected = []
    try:
        controls, usage = qualify_oracle(semantics, limits["oracle_subsets"])
        report.update(oracleControls=controls, oracleSubsets=usage)
        for case in cases[:cap]:
            instance = parse_instance(case["input"])
            if (instance.n > 12 or render_instance(instance) != case["input"]
                    or sha256_text(case["input"]) != case["inputHash"]):
                raise CampaignError("invalid_input", "A saved input failed canonical validation.")
            cost = 1 << instance.n
            if report["oracleSubsets"] + cost > limits["oracle_subsets"]:
                report["termination"] = "oracle_budget"
                break
            report["oracleSubsets"] += cost
            if checked_oracle(instance, semantics) != case["expected"]:
                raise CampaignError("oracle_changed", "Independent answers disagree with the campaign receipt.")
            selected.append(case)
        if report["termination"] == "complete" and len(selected) < len(cases):
            report["termination"] = "case_budget"
    except (CampaignError, InvalidInput) as exc:
        report.update(termination=getattr(exc, "kind", "invalid_input"), detail=str(exc))
        selected.clear()
    report["qualifiedTests"] = len(selected)

    stopped = False
    for candidate in candidates:
        control = candidate["role"] == "control"
        cells = []
        if selected and not stopped and (control or report["controlPassed"]):
            try:
                raw = execute(candidate["source"], selected, candidate["id"])
                report["worker"] = raw.get("worker_identity") or report["worker"]
                cells = _evaluate_batch(selected, raw, control=control)
            except CampaignError as exc:
                if exc.kind in ("stale", "wall_budget", "case_budget"):
                    report["termination"] = exc.kind
                    stopped = True
                else:
                    cells = [_cell(case, "worker_failure", detail=exc.kind) for case in selected]
        if control and cells:
            report["controlPassed"] = all(cell["status"] == "matched" for cell in cells)
        cells += [_cell(case, "not_run") for case in cases[len(cells):]]
        killed_by = [cell["caseId"] for cell in cells if cell["status"] == "killed"]
        if control:
            status = ("control_passed" if len(selected) == len(cases) else "control_partial") if report["controlPassed"] else "control_failed"
        elif killed_by:
            status = "killed"
        elif all(cell["status"] == "matched" for cell in cells):
            status = "survived"
        elif any(cell["status"] == "compile_error" for cell in cells):
            status = "compile_error"
        else:
            status = "unresolved"
        report["columns"].append({**{k: v for k, v in candidate.items() if k != "source"}, "status": status,
                                  "sourceHash": sha256_text(candidate["source"]), "killedBy": killed_by, "cells": cells})

    mutants = report["columns"][1:]
    report["counts"] = {key: sum(column["status"] == key for column in mutants)
                        for key in ("killed", "survived", "compile_error", "unresolved")}
    if selected and not report["controlPassed"]:
        report.update(status="control_failed", termination="control_failed" if report["termination"] == "complete" else report["termination"])
    elif all(cell["status"] in ("matched", "killed") for column in report["columns"] for cell in column["cells"]):
        report["status"] = "complete"
    elif report["termination"] == "complete":
        report["termination"] = "unresolved_cells"
    return report
