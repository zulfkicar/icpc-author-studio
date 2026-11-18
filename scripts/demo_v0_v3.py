"""Reproducible V0-V3 demonstration: fake model + fake worker.

Usage: python scripts/demo_v0_v3.py [--json]

The demo is explicitly not a real-model or real-worker qualification.  It shows
model-directed routing (a scripted plan selects investigation, then explanation)
and a human contribution preserved through the stage.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

from engine.demo import COMPOSE_DRAFT, FRAME_QUESTION, INTERPRET_DRAFT
from engine.model import FakeModelAdapter
from engine.service import EngineService
from engine.worker import FakeWorker

FIXTURES = ROOT / "qa" / "engine_contracts" / "fixtures" / "candidates"


def plan(action: str, **fields) -> dict:
    return {"kind": "ok", "data": {
        "action": action,
        "intent": fields.pop("intent", action),
        "target_claim_ids": fields.pop("target_claim_ids", []),
        "expected_observation": fields.pop("expected_observation", ""),
        "args": fields.pop("args", {}),
        "requested_budget": fields.pop("requested_budget", {}),
        "on_failure": "advisory",
    }}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    script = {
        "frame_goal": [FRAME_QUESTION],
        "plan": [
            plan("investigate", args={
                "candidate_ref": "fixture:earliest_finish_greedy", "claim_id": "H1",
                "domain": {"kind": "witness", "name": "weighted_greedy"}},
                requested_budget={"cases": 1}),
            plan("collaborate", args={"procedure": "COL-EXPLAIN",
                                      "question": "Why does earliest finish fail?"}),
            plan("finish"),
        ],
        "collaboration.compose": [COMPOSE_DRAFT],
        "investigation.interpret": [INTERPRET_DRAFT],
        "investigation.design": [],
        "editing.draft": [],
        "review.challenge": [],
    }
    root = pathlib.Path(tempfile.mkdtemp(prefix="engine-demo-"))
    service = EngineService(root, model_adapter=FakeModelAdapter(script=script),
                            worker=FakeWorker(), fixture_dir=str(FIXTURES))
    created = service.create_run(
        workspace_id="demo", idea="Help me develop profitable bookings; work with me, briefly.")
    run_id = created["runId"]
    service.pump_sync(run_id, max_steps=120)
    decision = service.view(run_id)["pendingDecision"]
    assert decision, "expected one endpoint decision card"

    # Human contribution lands as an immutable, attributed original.
    service.create_contribution(run_id, {
        "contributionKind": "lemma",
        "content": "Lemma: any schedule omitting job i lies in prefix i-1.",
        "attribution": "author",
    })
    service.submit_response(run_id, decision["id"], {
        "clientRequestId": "demo-response-1",
        "kind": "semantic_choice",
        "payload": {"requirement_id": "endpoint_semantics", "option_id": "half_open"},
        "expectedRevision": decision["revision"],
        "expectedGoalGeneration": decision["goalGeneration"],
        "expectedProposalHash": decision["proposalHash"],
    }, schedule=False)
    service.pump_sync(run_id, max_steps=120)

    store = service.store(run_id)
    view = service.view(run_id)
    evidence = store.list_evidence(run_id)
    explanation = store.current_explanation(run_id)
    handoff = store.latest_handoff(run_id)
    result = {
        "disclosure": service.capabilities(run_id)["disclosure"],
        "runId": run_id,
        "status": view["status"],
        "question": decision["prompt"],
        "choice": "half-open",
        "contributions": [{ "id": c["id"], "kind": c["kind"],
                            "attribution": c["attribution"],
                            "blobHash": c["original_blob_hash"]}
                          for c in store.list_contributions(run_id)],
        "evidence": [{"id": e["id"], "classification": e["classification"],
                      "freshness": e["freshness"], "outcome": e["outcome"]}
                     for e in evidence],
        "explanation": explanation["short_answer"] if explanation else None,
        "openQuestions": handoff["open_questions"] if handoff else [],
        "handoffOutcome": handoff["outcome"] if handoff else None,
        "eventTypes": [e["type"] for e in store.events_after(run_id, 0, 200)],
        "deliverySupported": view["delivery"]["supported"],
        "restoreMutationsSupported": view["restoreMutations"]["supported"],
    }
    assert result["evidence"] and result["evidence"][0]["classification"] == "counterexample"
    assert result["explanation"] and "13" in result["explanation"] and "12" in result["explanation"]
    assert result["contributions"] and result["contributions"][0]["attribution"] == "author"
    assert result["handoffOutcome"] == "awaiting_author"
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("V0-V3 demo (FAKE model + FAKE worker)")
        print(result["disclosure"])
        print(f"\n1. Question: {result['question']}")
        print(f"2. Author choice: {result['choice']}")
        print(f"3. Evidence: {result['evidence']}")
        print(f"4. Explanation: {result['explanation']}")
        print(f"5. Handoff: {result['handoffOutcome']} | open: {result['openQuestions']}")
        print(f"6. Delivery supported: {result['deliverySupported']} | "
              f"restore mutations: {result['restoreMutationsSupported']}")
        print(f"7. Human contribution retained: {result['contributions'][0]['id']}")
    service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
