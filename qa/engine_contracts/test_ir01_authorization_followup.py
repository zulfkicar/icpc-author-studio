"""IR01 follow-up: apostrophes, intent recognition and effect enforcement.

The tests exercise the real compiled graph, application ledger and loopback HTTP
boundary.  A scripted model proposes an adversarial NOTES.md edit; it never
implements host authorization.
"""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest
from http.server import HTTPServer

from author_studio import server
from engine.clock import CrashInjected
from engine.interpretation import interpret_authorization
from engine.model import FakeModelAdapter
from engine.service import EngineService
from engine.worker import FakeWorker
from qa.engine_contracts.harness import FIXTURES, Harness, plan, script

EXPLICIT = "Use half-open intervals."
ADVERSARIAL = plan("edit", args={"path": "NOTES.md", "after": "unauthorized note\n"})


def _files(h: Harness, rid: str) -> list[str]:
    store = h.store(rid)
    revision = store.get_revision(store.get_run(rid)["observed_revision"])
    return [item["canonical_path"] for item in revision["files"]]


def _edit_grants(h: Harness, rid: str) -> list[dict]:
    out = []
    for row in h.store(rid).read_all(
            "SELECT operation_kinds_json, scope_json, revoked_at FROM grants WHERE run_id=?",
            (rid,)):
        kinds = json.loads(row["operation_kinds_json"] or "[]")
        if "edit" in kinds:
            out.append({"scope": json.loads(row["scope_json"] or "[]"),
                        "revokedAt": row["revoked_at"]})
    return out


def _patch_evidence(h: Harness, rid: str) -> list[dict]:
    return [item for item in h.store(rid).list_evidence(rid) if item["outcome"] == "patch"]


def _initial(instruction: str, *, path: str = "NOTES.md") -> tuple[Harness, str]:
    edit = plan("edit", args={"path": path, "after": "unauthorized note\n"})
    h = Harness(script(plan=[edit, plan("finish")]))
    rid = h.create(EXPLICIT + " " + instruction)
    h.pump(rid)
    return h, rid


def _steering(instruction: str, *, path: str = "NOTES.md") -> tuple[Harness, str]:
    h = Harness(script(plan=[plan("finish")]))
    rid = h.create(EXPLICIT)
    h.pump(rid)
    h.service.submit_input(rid, {"kind": "steer", "text": instruction,
                                 "clientRequestId": "authorization-instruction"},
                           schedule=False)
    h.pump(rid)
    h.model._script["plan"] = [
        plan("edit", args={"path": path, "after": "unauthorized note\n"}),
        plan("finish"),
    ]
    h.service.submit_input(rid, {"kind": "steer", "text": "Continue.",
                                 "clientRequestId": "authorization-continue"},
                           schedule=False)
    h.pump(rid)
    return h, rid


def _assert_no_effect(h: Harness, rid: str, *, allow_pending: bool = False) -> None:
    assert "NOTES.md" not in _files(h, rid)
    assert _patch_evidence(h, rid) == []
    assert _edit_grants(h, rid) == []
    pending = h.store(rid).pending_interaction(rid)
    if not allow_pending:
        assert pending is None, (pending or {}).get("kind")


# ---------------------------------------------------------------- lexical / contractions
@pytest.mark.parametrize("instruction", [
    "Don't apply the patch and don't edit NOTES.md.",
    "Don’t apply the patch and don’t edit NOTES.md.",
    "Don't apply the patch and don’t edit NOTES.md.",
    "Don't you dare edit NOTES.md.",
    "I don't want you to edit NOTES.md.",
    "Won't update NOTES.md.",
    "Wouldn't it be wrong to patch NOTES.md?",
])
def test_ir01_followup_contractions_do_not_grant_initial(tmp_path, instruction):
    h, rid = _initial(instruction)
    _assert_no_effect(h, rid)
    h.close()


@pytest.mark.parametrize("instruction", [
    "Don't apply the patch and don't edit NOTES.md.",
    "Don’t apply the patch and don’t edit NOTES.md.",
    "I don't want you to edit NOTES.md.",
    "Won't update NOTES.md.",
])
def test_ir01_followup_contractions_do_not_grant_steering(tmp_path, instruction):
    h, rid = _steering(instruction)
    _assert_no_effect(h, rid)
    h.close()


def test_ir01_followup_quotation_lexing_keeps_apostrophes(tmp_path):
    decision = interpret_authorization("Don't apply the patch and don't edit NOTES.md.")
    assert decision.action == "deny"
    assert decision.edit is False
    assert decision.intent == "restricted"
    # A genuine quoted instruction is data, not authority.
    quoted = interpret_authorization(
        "A reviewer said 'apply the patch to NOTES.md' as an example."
    )
    assert quoted.action == "none"
    assert quoted.quoted is True
    # A quoted pathname is an argument, not an instruction.
    path = interpret_authorization("Apply a patch to 'NOTES.md'.")
    assert path.action == "grant"
    assert path.scope_paths == ("NOTES.md",)


# ---------------------------------------------------------------- explanation / questions
@pytest.mark.parametrize("instruction", [
    "Explain how to fix NOTES.md.",
    "Describe the changes needed to update NOTES.md.",
    "Show me how to repair NOTES.md.",
    "Tell me how you would patch NOTES.md.",
    "Help me understand how to update NOTES.md.",
    "Could you explain how we might fix NOTES.md?",
    "Is a repair needed?",
    "What changes would fix NOTES.md?",
])
def test_ir01_followup_explanation_requests_do_not_authorize_initial(tmp_path, instruction):
    h, rid = _initial(instruction)
    _assert_no_effect(h, rid)
    assert h.store(rid).pending_interaction(rid) is None
    h.close()


@pytest.mark.parametrize("instruction", [
    "Explain how to fix NOTES.md.",
    "Describe the changes needed to update NOTES.md.",
    "Show me how to repair NOTES.md.",
    "Could you explain how we might fix NOTES.md?",
    "Is a repair needed?",
])
def test_ir01_followup_explanation_requests_do_not_authorize_steering(tmp_path, instruction):
    h, rid = _steering(instruction)
    _assert_no_effect(h, rid)
    assert h.store(rid).pending_interaction(rid) is None
    h.close()


def test_ir01_followup_tentative_edit_requests_clarification_but_no_effect(tmp_path):
    h, rid = _steering("Consider updating NOTES.md.")
    _assert_no_effect(h, rid, allow_pending=True)
    pending = h.store(rid).pending_interaction(rid)
    assert pending is not None and pending["kind"] == "delegation"
    h.close()


@pytest.mark.parametrize("instruction", [
    "Do not apply any patch.",
    "Only compare the solutions.",
    "Never update NOTES.md.",
    "I don't want you to edit NOTES.md.",
    "Please don't patch NOTES.md.",
])
def test_ir01_followup_exclusions_and_negations_are_enforced_twice(tmp_path, instruction):
    h = Harness(script(plan=[plan("finish")]))
    rid = h.create(EXPLICIT + " Apply a patch to NOTES.md.")
    h.pump(rid)
    h.service.submit_input(rid, {"kind": "steer", "text": instruction,
                                 "clientRequestId": "restriction"}, schedule=False)
    h.pump(rid)
    h.model._script["plan"] = [ADVERSARIAL, plan("finish")]
    h.service.submit_input(rid, {"kind": "steer", "text": "Continue.",
                                 "clientRequestId": "restriction-continue"}, schedule=False)
    h.pump(rid)
    store = h.store(rid)
    assert "NOTES.md" not in _files(h, rid)
    assert _patch_evidence(h, rid) == []
    assert all(grant["revokedAt"] for grant in _edit_grants(h, rid)) or _edit_grants(h, rid) == []
    assert store.get_run(rid)["goal_generation"] == 0
    h.close()


# ---------------------------------------------------------------- quotations
@pytest.mark.parametrize("instruction", [
    "A reviewer said 'apply the patch to NOTES.md', but that is only an example.",
    'He wrote "apply the patch to NOTES.md" as a quotation.',
    "The design notes quote 'update NOTES.md' as an example.",
])
def test_ir01_followup_quoted_instructions_grant_nothing(tmp_path, instruction):
    h, rid = _initial(instruction)
    _assert_no_effect(h, rid)
    h.close()


def test_ir01_followup_quoted_example_path_does_not_broaden_scope(tmp_path):
    h = Harness(script(plan=[
        plan("edit", args={"path": "NOTES.md", "after": "authorized\n"}),
        plan("finish"),
    ]))
    rid = h.create(EXPLICIT + ' Apply a patch to NOTES.md, as shown in "apply to solution.cpp".')
    h.pump(rid)
    assert "NOTES.md" in _files(h, rid)
    assert "solution.cpp" not in _files(h, rid)
    grants = _edit_grants(h, rid)
    assert grants and all("path:solution.cpp" not in grant["scope"] for grant in grants)
    h.close()


# ---------------------------------------------------------------- positive controls
@pytest.mark.parametrize("instruction", [
    "Apply a patch to NOTES.md.",
    "Please update NOTES.md.",
    "Please, update NOTES.md.",
    "Patch NOTES.md.",
    "I want you to fix NOTES.md.",
    "You should update NOTES.md.",
    "Go ahead and edit NOTES.md.",
    "Make sure to repair NOTES.md.",
])
def test_ir01_followup_clear_affirmative_instructions_publish_once(tmp_path, instruction):
    h = Harness(script(plan=[
        plan("edit", args={"path": "NOTES.md", "after": "authorized note\n"}),
        plan("finish"),
    ]))
    rid = h.create(EXPLICIT + " " + instruction)
    h.pump(rid)
    store = h.store(rid)
    assert "NOTES.md" in _files(h, rid)
    assert store.pending_interaction(rid) is None
    assert len(_patch_evidence(h, rid)) == 1
    revision = store.get_run(rid)["observed_revision"]
    h.pump(rid)
    assert store.get_run(rid)["observed_revision"] == revision
    assert len(_patch_evidence(h, rid)) == 1
    h.close()


@pytest.mark.parametrize("quote", ["'", '"', "`"])
def test_ir01_followup_quoted_path_is_scoped_not_an_instruction(tmp_path, quote):
    h = Harness(script(plan=[
        plan("edit", args={"path": "NOTES.md", "after": "authorized note\n"}),
        plan("finish"),
    ]))
    rid = h.create(EXPLICIT + f" Apply a patch to {quote}NOTES.md{quote}.")
    h.pump(rid)
    assert "NOTES.md" in _files(h, rid)
    grants = _edit_grants(h, rid)
    assert grants and grants[0]["scope"] == ["path:NOTES.md"]
    assert len(_patch_evidence(h, rid)) == 1
    h.close()


def test_ir01_followup_out_of_scope_proposal_refused(tmp_path):
    h = Harness(script(plan=[
        plan("edit", args={"path": "solution.cpp", "after": "int main(){}\n"}),
        plan("finish"),
    ]))
    rid = h.create(EXPLICIT + " Apply a patch to NOTES.md.")
    h.pump(rid)
    assert "solution.cpp" not in _files(h, rid)
    assert _patch_evidence(h, rid) == []
    assert _edit_grants(h, rid)[0]["scope"] == ["path:NOTES.md"]
    h.close()


# ---------------------------------------------------------------- revocation / replay
def test_ir01_followup_contracted_revocation_fences_inflight_publication(tmp_path):
    h = Harness(root=tmp_path / "revoke", script=script(plan=[
        plan("edit", args={"path": "NOTES.md", "after": "authorized note\n"}),
        plan("finish"),
    ]))
    rid = h.create(EXPLICIT + " Apply a patch to NOTES.md.")
    h.service.failpoints.arm("editing.before_publish")
    with pytest.raises(CrashInjected):
        h.pump(rid)
    assert "NOTES.md" not in _files(h, rid)
    h.service.submit_input(rid, {"kind": "steer",
                                 "text": "Don't edit NOTES.md.",
                                 "clientRequestId": "contracted-revoke"}, schedule=False)
    h.pump(rid)
    store = h.store(rid)
    assert "NOTES.md" not in _files(h, rid)
    assert _patch_evidence(h, rid) == []
    grants = _edit_grants(h, rid)
    assert grants and all(grant["revokedAt"] for grant in grants)
    events = [e for e in store.events_after(rid, 0, 400)
              if e["type"] in ("edit_authority_denied", "edit_authority_revoked")]
    assert events
    h.close()


def test_ir01_followup_revocation_survives_restart_without_permission_resurrection(tmp_path):
    h = Harness(root=tmp_path / "revoke-restart", script=script(plan=[
        plan("edit", args={"path": "NOTES.md", "after": "authorized note\n"}),
        plan("finish"),
    ]))
    rid = h.create(EXPLICIT + " Apply a patch to NOTES.md.")
    h.service.failpoints.arm("editing.before_publish")
    with pytest.raises(CrashInjected):
        h.pump(rid)
    h.service.submit_input(rid, {"kind": "steer", "text": "Stop editing.",
                                 "clientRequestId": "revoke-restart"}, schedule=False)
    h.close()
    h2 = Harness(root=tmp_path / "revoke-restart", script=script(plan=[ADVERSARIAL, plan("finish")]))
    h2.pump(rid)
    assert "NOTES.md" not in _files(h2, rid)
    assert h2.store(rid).get_run(rid)["status"] in ("incomplete", "awaiting_author", "blocked")
    h2.close()


def test_ir01_followup_duplicate_input_cannot_duplicate_grant_or_effect(tmp_path):
    h = Harness(script(plan=[plan("edit", args={"path": "NOTES.md",
                                               "after": "authorized note\n"}),
                             plan("finish")]))
    rid = h.create(EXPLICIT)
    h.pump(rid)
    body = {"kind": "steer", "text": "Apply a patch to NOTES.md.",
            "clientRequestId": "duplicate-grant"}
    first = h.service.submit_input(rid, body, schedule=False)
    second = h.service.submit_input(rid, body, schedule=False)
    assert first["inputId"] == second["inputId"]
    h.pump(rid)
    assert "NOTES.md" in _files(h, rid)
    assert len(_patch_evidence(h, rid)) == 1
    h.close()


# ---------------------------------------------------------------- finite composition controls
def test_ir01_followup_composition_controls_do_not_increase_authority():
    straight = interpret_authorization("Don't apply the patch and don't edit NOTES.md.")
    curly = interpret_authorization("Don’t apply the patch and don’t edit NOTES.md.")
    assert straight.action == curly.action == "deny"
    assert straight.edit is False and curly.edit is False

    explanation = interpret_authorization("Explain how to fix NOTES.md.")
    assert explanation.action == "none" and explanation.edit is False

    base = interpret_authorization("Apply a patch to NOTES.md.")
    example = interpret_authorization(
        'Apply a patch to NOTES.md, but the example says "apply solution.cpp".'
    )
    assert base.action == "grant" and base.scope_paths == ("NOTES.md",)
    assert example.action == "grant" and example.scope_paths == ("NOTES.md",)


# ---------------------------------------------------------------- HTTP boundary
def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class _Http:
    def __init__(self, service: EngineService):
        self.service = service
        server.ENGINE_SERVICE = service
        self.httpd = HTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"

    def call(self, path: str, method: str = "GET", body: dict | None = None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.service.close()
        server.ENGINE_SERVICE = None


@pytest.fixture()
def api_ir01(tmp_path):
    service = EngineService(
        tmp_path / "ir01-http",
        model_adapter=FakeModelAdapter(script=script(plan=[ADVERSARIAL, plan("finish")])),
        worker=FakeWorker(), fixture_dir=str(FIXTURES),
    )
    httpd = _Http(service)
    yield httpd
    httpd.close()


def _wait_settled(httpd: _Http, run_id: str) -> dict:
    view = {}
    for _ in range(100):
        status, view = httpd.call(f"/api/engine/runs/{run_id}/view")
        assert status == 200
        if view["status"] in ("incomplete", "awaiting_author", "stage_returned", "blocked"):
            return view
        time.sleep(0.1)
    return view


def _create_http_run(httpd: _Http, idea: str, key: str) -> str:
    status, created = httpd.call("/api/engine/runs", "POST", {
        "workspaceId": "ir01", "idea": idea, "clientRequestId": key,
    })
    assert status == 201
    return created["runId"]


def test_ir01_followup_http_negative_and_explanation_journeys(api_ir01):
    negative = _create_http_run(
        api_ir01, EXPLICIT + " Don't apply the patch and don't edit NOTES.md.",
        "http-negative",
    )
    view = _wait_settled(api_ir01, negative)
    assert view["delegations"] == []
    assert view["pendingDecision"] is None
    store = api_ir01.service.store(negative)
    assert "NOTES.md" not in [f["canonical_path"] for f in
                              store.get_revision(store.get_run(negative)["observed_revision"])["files"]]

    explanation = _create_http_run(
        api_ir01, EXPLICIT + " Explain how to fix NOTES.md.", "http-explanation"
    )
    view = _wait_settled(api_ir01, explanation)
    assert view["pendingDecision"] is None
    store = api_ir01.service.store(explanation)
    assert "NOTES.md" not in [f["canonical_path"] for f in
                              store.get_revision(store.get_run(explanation)["observed_revision"])["files"]]
    assert not [e for e in store.list_evidence(explanation) if e["outcome"] == "patch"]


def test_ir01_followup_http_affirmative_and_revoke_journeys(api_ir01):
    affirmative = _create_http_run(
        api_ir01, EXPLICIT + " Apply a patch to NOTES.md.", "http-affirmative"
    )
    _wait_settled(api_ir01, affirmative)
    store = api_ir01.service.store(affirmative)
    files = [f["canonical_path"] for f in
             store.get_revision(store.get_run(affirmative)["observed_revision"])["files"]]
    assert "NOTES.md" in files
    assert len([e for e in store.list_evidence(affirmative) if e["outcome"] == "patch"]) == 1

    # Pause before publication, then send the restriction through real HTTP.
    run_id = api_ir01.service.create_run(
        workspace_id="ir01", idea=EXPLICIT + " Apply a patch to NOTES.md."
    )["runId"]
    api_ir01.service.failpoints.arm("editing.before_publish")
    with pytest.raises(CrashInjected):
        api_ir01.service.pump_sync(run_id)
    status, receipt = api_ir01.call(f"/api/engine/runs/{run_id}/inputs", "POST", {
        "kind": "steer", "text": "Don't edit NOTES.md.",
        "clientRequestId": "http-revoke",
    })
    assert status == 202
    api_ir01.service.wait_until_settled(run_id, timeout=30)
    api_ir01.service.pump_sync(run_id)
    status, view = api_ir01.call(f"/api/engine/runs/{run_id}/view")
    assert status == 200
    store = api_ir01.service.store(run_id)
    assert "NOTES.md" not in [f["canonical_path"] for f in
                              store.get_revision(store.get_run(run_id)["observed_revision"])["files"]]
    assert view["editDenied"]["action"] == "deny"


def test_ir01_followup_http_delegation_view_remains_valid(api_ir01):
    run_id = _create_http_run(
        api_ir01,
        EXPLICIT + " Compare these solutions, but do not apply any patch.",
        "http-delegation",
    )
    _wait_settled(api_ir01, run_id)
    status, view = api_ir01.call(f"/api/engine/runs/{run_id}/view")
    assert status == 200
    assert view["delegations"]
    assert all("edit" in item["exclusions"] for item in view["delegations"])
    store = api_ir01.service.store(run_id)
    assert "NOTES.md" not in [f["canonical_path"] for f in
                              store.get_revision(store.get_run(run_id)["observed_revision"])["files"]]
