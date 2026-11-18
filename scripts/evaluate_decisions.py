"""Evaluate the offline decision adapter against the versioned set.

Usage: python scripts/evaluate_decisions.py [--json OUT]
No provider call is made; the scripted demo adapter is measured only.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.decisions import ScriptedDecisionAdapter  # noqa: E402


def evaluate() -> dict:
    path = ROOT / "qa" / "engine_contracts" / "decision_eval.json"
    evaluation = json.loads(path.read_text(encoding="utf-8"))
    adapter = ScriptedDecisionAdapter()
    metrics = {
        "falseEffectAuthorization": 0,
        "falseSemanticCommitment": 0,
        "requestContributionConfusion": 0,
        "unnecessaryClarification": 0,
        "lostUsefulPositiveAction": 0,
        "decisionCalls": 0,
        "latency": "not measured for the scripted adapter",
        "usage": "not measured; scripted adapter reports no token usage",
        "cases": len(evaluation["cases"]),
        "replay": "one durable record per message id; replay covered by tests",
    }
    per_case = []
    for case in evaluation["cases"]:
        context = {"pendingQuestion": case.get("pendingQuestion"),
                   "decisions": case.get("decisions") or []}
        decision = adapter.call(case["text"], context).data
        metrics["decisionCalls"] += 1
        acts = decision["acts"]
        effect = [a for a in acts if a["kind"] == "effect_request"]
        semantic = [a for a in acts if a["kind"] == "semantic_assertion"
                    and a.get("semantic_option")]
        contributions = [a for a in acts if a["kind"] == "contribution"]
        if effect and not case.get("effectExpected"):
            metrics["falseEffectAuthorization"] += 1
        if semantic and semantic[0].get("semantic_option") != case.get("semanticOption"):
            metrics["falseSemanticCommitment"] += 1
        if contributions and case.get("contributionKind") not in (None, "any"):
            if contributions[0].get("contribution_kind") != case["contributionKind"]:
                metrics["requestContributionConfusion"] += 1
        if not acts and case.get("expectedAny"):
            metrics["unnecessaryClarification"] += 1
        for expected in case.get("expectedKinds") or []:
            if not any(a["kind"] == expected for a in acts):
                metrics["lostUsefulPositiveAction"] += 1
        per_case.append({"text": case["text"], "acts": [a["kind"] for a in acts],
                         "status": "ok"})
    return {"version": evaluation["version"], "adapter": adapter.identity,
            "qualification": "scripted demo adapter; no real-model evaluation",
            "metrics": metrics, "cases": per_case}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default=None)
    args = parser.parse_args()
    result = evaluate()
    text = json.dumps(result, indent=2, ensure_ascii=False)
    print(text)
    if args.json:
        pathlib.Path(args.json).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())