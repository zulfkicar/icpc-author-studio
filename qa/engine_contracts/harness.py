"""Shared deterministic harness for the V0-V3 acceptance suite.

Everything here uses temporary roots, a scripted fake model and (by default) a
simulated worker.  Real-worker/real-model qualification is never implied.
"""
from __future__ import annotations

import json
import pathlib
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "qa" / "engine_contracts" / "fixtures" / "candidates"

from engine.clock import ManualClock
from engine.demo import COMPOSE_DRAFT, FRAME_QUESTION, INTERPRET_DRAFT
from engine.model import FakeModelAdapter
from engine.service import EngineService
from engine.worker import FakeWorker


def plan(action: str, **args) -> dict:
    return {"kind": "ok", "data": {
        "action": action,
        "intent": args.pop("intent", action),
        "target_claim_ids": args.pop("target_claim_ids", []),
        "expected_observation": args.pop("expected_observation", ""),
        "args": args.pop("args", {}),
        "requested_budget": args.pop("requested_budget", {}),
        "on_failure": args.pop("on_failure", "advisory"),
    }}


def script(**overrides) -> dict:
    base = {
        "frame_goal": [FRAME_QUESTION],
        "plan": [],
        "collaboration.compose": [COMPOSE_DRAFT],
        "investigation.interpret": [INTERPRET_DRAFT],
        "investigation.design": [],
        "editing.draft": [],
        "review.challenge": [],
    }
    for key, value in overrides.items():
        base[key] = value
    return base


def _default_script() -> dict:
    return script()


class Harness:
    def __init__(self, script_dict: dict | None = None, *, worker=None,
                 clock: ManualClock | None = None, root: str | pathlib.Path | None = None,
                 model=None, script=None):
        self.root = pathlib.Path(root or tempfile.mkdtemp(prefix="engine-v0v3-"))
        self.clock = clock or ManualClock()
        self.worker = worker or FakeWorker()
        self.model = model or FakeModelAdapter(script=script_dict or script or _default_script())
        self.service = EngineService(
            self.root, clock=self.clock, model_adapter=self.model, worker=self.worker,
            fixture_dir=str(FIXTURES), clone_models=False,
        )

    def create(self, idea: str = "Help me develop profitable bookings; work with me, briefly.",
               seed: dict | None = None) -> str:
        created = self.service.create_run(workspace_id="test", idea=idea, seed=seed)
        return created["runId"]

    def pump(self, run_id: str, *, rounds: int = 24, steps: int = 120) -> dict:
        out = {"status": "unknown"}
        for _ in range(rounds):
            out = self.service.pump_sync(run_id, max_steps=steps)
            if out.get("status") in ("waiting", "idle", "done", "error", "step_limit", "locked"):
                return out
        return out

    def pump_until(self, run_id: str, predicate, *, rounds: int = 40, steps: int = 120) -> dict:
        out = {"status": "unknown"}
        for _ in range(rounds):
            out = self.service.pump_sync(run_id, max_steps=steps)
            store = self.service.store(run_id)
            if predicate(store.get_run(run_id), store):
                return out
            if out.get("status") in ("error", "step_limit", "locked"):
                return out
            if out.get("status") == "waiting" and store.pending_interaction(run_id) is None:
                # waiting for a worker receipt/deadline; give deferred settlement a chance
                continue
        return out

    def view(self, run_id: str) -> dict:
        return self.service.view(run_id)

    def store(self, run_id: str):
        return self.service.store(run_id)

    def respond(self, run_id: str, interaction: dict, kind: str, payload: dict,
                key: str = "resp-1") -> dict:
        generation = interaction.get("goalGeneration")
        if generation is None:
            generation = interaction.get("goal_generation")
        return self.service.submit_response(run_id, interaction["id"], {
            "clientRequestId": key,
            "kind": kind,
            "payload": payload,
            "expectedRevision": interaction.get("revision"),
            "expectedGoalGeneration": generation,
            "expectedProposalHash": interaction.get("proposalHash") or interaction.get("proposal_hash"),
        }, schedule=False)

    def answer_endpoint(self, run_id: str, option: str = "half_open", key: str = "resp-1") -> dict:
        decision = self.view(run_id)["pendingDecision"]
        assert decision is not None, "expected a pending endpoint decision"
        return self.respond(run_id, decision, "semantic_choice",
                            {"requirement_id": "endpoint_semantics", "option_id": option}, key=key)

    def settle(self, job_id: str) -> dict:
        return self.service.settle_worker(job_id)

    def close(self) -> None:
        self.service.close()


@pytest.fixture()
def harness():
    h = Harness()
    yield h
    h.close()
