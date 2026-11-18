"""Counterexample actions from chat through the HTTP boundary and worker."""
from __future__ import annotations

import os
import socket
import subprocess

import pytest

from engine.domain import oracle_subset, parse_instance
from engine.model import FakeModelAdapter
from engine.worker import FakeWorker, IsolateWorker
from qa.engine_contracts.harness import FIXTURES, plan, script
from qa.engine_contracts.test_api_boundary import api, wait_for
from qa.engine_contracts.test_t34_campaign import HELD_OUT, IDEA, draft, spec


def campaign_in_chat(api, worker, *, paste_source=False):
    service, call = api["service"], api["call"]
    service.base_worker = worker
    proposal = draft("dp_strict", spec(family="touching", target=1))
    model = service.model_factory = FakeModelAdapter(script=script(plan=[plan("finish")] * 2 if paste_source else [proposal]))
    service.clone_models = False
    idea = "Help me maximize the total reward of nonoverlapping bookings." if paste_source else IDEA
    status, started = call("/api/engine/chat", "POST", {"message": idea, "clientRequestId": "t35-idea"})
    assert status == 201
    run = started["runId"]
    path = f"/api/engine/runs/{run}"
    if paste_source:
        wait_for(call, run, lambda v: v.get("pendingDecision"))
        assert call(path + "/messages", "POST", {"message": "Use half-open intervals. Touching is allowed."})[0] == 200
        wait_for(call, run, lambda v: v["status"] == "awaiting_author" and not v.get("pendingDecision"))
        source = (FIXTURES / "dp_strict.cpp").read_text(encoding="utf-8")
        assert call(path + "/messages", "POST", {"message": f"```cpp\n{source}```"})[0] == 200
        wait_for(call, run, lambda v: any(a["kind"] == "solution" for a in v["artifacts"]))
        contribution, = [item for item in service.store(run).list_contributions(run) if item["kind"] == "code"]
        proposal["data"]["args"]["candidate_ref"] = contribution["id"]
        model._script["plan"] = [proposal]
        text = f"Run a weighted scheduling campaign with seed {HELD_OUT} against my C++ solution."
        assert call(path + "/messages", "POST", {"message": text})[0] == 200
    wait_for(call, run, lambda v: any(m["kind"] == "campaign" for m in v["chatMessages"]))
    status, view = call(path + "/view?studio=1")
    assert status == 200
    card, = view["evidenceCards"].values()
    assert card["replayable"]
    return run, path, card


@pytest.mark.parametrize("execution", ["simulated", "isolate"])
def test_chat_replays_and_reduces_with_durable_original_and_new_case(api, monkeypatch, execution):
    if execution == "isolate":
        url = os.environ.get("AUTHOR_AGENT_T35_TEST_ISOLATE_URL")
        if not url:
            pytest.skip("set AUTHOR_AGENT_T35_TEST_ISOLATE_URL for compiled execution")
        monkeypatch.setenv("AUTHOR_AGENT_ISOLATE_URL", url)
        worker = IsolateWorker()
    else:
        worker = FakeWorker()
    run, path, card = campaign_in_chat(api, worker, paste_source=True)
    call = api["call"]
    url = f"{path}/counterexamples/{card['id']}"
    original_url = f"{path}/campaigns/{card['id']}"
    original_receipt = call(original_url)
    store = api["service"].store(run)
    before = store.get_budget(run)
    status, replay = call(url, "POST", {"action": "replay", "clientRequestId": "t35-replay"})
    assert status == 200, replay
    assert replay["report"]["status"] == "reproduced"
    assert replay["report"]["replay"]["input"] == card["input"]
    request = {"action": "reduce", "clientRequestId": "t35-reduce"}
    status, reduced = call(url, "POST", request)
    assert status == 200, reduced
    report = reduced["report"]
    assert report["status"] == "reduced" and reduced["freshness"] == "current"
    assert report["predicate"]["kind"] == "endpoint_signature"
    assert report["candidateHash"] == card["sourceHash"] and report["parentEvidenceId"] == card["id"]
    assert report["original"]["input"] == card["input"]
    final = report["reduced"]
    small = parse_instance(final["input"])
    assert small.n == 2 < parse_instance(card["input"]).n
    assert oracle_subset(small, semantics="half_open")["value"] == final["expected"]
    assert oracle_subset(small, semantics="closed")["value"] == final["actual"] < final["expected"]
    assert report["worker"].startswith("isolate-client") is (execution == "isolate")
    assert call(f"{path}/counterexamples/{reduced['evidenceId']}")[1]["report"] == report
    assert call(original_url) == original_receipt
    assert call(url, "POST", request) == (200, reduced)
    assert call(url, "POST", {**request, "action": "replay"})[0] == 409
    budget = store.get_budget(run)
    assert budget["cases_used"] - before["cases_used"] == 17
    assert budget["wall_ms_used"] - before["wall_ms_used"] == 20_000
    assert budget["model_attempts_used"] == before["model_attempts_used"]
    refreshed = call(path + "/view?studio=1")[1]
    pair = refreshed["evidenceCards"][f"counterexample:{reduced['evidenceId']}"]["versions"]
    assert [(entry["title"], entry["input"]) for entry in pair] == [
        ("Original input", card["input"]), ("Reduced input", final["input"])]


def test_changed_answer_and_budget_limit_do_not_publish_a_smaller_witness(api, monkeypatch):
    worker = FakeWorker()
    _, path, card = campaign_in_chat(api, worker)
    call = api["call"]
    url = f"{path}/counterexamples/{card['id']}"
    budget = {"cases": 1, "wall_ms": 3000, "oracle_subsets": 2048}
    status, result = call(url, "POST", {"action": "reduce", "clientRequestId": "t35-limit", "budget": budget})
    assert status == 200, result
    assert result["report"]["termination"] == "case_budget" and result["report"]["reduced"] is None
    assert len(result["report"]["trials"]) == 1
    original_submit = worker.submit

    def changed(job):
        raw = original_submit(job)
        raw["cases"][0]["output"] = str(card["expected"])
        return raw

    monkeypatch.setattr(worker, "submit", changed)
    status, result = call(url, "POST", {"action": "reduce", "clientRequestId": "t35-changed"})
    assert status == 200 and result["report"]["status"] == "not_reproduced"
    assert len(result["report"]["trials"]) == 1 and result["report"]["reduced"] is None

    def different_failure(job):
        raw = original_submit(job)
        if job["cases"][0]["input"] != card["input"]:
            raw["cases"][0]["output"] = "-1"
        return raw

    monkeypatch.setattr(worker, "submit", different_failure)
    status, result = call(url, "POST", {"action": "reduce", "clientRequestId": "t35-other-mismatch"})
    assert status == 200 and result["report"]["status"] == "no_reduction"
    assert result["report"]["reduced"] is None
    assert all(trial["actual"] == -1 for trial in result["report"]["trials"][1:])


def test_a_different_source_cannot_replay_the_saved_witness(api, monkeypatch):
    worker = FakeWorker()
    run, path, card = campaign_in_chat(api, worker)
    runtime = api["service"].runtime(run)
    source = runtime.candidate_source

    def changed(run_id, ref):
        canonical_ref, body, label = source(run_id, ref)
        return canonical_ref, body + "\n// changed after campaign\n", label

    monkeypatch.setattr(type(runtime), "candidate_source", lambda self, *args: changed(*args))
    status, result = api["call"](f"{path}/counterexamples/{card['id']}", "POST",
                                {"action": "replay", "clientRequestId": "t35-different-source"})
    assert status == 409 and "hash changed" in result["error"]
    assert len(worker.jobs) == 1


def test_steering_during_replay_fences_every_later_trial_and_old_witness(api, monkeypatch):
    worker = FakeWorker()
    run, path, card = campaign_in_chat(api, worker)
    service, call = api["service"], api["call"]
    original_submit = worker.submit

    def steered(job):
        raw = original_submit(job)
        service.submit_input(run, {"kind": "steer", "text": "I meant closed intervals.",
                                   "clientRequestId": "t35-steering"}, schedule=False)
        return raw

    monkeypatch.setattr(worker, "submit", steered)
    url = f"{path}/counterexamples/{card['id']}"
    status, result = call(url, "POST", {"action": "reduce", "clientRequestId": "t35-superseded"})
    assert status == 200 and result["freshness"] == "stale"
    assert len(result["report"]["trials"]) == 1 and result["report"]["reduced"] is None
    service.pump_sync(run)
    assert call(url, "POST", {"action": "replay", "clientRequestId": "t35-after-steering"})[0] == 409
    assert len(worker.jobs) == 2


def test_reopen_projects_committed_result_even_if_chat_write_was_interrupted(api):
    worker = FakeWorker()
    run, path, card = campaign_in_chat(api, worker)
    service, call = api["service"], api["call"]
    # Commit the result through the normal service but skip the HTTP chat facade.
    receipt = service.counterexample_action(run, card["id"], {"action": "replay", "clientRequestId": "t35-project"})
    assert receipt["report"]["status"] == "reproduced"
    store = service.store(run)
    assert not any(m["kind"] == "counterexample" for m in store.list_chat_messages(run))
    first = call(path + "/view?studio=1")[1]
    second = call(path + "/view?studio=1")[1]
    assert [m for m in first["chatMessages"] if m["kind"] == "counterexample"] == [
        m for m in second["chatMessages"] if m["kind"] == "counterexample"]
    assert f"counterexample:{receipt['evidenceId']}" in second["evidenceCards"]
    assert len(worker.jobs) == 2


def test_rendered_chat_replay_reduce_and_reload(api):
    if not os.environ.get("AUTHOR_AGENT_T35_TEST_BROWSER"):
        pytest.skip("set AUTHOR_AGENT_T35_TEST_BROWSER=1 for the rendered Chrome check")
    run, _, _ = campaign_in_chat(api, FakeWorker())
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = str(listener.getsockname()[1])
    completed = subprocess.run(["node", "qa/engine_contracts/browser_t35_counterexamples.mjs"],
                               env={**os.environ, "ENGINE_UI_BASE": api["base"], "STUDIO_T35_RUN": run,
                                    "STUDIO_CDP_PORT": port}, capture_output=True, text=True, timeout=110)
    assert completed.returncode == 0, completed.stdout + completed.stderr
