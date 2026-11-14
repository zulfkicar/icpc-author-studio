"""Collaboration procedures and resources.

COL procedures are on-demand methods and resources, not stages or extra
agents (03 §1, 04 §8).  Retrieval composes one collaboration procedure plus at
most one domain procedure and up to two resource sections under a byte/token
cap; missing resources fail with ``resource_missing`` rather than substituted
advice.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

PROCEDURES: dict[str, dict] = {
    "COL-PACKAGE": {
        "id": "collab/package/v1",
        "purpose": "Draft reviewable reference code, a negative control, and concrete judge inputs from chat.",
        "procedure": [
            "Use the author record to settle the endpoint rule before drafting.",
            "Implement the optimum under the recorded rule and explain the proof and complexity.",
            "Design distinct inputs that discriminate endpoint, reward, duplicate and numeric errors.",
            "Present draft files for author review; package execution and export are separate author actions.",
        ],
        "completion": ["reference C++", "negative control", "editorial", "sample and secret input files"],
    },
    "COL-FRAME": {
        "id": "collab/frame/v1",
        "purpose": "Develop the shared specification with the author.",
        "procedure": [
            "Paraphrase the objective in one sentence.",
            "Separate unspecified facts from already chosen facts.",
            "Use one tiny example per consequential ambiguity.",
            "Ask at most three coupled questions; never repeat a settled choice.",
            "Record the author's choice with its input ID and derive affected requirements.",
            "Return a spec diff for visible inspection; an explicit choice applies without a redundant confirm.",
        ],
        "prompt": (
            "Which missing definition changes feasible solutions or expected output? Show its smallest "
            "distinguishing example. Preserve all settled choices and do not treat a familiar benchmark "
            "convention as author intent."
        ),
        "example": (
            "'Book talks for maximum value' lacks endpoint semantics. Ask whether [0,1) and [1,2) may both "
            "run. 'Yes, rooms free exactly at finish' establishes half-open compatibility. Then propose "
            "labelled jobs, start < finish, maximum sum and a numeric envelope, marking unchosen bounds as proposed."
        ),
        "failure": (
            "If the author says duration may be zero, explain why the pack's search/proof assumptions need "
            "revision and offer a supported positive-duration scope or a blocked extension; never normalise silently. "
            "A later contradictory endpoint input supersedes the earlier decision and invalidates dependents."
        ),
        "completion": ["versioned spec", "decision IDs", "remaining unknowns", "requirement/example map"],
        "acceptance": ["C01", "C06"],
    },
    "COL-COMPARE": {
        "id": "collab/compare/v1",
        "purpose": "Fairly test the author's preferred approach.",
        "procedure": [
            "Formulate each claim and its preconditions charitably.",
            "Identify what each approach optimises.",
            "Propose the cheapest discriminating input.",
            "Execute through the investigation boundary and explain the result at the chosen depth.",
            "Offer the surviving approach or a next bounded question.",
        ],
        "prompt": (
            "Do not discard an unconventional author idea because a standard algorithm exists. State its "
            "strongest testable version, a distinguishing case and what evidence would preserve or refute it."
        ),
        "example": (
            "Author says earliest finish maximises reward. On [0,2):6, [2,4):6, [0,4):13 greedy yields 12 and "
            "the optimum is 13. Say 'that exchange rule preserves count but not reward', link the lost-weight "
            "assumption, and suggest a DP. If the author prefers a sweep-line implementation, compare the same "
            "recurrence/invariant and accept it if justified."
        ),
        "failure": (
            "Random agreement does not prove greedy. A malformed counterexample must be repaired before rejection. "
            "If the author rejects an extra third reference to save time, retain the independent subset oracle, "
            "record the reduced scope and proceed without pressure."
        ),
        "completion": ["approach records", "preconditions", "valid witness or bounded unresolved result",
                       "author preference and rationale"],
        "acceptance": ["C02", "C03", "C12"],
    },
    "COL-PROOF": {
        "id": "collab/proof/v1",
        "purpose": "Build and challenge an argument together.",
        "procedure": [
            "Split feasibility, optimality, termination and complexity.",
            "Ask for or propose the missing link.",
            "Search for a counterexample before editing a disputed claim.",
            "Map each reviewed obligation to code.",
            "Distinguish a human lemma from its repaired agent derivation.",
        ],
        "prompt": (
            "Identify exactly which implication needs support. Use the author's lemma where valid, credit it, "
            "and challenge its assumptions rather than restating the whole proof."
        ),
        "example": (
            "Human lemma 'every schedule without job i lies in prefix i-1' supports the exclude case. Their added "
            "claim 'if i is chosen, every earlier job is compatible' is false: [0,3) conflicts with [2,4). Replace "
            "only that claim with 'selected remaining jobs lie in the compatible prefix p(i)' under finish sorting "
            "and positive duration. Both cases give max(D[i-1], w_i + D[p(i)]); each branch also constructs a "
            "feasible schedule. Complexity is n binary searches after sorting: O(n log n), sum bound 2*10^14 needs int64."
        ),
        "failure": (
            "A new setup-cost condition breaks p(i)'s simple prefix property; return to framing. Empirical "
            "agreement cannot discharge induction. A human assertion remains a claim, not truth."
        ),
        "completion": ["original lemma", "derived revision", "claim dependencies", "argument/code map",
                       "open challenges and review status"],
        "acceptance": ["C03", "C04"],
    },
    "COL-EXPLAIN": {
        "id": "collab/explain/v1",
        "purpose": "Connect a qualified counterexample to its cause.",
        "procedure": [
            "Replay or verify the receipt.",
            "Show input legality and expected/actual values.",
            "Identify the first violated invariant.",
            "Connect it to an assumption and a code span.",
            "State what remains unproved and propose the smallest next action.",
        ],
        "prompt": (
            "Give the shortest checkable explanation at the requested depth. Separate the observed mismatch "
            "from the inferred cause. Link the exact input, source hash and assumption; do not output private reasoning."
        ),
        "example": (
            "Two touching jobs with rewards 5 and 7 should yield 12 under half-open semantics, while strict "
            "predecessor search yields 7. Standard depth explains finish <= start; brief depth keeps the same "
            "witness and uncertainty in fewer words."
        ),
        "failure": (
            "If the input violates a strict-duration constraint, withdraw the alleged bug and repair the diagnostic. "
            "If the oracle also returns 7, inspect shared endpoint semantics before declaring two references authoritative."
        ),
        "completion": ["Explanation artifact", "valid receipt", "assumption/code links", "uncertainty",
                       "author actions"],
        "acceptance": ["C05", "C12"],
    },
    "COL-TEST": {
        "id": "collab/test/v1",
        "purpose": "Co-design discriminating tests.",
        "procedure": [
            "Retain the human original.",
            "Validate legality and expected answer independently.",
            "Map it to a defect family.",
            "Propose complementary boundaries with explicit purpose.",
            "Agree a bounded campaign under the existing grant and retain successes and limitations.",
        ],
        "prompt": (
            "What does this contributed test discriminate? Verify its expected answer, preserve attribution, then "
            "add only cases covering a different risk. Never manufacture coverage from case count."
        ),
        "example": (
            "Author supplies [(0,1,5),(1,2,7)] -> 12; retain it as the human touching-boundary case. The agent adds "
            "nested intervals to challenge weight choice and large rewards for accumulator width. The 1,554-case "
            "finite domain uses independent subset enumeration, not the DP as answer generator."
        ),
        "failure": (
            "Duplicate jobs remain labelled. A human expected value of 10 for the touching case is a claim to check, "
            "not an oracle. Invalid tests get a visible reason and an editable proposal, not silent deletion."
        ),
        "completion": ["contribution lineage", "validity receipt", "requirement-to-case matrix",
                       "oracle qualification", "completed/attempted counts"],
        "acceptance": ["C04", "C05"],
    },
    "COL-REPAIR": {
        "id": "collab/repair/v1",
        "purpose": "Review a diagnosis and a proposed change.",
        "procedure": [
            "Explain cause and minimum change.",
            "Show affected obligations.",
            "Allow edit, reject or an alternative.",
            "Validate the resulting patch hash.",
            "Commit only at the current revision/generation within grant, then rerun the witness and affected evidence.",
        ],
        "prompt": (
            "Present the concrete change and its tradeoff. Respect a reasonable rejected recommendation. Never "
            "broaden a patch to weaken the specification or claim approval for a different diff."
        ),
        "example": (
            "Propose replacing strict comparison with non-strict predecessor compatibility. Author chooses an "
            "upper_bound version rather than a custom loop. Preserve both proposal hashes, validate the selected "
            "prior-prefix search and run the same witness."
        ),
        "failure": (
            "Author changes endpoint semantics while the worker runs -> stale patch conflict, reconcile the new spec, "
            "never apply the old approval. Rejection leaves source unchanged and can return a diagnostic-only stage."
        ),
        "completion": ["decision/diff/receipt chain", "attribution", "current reruns", "residual risks"],
        "acceptance": ["C06", "C07", "C09"],
    },
    "COL-HANDOFF": {
        "id": "collab/handoff/v1",
        "purpose": "Delegate, return and resume work.",
        "procedure": [
            "Project the grant from the explicit instruction.",
            "Clarify only missing consequential scope.",
            "Work within the bounds.",
            "Return immediately on predicate, budget, unknown outcome or blocker.",
            "Summarise decisions, contributions, evidence freshness and next useful action; resume by reconciliation.",
        ],
        "prompt": (
            "Report what this stage established and what remains open. Credit human contributions, carry pending "
            "questions forward and distinguish a returned stage from a finished package. Do not ask again for a "
            "recorded current decision."
        ),
        "example": (
            "'Investigate greedy for at most 100 tiny cases; return a counterexample and explanation, do not edit "
            "solutions.' A valid weighted witness meets the typed first_valid_witness return condition without "
            "proceeding to DP implementation. A question or request to explain does not itself authorise edits."
        ),
        "failure": (
            "A provider timeout with unknown usage returns resumable incomplete status and a retained reservation; "
            "silence does not expand scope or approve delivery."
        ),
        "completion": ["delegation/grant", "terminal reason", "handoff", "linked resumption generation"],
        "acceptance": ["C08", "C10", "C11"],
    },
}

DOMAIN_PROCEDURES = {
    "domain/weighted-interval/v1": {
        "id": "domain/weighted-interval/v1",
        "purpose": "Investigate maximum-reward compatible interval selection.",
        "applicability": (
            "finite labelled intervals; start < finish; half-open occupancy; nonnegative integer reward; "
            "no travel/setup cost; no cardinality cap. Not applicable to preemption, capacity > 1, dependencies, "
            "or time-varying rewards."
        ),
        "steps": [
            "Normalise S1-S5: labelled jobs; half-open endpoints; each job at most once; reward sum; maximum value including empty set.",
            "Compare hypotheses. Earliest finish is correct for an unweighted cardinality objective; do not transfer its exchange argument.",
            "Witness [0,2):6, [2,4):6, [0,4):13: earliest finish yields 12, the long interval 13. This refutes that greedy rule, not all greedy methods.",
            "Sort by nondecreasing finish. p(i) is the last prior job with finish <= start_i. D[i] = max(D[i-1], reward_i + D[p(i)]), D[0] = 0, p(i)=0 if none. Do not substitute < for <=.",
            "Obligations: feasible schedules split on whether i is selected; selected i leaves compatible predecessors; optimising the prefix suffices; induction covers both branches; binary search finds that prefix; finite index order terminates.",
            "Map to code with a 64-bit accumulator, prior-finish prefix search, retained duplicate labels, initialised D[0] and one endpoint comparison in validator, oracle and editorial.",
            "Build the oracle by enumerating subsets and checking selected pairs directly. Do not copy the recurrence or predecessor search.",
            "Campaign the declared finite domain, then seeded structural cases, then maximum-size shapes.",
        ],
        "bounds": {
            "n": "1 <= n <= 200000",
            "start_finish": "0 <= start < finish <= 10^9",
            "reward": "1 <= reward <= 10^9",
            "sum": "<= 2*10^14 requires 64-bit accumulation",
            "complexity": "O(n log n) time after sorting, O(n) extra storage",
        },
        "failure_diagnostic": (
            "Touching jobs disagree: inspect p(i) and endpoint semantics before changing the recurrence. Only large "
            "rewards fail: inspect intermediate types and output parsing. Only equal finishes fail: compare stable "
            "identity/order and search bounds. Oracle and candidate agree but a hand case disagrees: audit shared semantics."
        ),
    }
}

RESOURCES = {
    "examples/touching": {
        "id": "examples/touching",
        "text": (
            "# Touching boundary\n\n"
            "Input:\n2\n0 1 5\n1 2 7\n\n"
            "Half-open compatibility: the two jobs do not overlap, so the optimum is 12.\n"
            "A strict predecessor test `finish < start` rejects the second job and returns 7.\n"
            "This is a legal positive-duration witness, not an invalid zero-duration case.\n"
        ),
    },
    "proof/prefix": {
        "id": "proof/prefix",
        "text": (
            "# Compatible prefix obligation\n\n"
            "For finish-sorted jobs, define p(i) as the last index j < i with finish_j <= start_i.\n"
            "If i is selected, any other selected job k < i that overlaps i is not feasible; the remaining selected "
            "jobs are exactly within the prefix p(i). Therefore the best reward for an optimal subset containing i "
            "is w_i + D[p(i)]. If i is omitted, D[i-1] bounds it. Both branches construct feasible subsets, so "
            "D[i] = max(D[i-1], w_i + D[p(i)]) by induction.\n\n"
            "Dependencies to challenge: positive-length intervals, finish sorting, half-open compatibility, and "
            "`<=` in the predecessor test. A closed-interval convention weakens the prefix property.\n"
        ),
    },
    "tests/subset-oracle": {
        "id": "tests/subset-oracle",
        "text": (
            "# Independent subset oracle\n\n"
            "For n <= 20 enumerate every labelled subset. For each feasible subset, sum rewards and keep the maximum. "
            "Feasibility checks every selected pair directly: half-open jobs conflict iff start_a < finish_b and "
            "start_b < finish_a.\n\n"
            "The oracle does not sort, search predecessors or reuse the DP recurrence. It shares only the endpoint "
            "assumption, so a shared endpoint error must be investigated rather than confirmed by agreement.\n"
            "Hand fixtures: empty subset -> 0; one job -> its reward; touching -> sum; nested -> larger of the two.\n"
        ),
    },
}

MAX_RETRIEVAL_TOKENS = 6000


@dataclass(frozen=True)
class ResourceRef:
    skill_id: str
    resource_id: str
    version: str
    sha256: str
    supported_domain: str
    license: str
    bytes: int
    approx_tokens: int
    tool_schema_version: int = 1
    section_keys: tuple[str, ...] = field(default_factory=tuple)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def manifest() -> list[dict]:
    entries: list[dict] = []
    for name, item in PROCEDURES.items():
        text = "\n".join(str(value) for value in item.values() if isinstance(value, (str, list)))
        entries.append({
            "id": item["id"], "skill": "collab", "name": name, "version": "v1",
            "sha256": _hash(text), "supportedDomain": "weighted-interval-v1",
            "license": "project-internal", "bytes": len(text.encode("utf-8")),
            "approxTokens": max(1, len(text) // 4), "toolSchemaVersion": 1,
        })
    for name, item in DOMAIN_PROCEDURES.items():
        text = "\n".join(str(value) for value in item.values())
        entries.append({
            "id": item["id"], "skill": "domain", "name": name, "version": "v1",
            "sha256": _hash(text), "supportedDomain": "weighted-interval-v1",
            "license": "project-internal", "bytes": len(text.encode("utf-8")),
            "approxTokens": max(1, len(text) // 4), "toolSchemaVersion": 1,
        })
    for name, item in RESOURCES.items():
        text = item["text"]
        entries.append({
            "id": item["id"], "skill": "resource", "name": name, "version": "v1",
            "sha256": _hash(text), "supportedDomain": "weighted-interval-v1",
            "license": "project-internal", "bytes": len(text.encode("utf-8")),
            "approxTokens": max(1, len(text) // 4), "toolSchemaVersion": 1,
        })
    return entries


def manifest_hash() -> str:
    return _hash("\n".join(sorted(f"{e['id']}:{e['sha256']}" for e in manifest())))


def lookup(procedure: str) -> dict | None:
    if procedure in PROCEDURES:
        return PROCEDURES[procedure]
    if procedure in DOMAIN_PROCEDURES:
        return DOMAIN_PROCEDURES[procedure]
    for key, item in PROCEDURES.items():
        if procedure.lower() == key.lower() or procedure == item["id"]:
            return item
    for key, item in DOMAIN_PROCEDURES.items():
        if procedure == key:
            return item
    return None


def read_skill_resource(skill_id: str, resource_id: str, section: str | None = None,
                        max_bytes: int = 12_000) -> dict:
    """Resolve only registered resources; never arbitrary path reads."""
    if max_bytes <= 0 or max_bytes > 64_000:
        raise ValueError("max_bytes must be within (0, 64000]")
    item = RESOURCES.get(resource_id)
    if item is None:
        return {"error": "resource_missing", "resourceId": resource_id, "skillId": skill_id}
    text = item["text"]
    if section:
        # A section is selected by its markdown heading; unknown sections are missing.
        blocks = re.split(r"\n(?=# )", text)
        matched = [b for b in blocks if b.splitlines()[0].lstrip("# ").strip().lower()
                   in (section.strip().lower(), section.strip().lower().replace("-", " "))]
        if not matched:
            return {"error": "resource_missing", "resourceId": resource_id, "section": section}
        text = matched[0]
    if len(text.encode("utf-8")) > max_bytes:
        text = text.encode("utf-8")[:max_bytes].decode("utf-8", "replace")
        return {"text": text, "truncated": True, "continuation": f"{resource_id}#beyond-{max_bytes}"}
    return {"text": text, "truncated": False}


def compose_selection(procedure: str, domain: str | None = "domain/weighted-interval/v1",
                      resource_ids: list[str] | None = None) -> dict:
    """One collaboration procedure + at most one domain procedure + <=2 resources."""
    selected = []
    proc = lookup(procedure)
    if proc is None:
        return {"error": "resource_missing", "procedure": procedure, "selected": []}
    selected.append({"id": proc["id"], "text": _flatten(proc)})
    if len(resource_ids or []) > 2:
        return {"error": "context_budget_exhausted",
                "detail": "at most two targeted resource sections",
                "selected": [p["id"] for p in selected]}
    if domain:
        dom = lookup(domain)
        if dom is None:
            return {"error": "resource_missing", "procedure": domain, "selected": selected}
        selected.append({"id": dom["id"], "text": _flatten(dom)})
    for rid in (resource_ids or [])[:2]:
        res = read_skill_resource("resource", rid)
        if "error" in res:
            return {"error": res["error"], "resourceId": rid, "selected": selected}
        selected.append({"id": rid, "text": res["text"]})
    total_tokens = sum(max(1, len(item["text"]) // 4) for item in selected)
    if total_tokens > MAX_RETRIEVAL_TOKENS:
        return {
            "error": "context_budget_exhausted",
            "selected": [item["id"] for item in selected],
            "approxTokens": total_tokens,
            "cap": MAX_RETRIEVAL_TOKENS,
        }
    return {"selected": selected, "approxTokens": total_tokens, "manifestHash": manifest_hash()}


def _flatten(item: dict) -> str:
    lines = []
    for key, value in item.items():
        if isinstance(value, (list, tuple)):
            lines.append(f"{key}: " + "; ".join(str(v) for v in value))
        elif isinstance(value, dict):
            lines.append(f"{key}: " + "; ".join(f"{k}={v}" for k, v in value.items()))
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)
