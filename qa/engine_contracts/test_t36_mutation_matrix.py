"""T36 from chat campaign through control, mutant execution and durable UI projection."""
from __future__ import annotations

import os
import socket
import subprocess

import pytest

from engine.model import FakeModelAdapter
from engine.worker import FakeWorker, IsolateWorker
from qa.engine_contracts.harness import FIXTURES, plan, script
from qa.engine_contracts.test_api_boundary import api, wait_for
from qa.engine_contracts.test_t34_campaign import HELD_OUT, IDEA, draft, spec


def start_campaign(api, worker, *, samples=3, extras=(), rule="half_open"):
    service, call = api["service"], api["call"]
    service.base_worker = worker
    proposal = draft("dp_strict" if rule == "half_open" else "dp_correct", spec(target=samples))
    model = service.model_factory = FakeModelAdapter(script=script(plan=[plan("finish")] if extras else [proposal]))
    service.clone_models = False
    idea = IDEA if rule == "half_open" else IDEA.replace("half-open", "closed")
    status, response = call("/api/engine/chat", "POST", {"message": idea, "clientRequestId": "t36-start"})
    assert status == 201
    run = response["runId"]
    path = f"/api/engine/runs/{run}"
    if rule == "closed":
        wait_for(call, run, lambda v: v.get("pendingDecision"))
        status, response = call(path + "/messages", "POST", {"message": "Use closed intervals. Touching is forbidden.",
                                                           "clientRequestId": "t36-closed-rule"})
        assert status == 200, response
        wait_for(call, run, lambda v: not v.get("pendingDecision"))
    for i, source in enumerate(extras):
        model._script["plan"] = [plan("finish")]
        status, response = call(path + "/messages", "POST", {"message": f"```cpp\n{source}\n```",
                                                           "clientRequestId": f"t36-candidate-{i}"})
        assert status == 200, response
        wait_for(call, run, lambda v: len([a for a in v["artifacts"] if a["kind"] == "solution"]) == i + 1)
    if extras:
        model._script["plan"] = [proposal]
        status, response = call(path + "/messages", "POST", {"message": f"Run a weighted scheduling campaign with seed {HELD_OUT}.",
                                                           "clientRequestId": "t36-campaign"})
        assert status == 200, response
    view = wait_for(call, run, lambda v: any(m["kind"] == "campaign" for m in v["chatMessages"]))
    campaign = next(m["dedupe_key"].split(":")[1] for m in view["chatMessages"] if m["kind"] == "campaign")
    assert campaign in call(path + "/view?studio=1")[1]["mutationCampaigns"]
    authored = [a for a in view["artifacts"] if a["kind"] == "solution"]
    return run, path, campaign, authored


@pytest.mark.parametrize("execution", ["simulated", "isolate"])
@pytest.mark.parametrize("rule", ["half_open", "closed"])
def test_http_matrix_distinguishes_kills_compile_errors_and_correct_survivor(api, monkeypatch, execution, rule):
    if execution == "isolate":
        url = os.environ.get("AUTHOR_AGENT_T36_TEST_ISOLATE_URL")
        if not url:
            pytest.skip("set AUTHOR_AGENT_T36_TEST_ISOLATE_URL for compiled execution")
        monkeypatch.setenv("AUTHOR_AGENT_ISOLATE_URL", url)
        worker = IsolateWorker()
    else:
        worker = FakeWorker()
    correct_fixture = "sweep_line_correct.cpp" if rule == "half_open" else "dp_strict.cpp"
    correct = (FIXTURES / correct_fixture).read_text(encoding="utf-8")
    invalid = "// fake-behavior: compile_error\n#include <iostream>\nint main( { std::cout << 1; }"
    run, path, campaign, authored = start_campaign(api, worker, extras=(invalid, correct), rule=rule)
    call, store = api["call"], api["service"].store(run)
    source_url = f"{path}/campaigns/{campaign}"
    original = call(source_url)
    url = f"{path}/mutation-matrices/{campaign}"
    request = {"clientRequestId": "t36-full", "mutantRefs": [item["id"] for item in authored]}
    status, result = call(url, "POST", request)
    assert status == 200, result
    assert result["freshness"] == "current"
    report = result["report"]
    assert report["semantics"] == rule and report["controlPassed"] and report["qualifiedTests"] == 3
    assert report["tests"] == original[1]["manifest"]["cases"]
    columns = {col["id"]: col for col in report["columns"]}
    assert columns["control"]["status"] == "control_passed" and columns["control"]["killedBy"] == []
    assert columns["endpoint"]["killedBy"] == ["case-00000", "case-00001"]
    assert columns["narrow"]["killedBy"] == ["case-00002"]
    assert columns["author-1"]["status"] == "compile_error"
    assert columns["author-1"]["killedBy"] == []
    assert {cell["status"] for cell in columns["author-1"]["cells"]} == {"compile_error"}
    assert columns["author-2"]["status"] == "survived"
    assert all(cell["actual"] == cell["expected"] for cell in columns["author-2"]["cells"])
    assert report["worker"].startswith("isolate-client") is (execution == "isolate")
    assert report["limits"]["cases"] == report["dispatched"] == 18
    assert call(source_url) == original
    before = store.get_budget(run)
    assert call(url, "POST", request) == (200, result)
    assert store.get_budget(run) == before
    assert call(url, "POST", {**request, "mutantRefs": []})[0] == 409
    saved = call(f"{path}/mutation-matrices/{result['evidenceId']}")[1]
    assert saved["report"] == report
    card = call(path + "/view?studio=1")[1]["evidenceCards"][f"mutation-matrix:{result['evidenceId']}"]
    assert card["matrix"] == report


def test_worker_failure_and_unchecked_rows_cannot_be_survivors_or_kills(api, monkeypatch):
    worker = FakeWorker()
    _, path, campaign, _ = start_campaign(api, worker)
    original = worker.submit

    def interrupted(job):
        if "#define NARROW 1" in job["candidate"]["source"]:
            return {"status": "failed", "classification": "infrastructure_error", "cases": []}
        return original(job)

    monkeypatch.setattr(worker, "submit", interrupted)
    url = f"{path}/mutation-matrices/{campaign}"
    budget = {"cases": 5, "wall_ms": 5000, "oracle_subsets": 4096}
    status, result = api["call"](url, "POST", {"clientRequestId": "t36-partial", "budget": budget})
    assert status == 200, result
    report = result["report"]
    assert report["status"] == "partial" and report["termination"] == "case_budget"
    assert report["qualifiedTests"] == 1 and report["limits"]["cases"] == 4
    assert report["counts"]["survived"] == 0
    narrow = next(col for col in report["columns"] if col["id"] == "narrow")
    assert [cell["status"] for cell in narrow["cells"]] == ["worker_failure", "not_run", "not_run"]
    assert narrow["killedBy"] == []


def test_failed_control_prevents_mutant_dispatch(api, monkeypatch):
    worker = FakeWorker()
    _, path, campaign, _ = start_campaign(api, worker)
    original = worker.submit

    def wrong_control(job):
        reply = original(job)
        reply["cases"][0]["output"] = "-1"
        return reply

    monkeypatch.setattr(worker, "submit", wrong_control)
    status, result = api["call"](f"{path}/mutation-matrices/{campaign}", "POST", {"clientRequestId": "t36-control"})
    assert status == 200, result
    report = result["report"]
    assert report["status"] == "control_failed" and report["counts"]["killed"] == 0
    assert len(worker.jobs) == 2
    assert all(cell["status"] == "not_run" for col in report["columns"][1:] for cell in col["cells"])


def test_steering_during_the_control_stops_mutants_and_fences_the_report(api, monkeypatch):
    worker = FakeWorker()
    run, path, campaign, _ = start_campaign(api, worker)
    service = api["service"]
    original = worker.submit

    def steered(job):
        reply = original(job)
        service.submit_input(run, {"kind": "steer", "text": "I meant closed intervals.",
                                   "clientRequestId": "t36-new-rule"}, schedule=False)
        return reply

    monkeypatch.setattr(worker, "submit", steered)
    status, result = api["call"](f"{path}/mutation-matrices/{campaign}", "POST", {"clientRequestId": "t36-race"})
    assert status == 200 and result["freshness"] == "stale"
    assert result["report"]["termination"] == "stale" and len(worker.jobs) == 2
    assert result["report"]["counts"]["killed"] == 0
    assert all(cell["status"] == "not_run" for col in result["report"]["columns"][1:] for cell in col["cells"])


def test_rendered_matrix_and_reload(api):
    if not os.environ.get("AUTHOR_AGENT_T36_TEST_BROWSER"):
        pytest.skip("set AUTHOR_AGENT_T36_TEST_BROWSER=1 for the rendered Chrome check")
    run, _, _, _ = start_campaign(api, FakeWorker(), samples=1)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = str(listener.getsockname()[1])
    completed = subprocess.run(["node", "qa/engine_contracts/browser_t36_mutation_matrix.mjs"],
                               env={**os.environ, "ENGINE_UI_BASE": api["base"], "STUDIO_T36_RUN": run,
                                    "STUDIO_CDP_PORT": port}, capture_output=True, text=True, timeout=110)
    assert completed.returncode == 0, completed.stdout + completed.stderr
