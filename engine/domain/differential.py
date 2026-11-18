"""Bounded weighted-scheduling campaigns with independent, replayable inputs."""
from __future__ import annotations

import random
import re
from typing import Annotated, Literal

from pydantic import Field, StrictInt, ValidationError

from ..schemas import Model, sha256_text
from . import FINITE_TYPES, InvalidInput, Job, Instance, compatible, finite_domain, oracle_subset, parse_instance, render_instance

GENERATOR = "weighted-scheduling-v1"
ORACLE = "subset-enumeration-v1"
MAX_CASES = 50
FAMILIES = ("touching", "nested_duplicates", "wide_rewards")


class CampaignSpec(Model):
    kind: Literal["weighted_campaign"]
    mode: Literal["exhaustive", "seeded"]
    seed: Annotated[StrictInt, Field(ge=0, le=2**32 - 1)]
    family: Literal["mixed", "touching", "nested_duplicates", "wide_rewards"] = "mixed"
    target_cases: Annotated[StrictInt, Field(ge=1, le=10_000)] | None = None
    lengths: list[Annotated[StrictInt, Field(ge=1, le=4)]] | None = Field(default=None, min_length=1, max_length=4)


class CampaignBudget(Model):
    cases: Annotated[StrictInt, Field(ge=1, le=MAX_CASES)]
    wall_ms: Annotated[StrictInt, Field(ge=1000, le=60_000)]
    oracle_subsets: Annotated[StrictInt, Field(ge=1, le=65_536)]


class CampaignError(ValueError):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def seeded_case(rng: random.Random, family: str) -> Instance:
    offset = rng.randrange(100, 10_000)
    step = rng.randrange(2, 19)
    if family == "touching":
        reward = rng.randrange(17, 80)
        rows = [(offset, offset + step, reward), (offset + step, offset + 2 * step, reward + 3),
                (offset, offset + 2 * step, 2 * reward + 4), (offset + 2 * step, offset + 4 * step, reward - 2)]
    elif family == "nested_duplicates":
        reward = rng.randrange(11, 48)
        rows = [(offset, offset + 6 * step, 2 * reward + 7),
                (offset + step, offset + 2 * step, reward), (offset + step, offset + 2 * step, reward),
                (offset + 2 * step, offset + 4 * step, reward + 1),
                (offset + 4 * step, offset + 5 * step, reward + 3)]
    else:
        offset = 10**9 - rng.randrange(120, 3000)
        rows = [(offset + i * (step + 1), offset + i * (step + 1) + step,
                 10**9 - rng.randrange(0, 10_000)) for i in range(4)]
        rows.append((offset, offset + 3 * (step + 1) + step, 10**9))
    rng.shuffle(rows)
    return Instance(tuple(Job(*row, label) for label, row in enumerate(rows)))


# Hand-derived controls are separate from the generator and candidate code.
_ORACLE_CONTROLS = (
    ("touching", "2\n5 8 7\n8 12 4\n", 11, 7),
    ("nesting", "3\n1 7 19\n2 4 9\n4 6 12\n", 21, 19),
    ("wide sum", "3\n17 20 1000000000\n21 27 1000000000\n30 35 1000000000\n", 3_000_000_000, 3_000_000_000),
)


def checked_oracle(instance: Instance, semantics: str) -> int:
    try:
        result = oracle_subset(instance, semantics=semantics)
        labels = result["best_subset"]
        if (result["producer"] != ORACLE or result["semantics"] != semantics
                or result["enumerations"] != 1 << instance.n or not isinstance(labels, list)
                or any(type(i) is not int or not 0 <= i < instance.n for i in labels)
                or len(labels) != len(set(labels))):
            raise ValueError("invalid oracle receipt")
        jobs = [instance.jobs[i] for i in labels]
        if (type(result["value"]) is not int or result["value"] != sum(job.reward for job in jobs)
                or any(not compatible(job, prior, semantics) for i, job in enumerate(jobs) for prior in jobs[:i])):
            raise ValueError("oracle optimum has no feasible witness")
        return result["value"]
    except Exception as exc:  # Oracle failure must never be charged to the candidate.
        raise CampaignError("oracle_invalid", f"Independent oracle failed: {exc}") from exc


def qualify_oracle(semantics: str, limit: int) -> tuple[list[dict], int]:
    audit = []
    subsets = 0
    for label, text, half_open, closed in _ORACLE_CONTROLS:
        instance = parse_instance(text)
        subsets += 1 << instance.n
        if subsets > limit:
            raise CampaignError("budget_exhausted", "Subset budget cannot cover the oracle controls.")
        expected = half_open if semantics == "half_open" else closed
        if checked_oracle(instance, semantics) != expected:
            raise CampaignError("oracle_invalid", f"Oracle disagreed with the hand-derived {label} control.")
        audit.append({"control": label, "expected": expected, "inputHash": sha256_text(text)})
    return audit, subsets


def prepare_campaign(domain: dict, budget: dict, *, semantics: str | None, case_ceiling: int,
                     wall_ceiling: int, worker_case_ceiling: int = MAX_CASES) -> dict:
    try:
        spec = CampaignSpec.model_validate(domain)
        limits = CampaignBudget.model_validate(budget)
    except ValidationError as exc:
        raise CampaignError("invalid_campaign", str(exc)) from exc
    if semantics not in ("half_open", "closed"):
        raise CampaignError("unresolved_semantics", "The author must settle the endpoint rule first.")
    if spec.mode == "seeded":
        if spec.target_cases is None or spec.lengths is not None:
            raise CampaignError("invalid_campaign", "Seeded campaigns require target_cases and omit lengths.")
        declared = spec.target_cases
    else:
        if spec.family != "mixed" or spec.target_cases is not None:
            raise CampaignError("invalid_campaign", "Exhaustive campaigns enumerate the registered job grid.")
        lengths = sorted(set(spec.lengths or [1, 2]))
        declared = sum(len(FINITE_TYPES)**n for n in lengths)
    selected_cap = min(declared, limits.cases, case_ceiling, worker_case_ceiling)
    wall_ms = min(limits.wall_ms, wall_ceiling)
    if selected_cap < 1 or wall_ms < 1000:
        raise CampaignError("budget_exhausted", "No case or execution time remains for this campaign.")

    audit, subsets = qualify_oracle(semantics, limits.oracle_subsets)

    if spec.mode == "exhaustive":
        order = finite_domain(lengths=lengths)
        if spec.seed:
            random.Random(spec.seed).shuffle(order)
        candidates = (("registered_grid", instance) for instance in order[:selected_cap])
    else:
        rng = random.Random(spec.seed)
        families = FAMILIES if spec.family == "mixed" else (spec.family,)
        order = tuple(families[i % len(families)] for i in range(selected_cap))
        candidates = ((family, seeded_case(rng, family)) for family in order)

    cases = []
    stop = "case_budget" if selected_cap < declared else None
    try:
        for family, candidate in candidates:
            text = render_instance(candidate)
            instance = parse_instance(text)
            if instance != candidate or instance.n > 12:
                raise InvalidInput("generated case failed canonical round-trip or exceeds 12 jobs")
            cost = 1 << instance.n
            if subsets + cost > limits.oracle_subsets:
                stop = "oracle_budget"
                break
            expected = checked_oracle(instance, semantics)
            subsets += cost
            cases.append({"case_id": f"case-{len(cases):05d}", "family": family, "input": text,
                          "inputHash": sha256_text(text), "expected": expected, "subsets": cost})
    except CampaignError:
        raise
    except (ValueError, TypeError, AttributeError, RuntimeError) as exc:
        raise CampaignError("generator_invalid", f"Generated input rejected: {exc}") from exc
    if not cases:
        raise CampaignError("budget_exhausted", "Subset budget cannot evaluate the first generated case.")
    recorded_spec = spec.model_dump()
    if spec.mode == "exhaustive":
        recorded_spec["lengths"] = lengths
    return {"kind": "weighted_campaign_manifest", "version": 1, "generator": GENERATOR,
            "profile": "weighted-interval-scheduling", "spec": recorded_spec, "semantics": semantics,
            "oracle": {"id": ORACLE, "controls": audit, "subsets": subsets},
            "declared": declared, "limits": {"requested": limits.model_dump(), "cases": len(cases),
                                              "wall_ms": wall_ms},
            "selectionStop": stop, "cases": cases}


def exact_integer_output(row: dict) -> int | None:
    output = row.get("output")
    if (row.get("status") == "ok" and type(row.get("exit")) is int and row["exit"] == 0
            and not row.get("outputTruncated") and isinstance(output, str)
            and re.fullmatch(r"[+-]?[0-9]{1,24}", output.strip())):
        return int(output)
    return None


def evaluate_receipt(manifest: dict, raw: dict) -> dict:
    """Bind each receipt to its case ID and compare integers against the frozen host answers."""
    entries = {case["case_id"]: case for case in manifest["cases"]}
    rows = raw.get("cases")
    report = {"declared": manifest["declared"], "selected": len(entries), "attempted": 0,
              "completed": 0, "matched": 0, "complete": False, "firstMismatch": None,
              "firstError": None, "classification": "worker_protocol_error", "termination": "worker_protocol_error"}
    if not isinstance(rows, list) or raw.get("status") not in ("completed", "incomplete", "failed"):
        return report
    if any(not isinstance(row, dict) or not isinstance(row.get("case_id"), str) for row in rows):
        return report
    receipts = {row["case_id"]: row for row in rows}
    if len(receipts) != len(rows) or not receipts.keys() <= entries.keys():
        return report
    report["attempted"] = len(rows)
    failures = {"compile_error", "candidate_runtime_error", "time_limit", "output_limit", "memory_limit",
                "infrastructure_error", "worker_protocol_error", "cancelled", "outcome_unknown"}
    for key, case in entries.items():
        if key not in receipts:
            continue
        row = receipts[key]
        status = row.get("status")
        actual = exact_integer_output(row)
        if status == "ok" and type(row.get("exit")) is int and row["exit"] == 0 and not row.get("outputTruncated"):
            if actual is not None:
                report["completed"] += 1
                if actual == case["expected"]:
                    report["matched"] += 1
                elif report["firstMismatch"] is None:
                    report["firstMismatch"] = {**case, "legal": True, "actual": actual,
                                               "comparison": f"expected {case['expected']}, got {actual}"}
                continue
            status = "invalid_output"
        elif not isinstance(status, str) or status not in failures:
            status = "worker_protocol_error"
        if report["firstError"] is None:
            report["firstError"] = {"case_id": key, "classification": status}
    truncation = raw.get("truncation") or {}
    if not isinstance(truncation, dict):
        report.update(classification="worker_protocol_error", termination="worker_protocol_error", firstMismatch=None)
        return report
    worker_stop = truncation.get("reason")
    if worker_stop is not None and not isinstance(worker_stop, str):
        report.update(firstMismatch=None)
        return report
    stop = worker_stop or manifest["selectionStop"]
    complete = (raw["status"] == "completed" and raw.get("classification") in (None, "completed")
                and report["completed"] == len(entries) == manifest["declared"] and not stop)
    report["complete"] = complete
    if report["firstMismatch"]:
        report.update(classification="counterexample", termination=stop or ("declared_scope_completed" if complete else "worker_incomplete"))
    elif complete:
        report.update(classification="agreement", termination="domain_exhausted" if manifest["spec"]["mode"] == "exhaustive" else "sample_exhausted")
    elif report["firstError"]:
        outcome = report["firstError"]["classification"]
        report.update(classification=outcome, termination=outcome)
    elif isinstance(raw.get("classification"), str) and raw["classification"] in failures:
        report.update(classification=raw["classification"], termination=raw["classification"])
    elif worker_stop == "deadline" or (stop in ("case_budget", "oracle_budget") and report["completed"] == len(entries)):
        report.update(classification="budget_exhausted", termination=stop)
    else:
        report.update(classification="worker_incomplete", termination=stop or "receipt incomplete")
    return report
