"""V0 contracts: oracle qualification, graph API pins, reducers, budgets."""
from __future__ import annotations

import json
import pathlib
import sqlite3

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from engine.budget import BudgetExhausted, ModelGateway
from engine.clock import ManualClock
from engine.demo import FRAME_QUESTION
from engine.domain import (
    FINITE_TYPES,
    Instance,
    InvalidInput,
    Job,
    dp_reference,
    finite_domain,
    oracle_subset,
    parse_instance,
    render_instance,
    witness_contained_pair,
    witness_duplicate_jobs,
    witness_large_reward,
    witness_two_touching,
    witness_weighted_greedy,
)
from engine.domain import candidates
from engine.graph_state import merge_evidence, validate_route
from engine.model import FakeModelAdapter
from engine.procedures import compose_selection, manifest, manifest_hash, read_skill_resource
from engine.prompts import bundle_hash, validate_bundle
from engine.schemas import PlanV1
from engine.stage import delivery_supported, refusal_payload
from engine.store import ApplicationStore
from engine.worker import FakeWorker


# ---------------------------------------------------------------- oracle
def test_oracle_hand_fixtures():
    assert oracle_subset(witness_weighted_greedy())["value"] == 13
    assert oracle_subset(witness_two_touching())["value"] == 12
    assert oracle_subset(witness_contained_pair())["value"] == 9
    assert oracle_subset(witness_duplicate_jobs())["value"] == 7
    assert oracle_subset(witness_large_reward())["value"] == 3 * 10 ** 9
    single = Instance((Job(0, 5, 42, 0),))
    assert oracle_subset(single)["value"] == 42


def test_oracle_is_independent_of_dp_recurrence():
    domain = finite_domain(lengths=(1, 2, 3, 4))
    assert len(domain) == 1554
    for instance in domain:
        assert oracle_subset(instance)["value"] == dp_reference(instance)


def test_oracle_reports_enumeration_count_and_does_not_use_candidate():
    result = oracle_subset(witness_weighted_greedy())
    assert result["enumerations"] == 2 ** 3
    assert result["producer"] == "subset-enumeration-v1"
    assert "dp" not in json.dumps(result)


def test_oracle_semantics_share_only_the_endpoint_assumption():
    instance = witness_two_touching()
    assert oracle_subset(instance, semantics="half_open")["value"] == 12
    assert oracle_subset(instance, semantics="closed")["value"] == 7


def test_greedy_is_refuted_only_on_weighted_witness():
    assert candidates.earliest_finish_greedy(witness_weighted_greedy()) == 12
    assert oracle_subset(witness_weighted_greedy())["value"] == 13
    # Correct for the unweighted-cardinality reading; the claim, not the method,
    # is what the witness refutes.
    assert candidates.earliest_finish_greedy(Instance((Job(0, 1, 1, 0), Job(1, 2, 1, 1)))) == 2


def test_correct_alternate_implementation_survives():
    for instance in finite_domain(lengths=(1, 2, 3)):
        assert candidates.sweep_line_correct(instance) == oracle_subset(instance)["value"]
        assert candidates.dp_correct(instance) == oracle_subset(instance)["value"]


def test_actual_dp_base_error_is_a_defect_distinct_from_empty_choice():
    bad = [i for i in finite_domain(lengths=(1, 2, 3))
           if candidates.dp_base_error(i) != oracle_subset(i)["value"]]
    assert bad, "the base/index defect must be observable on the finite domain"
    # A candidate that never explicitly selects the empty subset is not wrong
    # under n>=1 and strictly positive rewards: the optimum is nonempty.
    for instance in finite_domain(lengths=(1, 2, 3)):
        assert oracle_subset(instance)["value"] > 0


def test_fixture_manifest_matches_the_independent_oracle():
    manifest = json.loads((pathlib.Path(__file__).parent / "fixtures" / "instances.json")
                          .read_text(encoding="utf-8"))
    for entry in manifest["instances"]:
        instance = Instance(tuple(Job(s, f, r, i)
                                  for i, (s, f, r) in enumerate(entry["jobs"])))
        assert oracle_subset(instance)["value"] == entry["expected"], entry["name"]
        if "greedyEarliestFinish" in entry:
            assert candidates.earliest_finish_greedy(instance) == entry["greedyEarliestFinish"]
    controls = {c["name"]: c for c in manifest["negativeControls"]}
    with pytest.raises(InvalidInput):
        parse_instance(controls["zero_duration"]["input"])
    with pytest.raises(InvalidInput):
        parse_instance(controls["n_zero"]["input"])
    assert controls["omits_empty_choice_label"]["expected"] == "invalid_defect_label"
    assert controls["dp_base_error"]["expected"] == "defect"


def test_validator_rejects_invalid_inputs_and_negative_controls():
    with pytest.raises(InvalidInput):
        parse_instance("0\n")
    with pytest.raises(InvalidInput):
        parse_instance("1\n0 0 5\n")  # zero duration is outside the profile
    with pytest.raises(InvalidInput):
        parse_instance("1\n5 4 5\n")
    with pytest.raises(InvalidInput):
        parse_instance("1\n0 10 0\n")  # positive reward required
    with pytest.raises(InvalidInput):
        parse_instance("2\n0 1 1\n")
    with pytest.raises(InvalidInput):
        parse_instance("1\n0 1 1 extra\n")
    valid = parse_instance(render_instance(witness_two_touching()))
    assert valid.n == 2


def test_duplicate_jobs_are_labelled_not_deduplicated():
    instance = witness_duplicate_jobs()
    assert instance.n == 3
    assert len({job.label for job in instance.jobs}) == 3
    assert oracle_subset(instance)["value"] == 7


# ---------------------------------------------------------------- framework pins
def test_installed_graph_apis_support_single_router_and_interrupt(tmp_path):
    from typing import TypedDict

    class S(TypedDict, total=False):
        n: int
        route: str
        answer: str
        done: bool

    calls = {"wait": 0}

    def start(state):
        return {"n": state.get("n", 0) + 1, "route": "wait"}

    def wait(state):
        calls["wait"] += 1
        value = interrupt({"wait": "human", "n": state["n"]})
        return {"answer": value.get("answer")}

    def done(state):
        return {"done": True}

    builder = StateGraph(S)
    builder.add_node("start", start)
    builder.add_node("wait", wait)
    builder.add_node("done", done)
    builder.add_edge(START, "start")
    builder.add_conditional_edges("start", lambda s: s["route"], {"wait": "wait"})
    builder.add_edge("wait", "done")
    builder.add_edge("done", END)
    conn = sqlite3.connect(tmp_path / "graph.db", check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    graph = builder.compile(checkpointer=saver)
    config = {"configurable": {"thread_id": "t1"}}
    first = graph.invoke({"n": 0}, config)
    snapshot = graph.get_state(config)
    assert snapshot.next == ("wait",)
    assert first["__interrupt__"][0].value["wait"] == "human"
    second = graph.invoke(Command(resume={"answer": "ok"}), config)
    assert second["answer"] == "ok"
    assert second["done"] is True
    # Node re-execution on resume is expected; no non-idempotent effect was
    # written before interrupt in production nodes.
    assert calls["wait"] == 2


def test_assembled_parent_has_one_router_per_transition():
    from engine.graph import Runtime, build_parent

    store = ApplicationStore(pathlib.Path(tempfile_dir()) / "graphcheck")
    adapter = FakeModelAdapter(script={"plan": []})
    runtime = Runtime(store=store, inputs=__import__("engine.input_service", fromlist=["InputService"]).InputService(store),
                      gateway=ModelGateway(store, adapter), worker=FakeWorker())
    graph = build_parent(runtime, None)
    nodes = set(graph.get_graph().nodes)
    for name in ("reconcile", "frame_goal", "select_action", "admit_action", "assess",
                 "await_human", "await_operation", "handoff", "collaboration",
                 "investigation", "editing", "review"):
        assert name in nodes
    with pytest.raises(ValueError):
        validate_route("investigation", "await_operation")
    with pytest.raises(ValueError):
        validate_route("assess", "investigation")


def tempfile_dir() -> str:
    import tempfile

    return tempfile.mkdtemp(prefix="engine-v0-")


def test_evidence_reducer_rejects_conflicting_same_id_payloads():
    merged = merge_evidence({"ev-1": {"hash": "a"}}, {"ev-2": {"hash": "b"}})
    assert set(merged) == {"ev-1", "ev-2"}
    with pytest.raises(ValueError):
        merge_evidence({"ev-1": {"hash": "a"}}, {"ev-1": {"hash": "b"}})


def test_prompt_and_skill_bundles_validate():
    bundle = validate_bundle()
    assert bundle["validated"] is True
    assert bundle["hash"] == bundle_hash()
    entries = manifest()
    assert len(entries) >= 10
    assert manifest_hash()
    for entry in entries:
        assert entry["sha256"] and entry["bytes"] > 0 and entry["toolSchemaVersion"] == 1


def test_procedure_retrieval_is_bounded_and_missing_resources_fail():
    selection = compose_selection("COL-EXPLAIN", resource_ids=["examples/touching", "proof/prefix"])
    assert "error" not in selection
    assert selection["approxTokens"] <= 6000
    missing = read_skill_resource("collab", "does/not/exist")
    assert missing["error"] == "resource_missing"
    too_many = compose_selection("COL-EXPLAIN", resource_ids=["examples/touching", "proof/prefix",
                                                             "tests/subset-oracle"])
    assert too_many["error"] == "context_budget_exhausted"


# ---------------------------------------------------------------- budget
def test_budget_three_total_attempts_and_unique_settlement(tmp_path):
    store = ApplicationStore(tmp_path / "budget")
    run = store.create_run("w", "idea")
    reservation = store.reserve_action(run["run_id"], action_id="a1", attempts_limit=3)
    for index in (1, 2, 3):
        store.record_attempt(reservation["id"], kind="model", outcome="error", attempt_index=index)
    with pytest.raises(Exception):
        store.record_attempt(reservation["id"], kind="model", outcome="error", attempt_index=4)
    assert store.get_budget(run["run_id"])["model_attempts_used"] == 3
    # Settlement is unique per reservation.
    store.settle_reservation(reservation["id"], "exhausted")
    store.settle_reservation(reservation["id"], "exhausted")
    settled = json.loads(store.get_budget(run["run_id"])["settled_json"])
    assert settled == {reservation["id"]: "exhausted"}


def test_gateway_transient_then_malformed_then_error_is_exactly_three_attempts(tmp_path):
    store = ApplicationStore(tmp_path / "gateway")
    run = store.create_run("w", "idea")
    reservation = store.reserve_action(run["run_id"], action_id="gateway", attempts_limit=3)
    adapter = FakeModelAdapter(script=[
        {"kind": "transport_error", "error": "disconnect"},
        {"kind": "malformed", "error": "not json"},
        {"kind": "transport_error", "error": "429"},
    ])
    gateway = ModelGateway(store, adapter)
    outcome = gateway.call(run_id=run["run_id"], reservation_id=reservation["id"], node="plan",
                           prompt="x", context={}, validate=PlanV1.model_validate)
    assert outcome.ok is False
    assert outcome.attempts == 3
    assert len(store.attempts_for(reservation["id"])) == 3
    assert store.get_budget(run["run_id"])["model_attempts_used"] == 3
    assert all(attempt["usage"].get("unknown") for attempt in store.attempts_for(reservation["id"]))
    with pytest.raises(BudgetExhausted):
        gateway.call(run_id=run["run_id"], reservation_id=reservation["id"], node="plan",
                     prompt="x", context={}, validate=PlanV1.model_validate)


def test_stage_schema_is_not_delivery_schema():
    assert delivery_supported() is False
    refusal = refusal_payload("export")
    assert refusal["supported"] is False
    assert refusal["effectsApplied"] == 0
