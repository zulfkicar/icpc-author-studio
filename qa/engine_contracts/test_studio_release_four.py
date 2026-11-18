"""Release 4 data contracts, isolation and recovery through local HTTP."""
import json
import uuid

from author_studio.packages import workspace
from engine.context import conversation_context
from engine.request_meter import measure
from qa.engine_contracts.test_api_boundary import api, wait_for
from qa.engine_contracts.test_studio_release_one import start
from qa.engine_contracts.test_studio_routes import finish
from author_studio.studio_sample import SOURCE


def test_sample_is_distinct_resumable_and_uses_no_configured_worker(api, monkeypatch, tmp_path):
    monkeypatch.setattr(workspace, "WORKSPACES", tmp_path / "packages")
    call = api["call"]
    original = start(call, "release-four-original", "My open problem")
    sample = {"clientRequestId": "sample-r4-test"}
    status, opened = call("/api/studio/sample", "POST", sample)
    assert status == 201, opened
    assert opened["runId"] != original
    assert call("/api/studio/sample", "POST", sample) == (201, opened)
    assert len(workspace.list_workspaces()) == 1
    run = "/api/engine/runs/" + opened["runId"]
    card = wait_for(call, opened["runId"], lambda v: v.get("pendingDecision"))["pendingDecision"]
    assert call(run + "/messages", "POST", {"message": "Half-open: touching jobs are compatible",
        "clientRequestId": "r4-choice", "expectedInteractionId": card["id"]})[0] == 200
    result = wait_for(call, opened["runId"], lambda v: v["evidenceCards"])
    assert not result["capabilities"]["workerReal"] and result["capabilities"]["demoMode"]
    demo = call(run + "/view?studio=1")[1]
    roles = {row["role"] for row in demo["requestContext"]}
    assert roles == {"Authoring", "Decision"}
    assert all(row["source"] == "estimated" for row in demo["requestContext"])
    assert {r["slug"] for r in workspace.list_workspaces()} == {opened["slug"]}
    assert call("/api/engine/runs/" + original + "/studio-sample")[0] == 404
    assert call(run + "/studio-sample")[1]["path"] == SOURCE

    base = "/api/workspaces/" + opened["slug"]
    snapshot = call(base + "/studio")[1]["snapshot"]
    data = {"studioRequestId": str(uuid.uuid4()), "expectedSnapshot": snapshot, "path": SOURCE,
            "asJob": True, "stdin": "3\n0 2 6\n2 4 6\n0 4 13\n", "expected": "13"}
    code, job = call(base + "/run", "POST", data)
    assert code == 200
    assert call(base + "/run", "POST", data)[1]["id"] == job["id"]
    assert call(base + "/run", "POST", {**data, "stdin": "different"})[0] == 409
    found = call(base + "/studio-job?requestId=" + data["studioRequestId"])
    assert found[0] == 200 and found[1]["id"] == job["id"]
    assert call("/api/workspaces/unrelated/studio-job?requestId=" + data["studioRequestId"])[0] == 404
    outcome = finish(call, job)["result"]
    assert outcome["stdout"].strip() == "12" and not outcome["comparison"]["matches"]


def test_context_reports_one_request_and_omits_private_content():
    class Provider:
        name = "Test model"
        configured = True

        def describe_capabilities(self):
            return {"model": self.name, "contextWindow": 32000, "contextWindowSource": "Fixture metadata"}

    body = {"node": "decision.interpret", "prompt": "HIDDEN_SYSTEM_PROMPT",
            "schema_json": {"title": "INTERNAL_SCHEMA"}, "context": {"artifacts": ["SECRET_CASE"], "authorText": "user request"}}
    receipt = measure(body, Provider(), {"input_tokens": 91, "total_tokens": 138})
    assert receipt["tokens"] == receipt["unallocated"] == 91
    assert receipt["source"] == "reported" and receipt["capacity"] == 32000
    assert all(term not in json.dumps(receipt) for term in ("HIDDEN_SYSTEM_PROMPT", "INTERNAL_SCHEMA", "SECRET_CASE"))
    assert {row["id"] for row in receipt["categories"]} >= {"workspace", "conversation", "instructions"}
    estimate = measure(body, Provider(), {"total_tokens": 999})
    assert estimate["source"] == "estimated" and estimate["tokens"] == sum(row["tokens"] for row in estimate["categories"])


def test_long_transcript_pages_keep_newest_turns_in_both_models(api):
    call, service = api["call"], api["service"]
    run_id = start(call, "release-four-long", "Long conversation")
    store = service.store(run_id)
    for index in range(500):
        store.append_chat_message(run_id, role="author", kind="message", text=f"long fixture turn {index:03d}")
    run = f"/api/engine/runs/{run_id}"
    recent = call(run + "/view?studio=1")[1]
    messages = recent["chatMessages"]
    assert recent["hasEarlierChat"] and len(messages) == 100
    assert messages[-1]["text"] == "long fixture turn 499"
    earlier = call(run + "/chat?before=" + str(messages[0]["seq"]))[1]
    assert len(earlier["messages"]) == 100 and earlier["messages"][-1]["seq"] == messages[0]["seq"] - 1
    authoring = conversation_context(service.runtime(run_id), run_id, max_total=50)
    assert "499" in authoring["messages"][-1]["text"]
    decision = service.decisions(run_id).context(run_id, "fixture-message", "next")
    assert decision["conversation"][-1]["text"] == "long fixture turn 499"


def test_stop_keeps_queued_verification_from_changing_saved_package(api, monkeypatch, tmp_path):
    from author_studio import server

    monkeypatch.setattr(workspace, "WORKSPACES", tmp_path / "packages")
    slug = workspace.create("Cancel waiting verification")["slug"]
    call = api["call"]
    base = "/api/workspaces/" + slug
    before = call(base + "/studio")[1]
    request = str(uuid.uuid4())
    with server.workspace_lock(slug):
        status, job = call(base + "/verify", "POST", {"studioRequestId": request,
            "expectedSnapshot": before["snapshot"], "writeAnswers": False})
        assert status == 200 and job["phase"] == "queued"
        assert call("/api/jobs/" + job["id"] + "/cancel", "POST", {})[1]["accepted"]
        assert finish(call, job)["state"] == "cancelled"
    after = call(base + "/studio")[1]
    assert after["lastReport"] == before["lastReport"] and after["snapshot"] == before["snapshot"]
