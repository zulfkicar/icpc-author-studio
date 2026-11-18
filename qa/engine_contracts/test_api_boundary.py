"""Real HTTP server boundary tests for the V0-V3 engine routes."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
import zipfile

import pytest
from http.server import HTTPServer

import server
import workspace
from engine.demo import demo_script
from engine.model import FakeModelAdapter
from engine.policy import render_text_escaped
from engine.service import EngineService
from engine.worker import FakeWorker
from qa.engine_contracts.harness import FIXTURES


@pytest.fixture()
def api(tmp_path):
    service = EngineService(tmp_path / "api-root",
                            model_adapter=FakeModelAdapter(script=demo_script()),
                            worker=FakeWorker(), fixture_dir=str(FIXTURES))
    server.ENGINE_SERVICE = service
    httpd = HTTPServer(("127.0.0.1", 0), server.Handler)
    server_errors: list[str] = []

    def record_error(request, client_address):
        import traceback
        server_errors.append(traceback.format_exc())

    def serve():
        try:
            httpd.serve_forever()
        except BaseException:  # noqa: BLE001
            import traceback
            server_errors.append(traceback.format_exc())

    httpd.handle_error = record_error
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_port}"

    def call(path, method="GET", body=None, headers=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request_headers = {"Content-Type": "application/json"} if data else {}
        request_headers.update(headers or {})

        def attempt():
            req = urllib.request.Request(base + path, data=data, method=method,
                                         headers=request_headers)
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    return response.status, json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                return exc.code, json.loads(exc.read().decode("utf-8"))

        # Windows loopback occasionally resets a fresh GET under load; retry
        # only idempotent reads.  Mutations are never retried here.
        last = None
        for _ in range(3 if method == "GET" else 1):
            try:
                return attempt()
            except (ConnectionAbortedError, ConnectionResetError) as exc:
                last = exc
                import time
                time.sleep(0.05)
        if last is not None:
            raise ConnectionAbortedError(
                f"loopback reset after retries; serverErrors={server_errors[-3:]}"
            ) from last
        return attempt()

    yield {"call": call, "service": service, "base": base, "root": tmp_path / "api-root"}
    httpd.shutdown()
    httpd.server_close()
    service.close()
    server.ENGINE_SERVICE = None


def wait_for(call, run_id, predicate, attempts=80):
    view = {}
    for _ in range(attempts):
        status, view = call(f"/api/engine/runs/{run_id}/view")
        assert status == 200
        if predicate(view):
            return view
        import time
        time.sleep(0.1)
    raise AssertionError(f"condition not reached: {json.dumps(view)[:1000]}")


def create_run(api, idea="Help me develop profitable bookings; work with me, briefly.", key="api-1"):
    status, created = api["call"]("/api/engine/runs", "POST", {
        "workspaceId": "api-test", "idea": idea, "clientRequestId": key,
    })
    assert status == 201
    return created["runId"]


def test_capabilities_disclose_fake_model_and_worker(api):
    status, caps = api["call"]("/api/engine/capabilities")
    assert status == 200
    assert caps["modelIsFake"] is True
    assert caps["workerReal"] is False
    assert caps["delivery"]["supported"] is False
    assert caps["restoreMutations"]["supported"] is False
    assert "workflow mechanics" in caps["disclosure"]


def test_problem_title_is_persisted_without_steering_the_run(api):
    call = api["call"]
    idea = "Help me develop profitable bookings."
    status, started = call("/api/engine/chat", "POST", {"message": idea, "title": " Lock Windows "})
    assert status == 201 and started["view"]["title"] == "Lock Windows"
    run_id = started["runId"]
    run_path = f"/api/engine/runs/{run_id}"
    before = started["view"]

    assert call(run_path + "/title", "POST", {"title": "Revised Lock Windows"}) == (
        200, {"runId": run_id, "title": "Revised Lock Windows"},
    )
    assert call(run_path + "/title", "POST", {"title": "line one\nline two"})[0] == 400
    status, after = call(run_path + "/view")
    assert status == 200 and after["title"] == "Revised Lock Windows"
    for key in ("revision", "goalGeneration", "steeringEpoch", "inputs", "chatMessages", "pendingDecision"):
        assert after[key] == before[key]
    entry = next(row for row in call("/api/engine/runs")[1]["runs"] if row["runId"] == run_id)
    assert entry["title"] == "Revised Lock Windows" and entry["idea"] == idea


def test_named_package_uses_title_and_rename_requires_fresh_approval(api, monkeypatch, tmp_path):
    monkeypatch.setattr(workspace, "WORKSPACES", tmp_path / "packages")
    call = api["call"]
    start, data = call("/api/engine/chat", "POST", {"message": "Named bookings", "title": "First Lock"})
    assert start == 201
    run_id = data["runId"]
    run_path = f"/api/engine/runs/{run_id}"
    status, linked = call(run_path + "/studio-package", "POST", {"name": "Ignored duplicate name"})
    assert status == 201 and linked == {"slug": "first-lock"}
    slug = linked["slug"]
    root = workspace.ws_path(slug)
    assert workspace.summary(slug)["meta"]["name"] == "First Lock"
    assert r"\problemname{First Lock}" in (root / "problem_statement/problem.en.tex").read_text("utf-8")

    def save_passing_snapshot():
        # Seed only the verification receipt. Archive generation and review use the real package APIs.
        snapshot = workspace.snapshot_hash(slug)
        workspace.set_report(slug, {"status": "verified", "snapshot": snapshot})
        return snapshot

    initial = save_passing_snapshot()
    assert call(f"/api/workspaces/{slug}/review", "POST", {"expectedSnapshot": initial})[0] == 200
    old = server.verify.export_package(slug)
    assert old["path"].endswith("first-lock-domjudge.zip")
    title = 'Second Lock & "Harbor"'
    assert call(run_path + "/title", "POST", {"title": title})[0] == 200
    assert workspace.summary(slug)["meta"]["name"] == title
    assert server.verify._read_meta(slug)["name"] == title
    assert r'\problemname{Second Lock \& "Harbor"}' in (root / "problem_statement/problem.en.tex").read_text("utf-8")
    assert workspace.summary(slug)["lastStatus"] == "stale"
    assert workspace.snapshot_hash(slug) != initial
    with pytest.raises(ValueError, match="workspace changed"):
        server.verify.export_package(slug)

    current = save_passing_snapshot()
    with pytest.raises(ValueError, match="Mark all changes reviewed"):
        server.verify.export_package(slug)
    status, _ = call(f"/api/workspaces/{slug}/review", "POST", {"expectedSnapshot": current})
    assert status == 200
    result = server.verify.export_package(slug)
    assert result["path"].endswith("second-lock-harbor-domjudge.zip")
    request = urllib.request.Request(api["base"] + f"/api/workspaces/{slug}/download?snapshot={current}")
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.headers["Content-Disposition"] == 'attachment; filename="second-lock-harbor-domjudge.zip"'
        assert response.read() == (root / result["path"]).read_bytes()
    with zipfile.ZipFile(root / result["path"]) as archive:
        assert json.loads(archive.read("problem_statement/manifest.json"))["problem"]["name"] == title


def test_full_http_journey_decision_explanation_and_unsupported_actions(api):
    run_id = create_run(api)
    view = wait_for(api["call"], run_id,
                    lambda v: v.get("pendingDecision") and v["status"] == "waiting_human")
    decision = view["pendingDecision"]
    assert view["status"] == "waiting_human"
    status, receipt = api["call"](
        f"/api/engine/runs/{run_id}/interactions/{decision['id']}/responses", "POST", {
            "clientRequestId": "resp-http-1",
            "kind": "semantic_choice",
            "payload": {"requirement_id": "endpoint_semantics", "option_id": "half_open"},
            "expectedRevision": decision["revision"],
            "expectedGoalGeneration": decision["goalGeneration"],
            "expectedProposalHash": decision["proposalHash"],
        })
    assert status == 200 and receipt["status"] == "receipt"
    view = wait_for(api["call"], run_id,
                    lambda v: v["status"] in ("awaiting_author", "stage_returned", "incomplete")
                    and not v.get("pendingDecision"))
    assert view["currentExplanation"] is not None
    assert "13" in view["currentExplanation"]["short_answer"]
    assert view["delivery"]["supported"] is False
    assert view["restoreMutations"]["supported"] is False
    events_before = len(api["call"](f"/api/engine/runs/{run_id}/events?after=0")[1]["events"])
    for action in ("exports", "restores", "approve-export"):
        status, refusal = api["call"](f"/api/engine/runs/{run_id}/{action}", "POST", {})
        assert status == 501
        assert refusal["supported"] is False and refusal["effectsApplied"] == 0
    events_after = len(api["call"](f"/api/engine/runs/{run_id}/events?after=0")[1]["events"])
    assert events_after == events_before, "refusal must have no ledger effects"


def test_input_received_202_and_idempotency_conflict_409(api):
    run_id = create_run(api, key="idem-run")
    body = {"kind": "steer", "text": "Use brief explanations.",
            "clientRequestId": "same-key", "expectedGeneration": 0}
    status, first = api["call"](f"/api/engine/runs/{run_id}/inputs", "POST", body)
    assert status == 202 and first["status"] == "received"
    status, second = api["call"](f"/api/engine/runs/{run_id}/inputs", "POST", body)
    assert status == 202 and second["inputId"] == first["inputId"]
    status, conflict = api["call"](f"/api/engine/runs/{run_id}/inputs", "POST", {
        **body, "text": "different body"})
    assert status == 409
    assert conflict["code"] == "idempotency_conflict"
    view = wait_for(api["call"], run_id, lambda v: any(i["id"] == first["inputId"] and
                                                       i["status"] != "received"
                                                       for i in v["inputs"]))
    assert any(i["status"] == "received" for i in view["inputs"]) is False


def test_stale_response_returns_409_and_keeps_card(api):
    run_id = create_run(api, key="stale-run")
    view = wait_for(api["call"], run_id, lambda v: v.get("pendingDecision"))
    decision = view["pendingDecision"]
    status, receipt = api["call"](
        f"/api/engine/runs/{run_id}/interactions/{decision['id']}/responses", "POST", {
            "clientRequestId": "stale-http",
            "kind": "semantic_choice",
            "payload": {"requirement_id": "endpoint_semantics", "option_id": "half_open"},
            "expectedRevision": "rev-999",
            "expectedGoalGeneration": 7,
            "expectedProposalHash": "0" * 64,
        })
    assert status == 409
    assert set(receipt["stale"]) >= {"revision", "goal_generation", "proposal_hash"}
    view = wait_for(api["call"], run_id, lambda v: True)
    assert view["pendingDecision"] is not None
    assert view["goalGeneration"] == 0


def test_cross_origin_mutation_and_bad_host_rejected(api):
    run_id = create_run(api, key="origin-run")
    status, body = api["call"](f"/api/engine/runs/{run_id}/inputs", "POST",
                               {"kind": "steer", "text": "x", "clientRequestId": "origin"},
                               headers={"Origin": "http://evil.example"})
    assert status == 403
    assert "origin" in body["error"].lower()
    status, body = api["call"]("/api/engine/capabilities", headers={"Host": "evil.example"})
    assert status == 403


def test_oversized_and_schema_invalid_payloads_fail_safely(api):
    run_id = create_run(api, key="schema-run")
    status, body = api["call"](f"/api/engine/runs/{run_id}/inputs", "POST", {
        "kind": "contribute", "clientRequestId": "big",
        "payload": {"contributionKind": "code", "content": "x" * (1024 * 1024 + 1)},
    })
    assert status == 413
    status, body = api["call"](f"/api/engine/runs/{run_id}/inputs", "POST", {
        "kind": "contribute", "clientRequestId": "path",
        "payload": {"contributionKind": "code", "content": "x", "path": "../../secret"},
    })
    assert status == 403
    status, body = api["call"](f"/api/engine/runs/{run_id}/inputs", "POST", {
        "kind": "not_a_kind", "clientRequestId": "bad-kind", "text": "x",
    })
    assert status == 422
    status, body = api["call"](f"/api/engine/runs/{run_id}/inputs", "POST", {
        "kind": "steer", "text": "x", "clientRequestId": "actor", "actorId": "root",
    })
    assert status == 422


def test_unsafe_html_is_returned_as_data_and_escaped_for_rendering(api):
    run_id = create_run(api, idea="Maximise reward over half-open intervals.")
    payload = '<img src=x onerror="alert(1)"><script>bad()</script>'
    status, receipt = api["call"](f"/api/engine/runs/{run_id}/inputs", "POST", {
        "kind": "contribute", "clientRequestId": "html",
        "payload": {"contributionKind": "idea", "content": payload, "attribution": "<b>author</b>"},
    })
    assert status == 202
    wait_for(api["call"], run_id, lambda v: any(c["actorKind"] == "human" for c in v["contributions"]))
    status, view = api["call"](f"/api/engine/runs/{run_id}/view")
    stored = [c for c in view["contributions"] if c["actorKind"] == "human"]
    assert stored and stored[0]["attribution"] == "<b>author</b>"  # data, not markup
    escaped = render_text_escaped(payload)
    assert "<script>" not in escaped and "&lt;script&gt;" in escaped
    # The renderer uses textContent; verify the shipped UI path does not inject HTML.
    ui_source = (server.WEB / "engine.js").read_text(encoding="utf-8")
    assert "textContent" in ui_source
    assert ".innerHTML" not in ui_source


def test_unknown_run_and_malformed_body(api):
    status, body = api["call"]("/api/engine/runs/run-nope/view")
    assert status == 404
    status, body = api["call"]("/api/engine/runs", "POST", {"idea": ""})
    assert status in (400, 422, 403)


def test_http_cannot_seed_records_or_invoke_the_graph(api):
    status, created = api["call"]("/api/engine/runs", "POST", {
        "workspaceId": "api-test", "idea": "Help me decide endpoints.",
        "clientRequestId": "seed-attempt",
        "seed": {"contributions": [{"contributionKind": "code", "content": "int main(){}"}]},
    })
    assert status == 201
    run_id = created["runId"]
    wait_for(api["call"], run_id, lambda v: v.get("pendingDecision"))
    view = api["call"](f"/api/engine/runs/{run_id}/view")[1]
    assert view["contributions"] == []
    status, _ = api["call"](f"/api/engine/runs/{run_id}/pump", "POST", {})
    assert status == 404
    status, _ = api["call"](f"/api/engine/runs/{run_id}/contributions", "POST", {
        "contributionKind": "code", "content": "int main(){}"})
    assert status == 422


def test_events_cursor_and_snapshot(api):
    run_id = create_run(api, key="events-run")
    wait_for(api["call"], run_id, lambda v: v.get("pendingDecision"))
    status, first = api["call"](f"/api/engine/runs/{run_id}/events?after=0")
    assert status == 200 and first["events"]
    assert first["nextSeq"] > 1
    status, tail = api["call"](f"/api/engine/runs/{run_id}/events?after={first['nextSeq'] - 1}")
    assert len(tail["events"]) <= 1
    status, view = api["call"](f"/api/engine/runs/{run_id}/view")
    assert view["appliedAuthorSeq"] >= 1
    assert view["budget"]["modelAttemptsLimit"] == 30
