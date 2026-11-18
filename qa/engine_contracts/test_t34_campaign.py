"""T34 production graph and HTTP contract, with an opt-in real Isolate run."""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from engine.domain import Instance, Job, parse_instance
from engine.domain import differential as campaign
from engine.model import FakeModelAdapter
from engine.schemas import sha256_text
from engine.worker import FakeWorker, IsolateWorker
from engine import worker as worker_module
from qa.engine_contracts.harness import FIXTURES, Harness, plan, script
from qa.engine_contracts.test_api_boundary import api, wait_for


IDEA = "Maximize total reward for nonoverlapping half-open weighted intervals."
BUDGET = {"cases": 6, "wall_ms": 15_000, "oracle_subsets": 256}
HELD_OUT = 2_951_404_661


def spec(*, seed=HELD_OUT, family="mixed", target=6):
    return {"kind": "weighted_campaign", "mode": "seeded", "seed": seed,
            "family": family, "target_cases": target}


def draft(candidate="dp_correct", domain=None, budget=None):
    return plan("investigate", args={"candidate_ref": f"fixture:{candidate}", "claim_id": "H1",
                                    "domain": domain if domain is not None else spec()},
                requested_budget=budget if budget is not None else BUDGET)


def manifest(domain=None, budget=None, semantics="half_open"):
    return campaign.prepare_campaign(domain if domain is not None else spec(),
                                     budget if budget is not None else BUDGET, semantics=semantics,
                                     case_ceiling=50, wall_ceiling=60_000)


def test_held_out_inputs_have_independently_derived_answers_and_replay():
    half = manifest()
    closed = manifest(semantics="closed")
    assert half == manifest()
    assert [x["inputHash"] for x in half["cases"]] != [x["inputHash"] for x in manifest(spec(seed=713_236))["cases"]]
    assert len({case["inputHash"] for case in half["cases"]}) == 6
    for a, b in zip(half["cases"], closed["cases"], strict=True):
        assert a["input"] == b["input"] and a["inputHash"] == sha256_text(a["input"])
        rewards = sorted(job.reward for job in parse_instance(a["input"]).jobs)
        if a["family"] == "touching":
            r = rewards[1]
            expected = (3 * r + 2, 2 * r + 4)
        elif a["family"] == "nested_duplicates":
            r = rewards[0]
            expected = (3 * r + 4, 2 * r + 7)
        else:
            expected = (sum(rewards[:4]),) * 2
            assert expected[0] > 2**31 - 1
        assert (a["expected"], b["expected"]) == expected


@pytest.mark.parametrize("fault,expected", [("generator", "generator_invalid"), ("oracle", "oracle_invalid"),
                                            ("budget", "budget_exhausted"), ("schema", "invalid_campaign")])
def test_graph_distinguishes_invalid_inputs_and_oracle_from_exhaustion(tmp_path, monkeypatch, fault, expected):
    limits = dict(BUDGET)
    if fault == "generator":
        monkeypatch.setattr(campaign, "seeded_case", lambda *_: Instance((Job(3, 3, 1, 0),)))
    elif fault == "oracle":
        original = campaign.oracle_subset
        # A feasible, complete receipt can still encode a shared endpoint bug.
        monkeypatch.setattr(campaign, "oracle_subset",
                            lambda instance, **_: {**original(instance, semantics="closed"), "semantics": "half_open"})
    elif fault == "budget":
        limits["oracle_subsets"] = 19
    else:
        limits["cases"] = True
    h = Harness(script(plan=[draft(budget=limits)]), root=tmp_path)
    try:
        run = h.create(IDEA)
        h.pump(run)
        assert not h.worker.jobs
        assert h.store(run).get_budget(run)["cases_used"] == 0
        assert h.store(run).get_budget(run)["wall_ms_used"] == 0
        assert h.store(run).get_run(run)["stop_reason"] == expected
    finally:
        h.close()


@pytest.mark.parametrize("limited", ["cases", "oracle_subsets", None])
def test_compiled_graph_reports_bounded_scope_and_holds_no_retry_budget(tmp_path, limited):
    domain = {"kind": "weighted_campaign", "mode": "exhaustive", "seed": 0, "lengths": [1, 2]}
    limits = {**BUDGET, "cases": 50}
    if limited:
        limits[limited] = {"cases": 3, "oracle_subsets": 26}[limited]
    h = Harness(script(plan=[draft("sweep_line_correct", domain, limits)]), root=tmp_path)
    try:
        run = h.create(IDEA)
        h.pump(run)
        store = h.store(run)
        evidence, = store.list_evidence(run)
        receipt = h.service.campaign_receipt(run, evidence["id"])
        report = receipt["report"]
        assert report["declared"] == 42
        expected = {"cases": (3, "case_budget"), "oracle_subsets": (3, "oracle_budget"), None: (42, "domain_exhausted")}
        assert (report["completed"], report["termination"]) == expected[limited]
        assert report["complete"] is (limited is None)
        assert report["classification"] == ("agreement" if limited is None else "budget_exhausted")
        assert store.get_budget(run)["cases_used"] == report["selected"]
        assert store.get_budget(run)["wall_ms_used"] == limits["wall_ms"]
        assert all(set(case) == {"case_id", "input"} for case in h.worker.jobs[0]["cases"])
        assert not any(call["node"] == "investigation.interpret" for call in h.model.calls)
        assert len(h.worker.jobs) == 1
    finally:
        h.close()


def test_worker_protocol_reorders_exact_ids_and_rejects_duplicates_and_invalid_outputs():
    inputs = manifest()
    rows = [{"case_id": row["case_id"], "exit": 0, "status": "ok", "output": str(row["expected"])}
            for row in inputs["cases"]]
    result = campaign.evaluate_receipt(inputs, {"status": "completed", "cases": rows[::-1]})
    assert result["termination"] == "sample_exhausted" and result["complete"]
    for bad in ([rows[0], rows[0]], [{**rows[0], "case_id": "outside"}]):
        value = campaign.evaluate_receipt(inputs, {"status": "completed", "cases": bad})
        assert value["classification"] == "worker_protocol_error" and value["firstMismatch"] is None
    for bad_output in ("2 3", "3.2", "٣", "7" * 25):
        value = campaign.evaluate_receipt(inputs, {"status": "completed", "cases": [{**rows[0], "output": bad_output}]})
        assert value["classification"] == "invalid_output" and not value["complete"]


@pytest.mark.parametrize("candidate,rule,classification", [("dp_strict", "half_open", "counterexample"),
                                                           ("dp_strict", "closed", "agreement"),
                                                           ("sweep_line_correct", "half_open", "agreement")])
@pytest.mark.parametrize("execution", ["simulated", "isolate"])
def test_chat_to_campaign_receipt_over_http(api, monkeypatch, candidate, rule, classification, execution):
    service = api["service"]
    if execution == "isolate":
        url = os.environ.get("AUTHOR_AGENT_T34_TEST_ISOLATE_URL")
        if not url:
            pytest.skip("set AUTHOR_AGENT_T34_TEST_ISOLATE_URL for the compiled C++ check")
        monkeypatch.setenv("AUTHOR_AGENT_ISOLATE_URL", url)
        service.base_worker = IsolateWorker()
    else:
        service.base_worker = FakeWorker()
    model = service.model_factory = FakeModelAdapter(script=script(plan=[plan("finish"), plan("finish")]))
    service.clone_models = False
    call = api["call"]
    status, started = call("/api/engine/chat", "POST", {
        "message": "Help me maximize the total reward of a set of nonoverlapping weighted bookings.",
        "clientRequestId": "start-t34",
    })
    assert status == 201
    run = started["runId"]
    path = f"/api/engine/runs/{run}"
    waiting = wait_for(call, run, lambda v: v.get("pendingDecision"))
    assert waiting["pendingDecision"]
    answer = "Use half-open intervals. Touching is allowed." if rule == "half_open" else "Use closed intervals. Touching is forbidden."
    assert call(path + "/messages", "POST", {"message": answer, "clientRequestId": "rule-t34"})[0] == 200
    wait_for(call, run, lambda v: v["status"] == "awaiting_author" and not v.get("pendingDecision"))
    source = (FIXTURES / f"{candidate}.cpp").read_text(encoding="utf-8")
    assert call(path + "/messages", "POST", {"message": f"```cpp\n{source}```", "clientRequestId": "source-t34"})[0] == 200
    wait_for(call, run, lambda v: v["status"] == "awaiting_author" and any(a["kind"] == "solution" for a in v["artifacts"]))
    contribution, = [item for item in service.store(run).list_contributions(run) if item["kind"] == "code"]
    proposal = draft(candidate, spec(target=3))
    proposal["data"]["args"]["candidate_ref"] = contribution["id"]
    model._script["plan"] = [proposal]
    request = {"message": f"Run a weighted scheduling campaign with seed {HELD_OUT} against my C++ solution.",
               "clientRequestId": "campaign-t34"}
    assert call(path + "/messages", "POST", request)[0] == 200
    view = wait_for(call, run, lambda v: any(m["kind"] == "campaign" for m in v.get("chatMessages", [])))
    message, = [m for m in view["chatMessages"] if m["kind"] == "campaign"]
    report_path = f"{path}/campaigns/{message['dedupe_key'].split(':')[1]}"
    status, receipt = call(report_path)
    assert status == 200 and receipt["freshness"] == "current"
    assert ("isolate-client" in receipt["workerIdentity"]) is (execution == "isolate")
    assert receipt["manifest"]["spec"]["seed"] == HELD_OUT
    assert receipt["manifest"]["semantics"] == rule
    report = receipt["report"]
    assert report["candidateRef"] == f"contribution:{contribution['id']}"
    assert report["completed"] == report["declared"] == 3
    assert report["classification"] == classification
    if classification == "counterexample":
        witness = report["firstMismatch"]
        assert witness["family"] == "touching" and witness["actual"] < witness["expected"]
        assert witness["inputHash"] == sha256_text(witness["input"])
        assert any("independent optimum" in m["text"] for m in view["chatMessages"] if m["kind"] == "finding")
        status, studio = call(path + "/view?studio=1")
        assert status == 200
        card, = studio["evidenceCards"].values()
        assert card["input"] == witness["input"] and card["sourceHash"] == receipt["report"]["candidateHash"]
    else:
        assert report["firstMismatch"] is None and report["termination"] == "sample_exhausted"
    assert call(report_path) == (200, receipt)
    assert call(path + "/messages", "POST", request)[0] == 200
    assert call(f"{path}/campaigns/ev-unknown")[0] == 404
    assert len(service.store(run).list_operations(run)) == 1


@pytest.mark.parametrize("ending", ["resumed", "deadline", "steered"])
def test_pending_campaign_preserves_budgets_and_fences_late_results(tmp_path, ending):
    worker = FakeWorker(deferred=True)
    h = Harness(script(plan=[draft("dp_strict"), plan("finish")]), worker=worker, root=tmp_path)
    try:
        run = h.create(IDEA)
        h.pump(run)
        store = h.store(run)
        operation, = store.list_operations(run)
        assert operation["status"] == "pending"
        if ending == "deadline":
            h.clock.advance(16)
            assert "deadline" in h.service.settle_worker(operation["job_id"], schedule=False)["error"]
        elif ending == "steered":
            h.service.submit_input(run, {"kind": "steer", "text": "I meant closed intervals.",
                                        "clientRequestId": "closed-after-dispatch"}, schedule=False)
            assert h.service.settle_worker(operation["job_id"], schedule=False)["settled"]
        else:
            assert h.service.settle_worker(operation["job_id"], schedule=False)["settled"]
        h.pump(run)
        current = [item for item in store.list_evidence(run) if item["freshness"] == "current"]
        if ending == "resumed":
            assert len(current) == 1 and current[0]["classification"] == "counterexample"
            assert "terminal" in h.service.settle_worker(operation["job_id"], schedule=False)["error"]
        else:
            assert not current and not store.list_findings(run)
        if ending == "deadline":
            assert store.get_operation(operation["operation_id"])["classification"] == "worker_deadline"
        assert len(worker.jobs) == 1
        assert store.get_budget(run)["wall_ms_used"] == BUDGET["wall_ms"]
    finally:
        h.close()


def test_isolate_adapter_stops_sending_cases_on_batch_wall_limit(monkeypatch):
    import isolate_client

    sent = []
    moments = iter([50.0, 50.1, 51.1])
    monkeypatch.setenv("AUTHOR_AGENT_ISOLATE_URL", "http://local-isolate")
    monkeypatch.setattr(worker_module, "time", SimpleNamespace(monotonic=lambda: next(moments)))

    def run(_source, _language, input_text, **limits):
        sent.append((input_text, limits))
        return {"status": "OK", "exit": 0, "stdout": "1"}

    monkeypatch.setattr(isolate_client, "run", run)
    inputs = manifest()
    result = IsolateWorker().submit({"campaign": "manifest", "candidate": {"source": "fixture"},
        "cases": [{"case_id": c["case_id"], "input": c["input"]} for c in inputs["cases"]],
        "budget": {"wall_ms": 1000, "output_bytes": 4096}})
    assert len(sent) == 1 and sent[0][1]["request_timeout"] == pytest.approx(0.9)
    assert result["status"] == "incomplete" and result["truncation"]["reason"] == "deadline"


def test_run_wall_budget_is_shared_across_distinct_campaigns(tmp_path):
    actions = [draft(domain=spec(seed=11, target=1)) for _ in range(3)]
    h = Harness(script(plan=actions), root=tmp_path)
    h.service.default_budget_limits = {"wall_ms_limit": 20_000}
    try:
        run = h.create(IDEA)
        h.pump(run)
        for request in ("Run the next weighted campaign.", "Run a third weighted campaign."):
            h.service.submit_input(run, {"kind": "steer", "text": request, "clientRequestId": request}, schedule=False)
            h.pump(run)
        assert [job["budget"]["wall_ms"] for job in h.worker.jobs] == [15_000, 5_000]
        assert h.worker.jobs[0]["cases"] == h.worker.jobs[1]["cases"]
        assert h.store(run).get_budget(run)["wall_ms_used"] == 20_000
        assert h.store(run).get_run(run)["stop_reason"] == "budget_exhausted"
    finally:
        h.close()
