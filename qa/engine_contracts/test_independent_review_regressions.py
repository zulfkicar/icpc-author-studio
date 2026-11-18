"""Regressions for the independent V0-V3 review (IR01-IR05).

Each test exercises the actual host policy, compiled graph, application ledger
or real HTTP boundary.  Fake models generate adversarial proposals and record
requests; they do not implement policy or context assembly.  The IR05 transport
is mocked because no live worker is authorized.
"""
from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request

import pytest
from http.server import HTTPServer

import server
from engine.clock import CrashInjected
from engine.domain import Instance, Job
from engine.interpretation import interpret_authorization, interpret_semantics
from engine.model import FakeModelAdapter
from engine.policy import classify_free_text
from engine.protocol import normalize_isolate_case
from engine.service import EngineService
from engine.worker import FakeWorker, IsolateWorker
from qa.engine_contracts.harness import FIXTURES, Harness, plan, script

EXPLICIT = "Use half-open intervals."


def _revision_files(harness: Harness, run_id: str) -> list[str]:
    store = harness.store(run_id)
    revision = store.get_revision(store.get_run(run_id)["observed_revision"])
    return [item["canonical_path"] for item in revision["files"]]


def _edit_grants(harness: Harness, run_id: str) -> list[dict]:
    rows = harness.store(run_id).read_all(
        "SELECT id, operation_kinds_json, scope_json, revoked_at FROM grants WHERE run_id=?",
        (run_id,),
    )
    return [{"id": row["id"],
             "kinds": json.loads(row["operation_kinds_json"] or "[]"),
             "scope": json.loads(row["scope_json"] or "[]"),
             "revokedAt": row["revoked_at"]} for row in rows]


# ---------------------------------------------------------------- IR01
def test_ir01_negated_initial_instruction_cannot_publish_model_edit(tmp_path):
    h = Harness(root=tmp_path / "ir01-initial", script=script(plan=[
        plan("edit", args={"path": "NOTES.md", "after": "unauthorized\n"}),
        plan("finish"),
    ]))
    rid = h.create("Use half-open intervals. Compare these solutions, but do not apply any patch.")
    h.pump(rid)
    store = h.store(rid)
    assert "NOTES.md" not in _revision_files(h, rid)
    assert not [e for e in store.list_evidence(rid) if e["outcome"] == "patch"]
    grants = _edit_grants(h, rid)
    assert all("edit" not in grant["kinds"] for grant in grants)
    assert store.get_run(rid)["status"] in ("incomplete", "awaiting_author", "blocked")
    h.close()


@pytest.mark.parametrize("instruction", [
    "Do not apply any patch to NOTES.md.",
    "Don't patch anything.",
    "Only compare the solutions; do not change files.",
    "Is a repair needed for NOTES.md?",
    'He wrote "apply the patch to NOTES.md" as an example, but it is a quotation.',
])
def test_ir01_steering_negation_question_and_quotation_do_not_authorize_edits(tmp_path, instruction):
    h = Harness(root=tmp_path / f"ir01-steer-{abs(hash(instruction))}", script=script(plan=[
        plan("finish"),
    ]))
    rid = h.create(EXPLICIT)
    h.pump(rid)
    h.model._script["plan"] = [
        plan("edit", args={"path": "NOTES.md", "after": "hostile\n"}),
        plan("finish"),
    ]
    h.service.submit_input(rid, {"kind": "steer", "text": instruction,
                                 "clientRequestId": "ir01-steer"}, schedule=False)
    h.pump(rid)
    store = h.store(rid)
    assert "NOTES.md" not in _revision_files(h, rid)
    assert not [e for e in store.list_evidence(rid) if e["outcome"] == "patch"]
    assert all("edit" not in grant["kinds"] for grant in _edit_grants(h, rid))
    h.close()


def test_ir01_explicit_scoped_instruction_publishes_without_redundant_approval(tmp_path):
    h = Harness(root=tmp_path / "ir01-grant", script=script(plan=[
        plan("edit", args={"path": "NOTES.md", "after": "authorized note\n"}),
        plan("finish"),
    ]))
    rid = h.create("Use half-open intervals. Apply a patch to NOTES.md.")
    h.pump(rid)
    store = h.store(rid)
    assert "NOTES.md" in _revision_files(h, rid)
    assert store.pending_interaction(rid) is None
    patches = [e for e in store.list_evidence(rid) if e["outcome"] == "patch"]
    assert len(patches) == 1
    assert any("edit" in grant["kinds"] and "path:NOTES.md" in grant["scope"]
               for grant in _edit_grants(h, rid))
    h.close()


def test_ir01_out_of_scope_edit_is_denied(tmp_path):
    h = Harness(root=tmp_path / "ir01-scope", script=script(plan=[
        plan("edit", args={"path": "solution.cpp", "after": "int main(){}\n"}),
        plan("finish"),
    ]))
    rid = h.create("Use half-open intervals. Apply a patch to NOTES.md.")
    h.pump(rid)
    store = h.store(rid)
    assert "solution.cpp" not in _revision_files(h, rid)
    assert not [e for e in store.list_evidence(rid) if e["outcome"] == "patch"]
    h.close()


def test_ir01_revocation_fences_inflight_publication_and_keeps_history(tmp_path):
    h = Harness(root=tmp_path / "ir01-revoke", script=script(plan=[
        plan("edit", args={"path": "NOTES.md", "after": "authorized note\n"}),
        plan("finish"),
    ]))
    rid = h.create("Use half-open intervals. Apply a patch to NOTES.md.")
    h.service.failpoints.arm("editing.before_publish")
    with pytest.raises(CrashInjected):
        h.pump(rid)
    assert "NOTES.md" not in _revision_files(h, rid)
    h.service.submit_input(rid, {"kind": "steer", "text": "Revoke the edit permission.",
                                 "clientRequestId": "ir01-revoke"}, schedule=False)
    h.pump(rid)
    store = h.store(rid)
    assert "NOTES.md" not in _revision_files(h, rid)
    grants = _edit_grants(h, rid)
    assert any(grant["revokedAt"] for grant in grants if "edit" in grant["kinds"])
    events = [e for e in store.events_after(rid, 0, 300)
              if e["type"] == "edit_authority_revoked"]
    assert events and events[0]["payload"]["historyPreserved"] is True
    h.close()


def test_ir01_followup_delegation_does_not_broaden_existing_edit_scope(tmp_path):
    h = Harness(root=tmp_path / "ir01-scope-preserve", script=script(plan=[plan("finish")]))
    rid = h.create("Use half-open intervals. Apply a patch to NOTES.md.")
    h.pump(rid)
    h.service.submit_input(rid, {
        "kind": "steer",
        "text": "Investigate for at most 10 cases; return a counterexample; no edits.",
        "clientRequestId": "scope-preserve",
    }, schedule=False)
    h.pump(rid)
    h.model._script["plan"] = [
        plan("edit", args={"path": "solution.cpp", "after": "int main(){}\n"}),
        plan("finish"),
    ]
    h.service.submit_input(rid, {"kind": "steer", "text": "Continue.",
                                 "clientRequestId": "scope-continue"}, schedule=False)
    h.pump(rid)
    assert "solution.cpp" not in _revision_files(h, rid)
    assert not [e for e in h.store(rid).list_evidence(rid) if e["outcome"] == "patch"]
    h.close()


def test_ir01_duplicate_replay_does_not_duplicate_patch(tmp_path):
    h = Harness(root=tmp_path / "ir01-replay", script=script(plan=[
        plan("edit", args={"path": "NOTES.md", "after": "one note\n"}),
        plan("finish"),
    ]))
    rid = h.create("Use half-open intervals. Apply a patch to NOTES.md.")
    h.pump(rid)
    store = h.store(rid)
    first = [e for e in store.list_evidence(rid) if e["outcome"] == "patch"]
    revision = store.get_run(rid)["observed_revision"]
    for _ in range(2):
        h.pump(rid)
    assert store.get_run(rid)["observed_revision"] == revision
    assert len([e for e in store.list_evidence(rid) if e["outcome"] == "patch"]) == 1
    # The same client key and body cannot create a second effect.
    body = {"kind": "steer", "text": "Apply a patch to NOTES.md.",
            "clientRequestId": "same-effect"}
    first_receipt = h.service.submit_input(rid, body, schedule=False)
    second_receipt = h.service.submit_input(rid, body, schedule=False)
    assert first_receipt["inputId"] == second_receipt["inputId"]
    h.close()


def test_ir01_replay_after_publish_crash_does_not_duplicate_revision(tmp_path):
    h = Harness(root=tmp_path / "ir01-replay-crash", script=script(plan=[
        plan("edit", args={"path": "NOTES.md", "after": "one note\n"}),
        plan("finish"),
    ]))
    rid = h.create("Use half-open intervals. Apply a patch to NOTES.md.")
    h.service.failpoints.arm("editing.after_publish_before_checkpoint")
    with pytest.raises(CrashInjected):
        h.pump(rid)
    store = h.store(rid)
    revisions = store.read_all("SELECT id FROM revisions WHERE run_id=?", (rid,))
    patches = [e for e in store.list_evidence(rid) if e["outcome"] == "patch"]
    assert "NOTES.md" in _revision_files(h, rid)
    assert len(patches) == 1
    h.pump(rid)
    assert len(store.read_all("SELECT id FROM revisions WHERE run_id=?", (rid,))) == len(revisions)
    assert len([e for e in store.list_evidence(rid) if e["outcome"] == "patch"]) == 1
    h.close()


def test_ir01_model_proposal_cannot_expand_host_scope(tmp_path):
    h = Harness(root=tmp_path / "ir01-hostile", script=script(plan=[
        plan("edit", args={"path": "solution.cpp", "after": "int main(){}\n",
                           "grant_scope_ref": "path:*", "scope": ["path:*"]}),
        plan("finish"),
    ]))
    rid = h.create("Use half-open intervals. Apply a patch to NOTES.md.")
    h.pump(rid)
    store = h.store(rid)
    assert "solution.cpp" not in _revision_files(h, rid)
    assert not [e for e in store.list_evidence(rid) if e["outcome"] == "patch"]
    assert all(grant["scope"] != ["path:*"] for grant in _edit_grants(h, rid)
               if "edit" in grant["kinds"])
    h.close()


# ---------------------------------------------------------------- IR02
def test_ir02_negated_closed_intervals_retain_half_open(tmp_path):
    h = Harness(root=tmp_path / "ir02-negated", script=script(plan=[plan("finish")]))
    rid = h.create(EXPLICIT + " Help me develop bookings.")
    h.pump(rid)
    h.service.submit_input(rid, {"kind": "steer", "text": "Do not use closed intervals.",
                                 "clientRequestId": "ir02-neg"}, schedule=False)
    h.pump(rid)
    store = h.store(rid)
    collab = json.loads(store.get_run(rid)["collaboration_json"])
    decisions = [(d["requirementId"], d["optionId"]) for d in collab["decisions"]]
    assert ("endpoint_semantics", "half_open") in decisions
    assert ("endpoint_semantics", "closed") not in decisions
    assert store.get_run(rid)["goal_generation"] == 0
    h.close()


@pytest.mark.parametrize("text", [
    "Maybe closed intervals?",
    "Perhaps use closed intervals?",
    "Should we use closed intervals?",
    "The statement says 'closed intervals' — is that what we use?",
    "Be brief, maybe use closed intervals?",
])
def test_ir02_tentative_question_or_quoted_endpoint_requests_clarification(tmp_path, text):
    h = Harness(root=tmp_path / f"ir02-clarify-{abs(hash(text))}", script=script(plan=[plan("finish")]))
    rid = h.create(EXPLICIT + " Help me develop bookings.")
    h.pump(rid)
    receipt = h.service.submit_input(rid, {"kind": "steer", "text": text,
                                          "clientRequestId": "ir02-clarify"}, schedule=False)
    assert receipt["barrier"] is True
    h.pump(rid)
    store = h.store(rid)
    collab = json.loads(store.get_run(rid)["collaboration_json"])
    decisions = [(d["requirementId"], d["optionId"]) for d in collab["decisions"]]
    assert ("endpoint_semantics", "closed") not in decisions
    assert store.get_run(rid)["goal_generation"] == 0
    pending = store.pending_interaction(rid)
    assert pending is not None and pending["kind"] == "semantics"
    assert store.get_input(receipt["inputId"])["status"] == "needs_disambiguation"
    h.close()


def test_ir02_explicit_change_applies_once_and_invalidates_evidence(tmp_path):
    h = Harness(root=tmp_path / "ir02-explicit", script=script(plan=[
        plan("investigate", args={"candidate_ref": "fixture:earliest_finish_greedy",
                                  "claim_id": "H1",
                                  "domain": {"kind": "witness", "name": "weighted_greedy"}}),
        plan("finish"),
    ]))
    rid = h.create(EXPLICIT)
    h.pump(rid)
    store = h.store(rid)
    assert [e for e in store.list_evidence(rid) if e["freshness"] == "current"]
    h.service.submit_input(rid, {"kind": "steer", "text": "I meant closed intervals.",
                                 "clientRequestId": "ir02-close-1"}, schedule=False)
    h.pump(rid)
    collab = json.loads(store.get_run(rid)["collaboration_json"])
    closed = [d for d in collab["decisions"] if d.get("optionId") == "closed"]
    assert len(closed) == 1
    assert store.get_run(rid)["goal_generation"] == 1
    assert all(e["freshness"] == "stale" for e in store.list_evidence(rid))
    h.service.submit_input(rid, {"kind": "steer", "text": "Use closed intervals.",
                                 "clientRequestId": "ir02-close-2"}, schedule=False)
    h.pump(rid)
    collab = json.loads(store.get_run(rid)["collaboration_json"])
    assert len([d for d in collab["decisions"] if d.get("optionId") == "closed"]) == 1
    assert store.get_run(rid)["goal_generation"] == 1
    h.close()


def test_ir02_pending_semantic_interpretation_fences_inflight_receipt(tmp_path):
    from engine.worker import FakeWorker

    h = Harness(script(plan=[
        plan("investigate", args={"candidate_ref": "fixture:earliest_finish_greedy",
                                  "claim_id": "H1",
                                  "domain": {"kind": "witness", "name": "weighted_greedy"}}),
        plan("finish"),
    ]), worker=FakeWorker(deferred=True), root=tmp_path / "ir02-fence")
    rid = h.create(EXPLICIT)
    h.pump(rid)
    operation = h.store(rid).list_operations(rid)[0]
    receipt = h.service.submit_input(rid, {"kind": "steer", "text": "Maybe closed intervals?",
                                          "clientRequestId": "ir02-fence"}, schedule=False)
    assert receipt["barrier"] is True
    h.service.settle_worker("job:" + operation["operation_id"], schedule=False)
    h.pump(rid)
    store = h.store(rid)
    pending = store.pending_interaction(rid)
    assert pending is not None and pending["kind"] == "semantics"
    assert not [e for e in store.list_evidence(rid)
                if e["classification"] == "counterexample" and e["freshness"] == "current"]
    collab = json.loads(store.get_run(rid)["collaboration_json"])
    assert not [d for d in collab["decisions"] if d.get("optionId") == "closed"]
    h.close()


def test_ir02_interpretation_unit_separates_mention_from_decision():
    assert interpret_semantics("Do not use closed intervals").endpoint is None
    assert interpret_semantics("Maybe closed intervals?").ambiguous is True
    assert interpret_semantics("I meant closed intervals.").endpoint == "closed"
    assert interpret_semantics("closed intervals", initial=False).ambiguous is True
    assert classify_free_text("Be brief, maybe use closed intervals?")["semanticAmbiguous"] is True
    assert classify_free_text("Use brief explanations.")["semanticAmbiguous"] is False


# ---------------------------------------------------------------- IR03
def _request_context(harness: Harness, node: str) -> dict:
    calls = [call for call in harness.model.calls if call.get("node") == node]
    assert calls, f"no captured request for {node}"
    return calls[-1]["context"]


def test_ir03_planning_and_collaboration_receive_resource_and_author_text(tmp_path):
    h = Harness(root=tmp_path / "ir03-content", script=script(plan=[
        plan("collaborate", args={"procedure": "COL-COMPARE",
                                  "resources": ["proof/prefix"],
                                  "question": "Compare the author lemma."}),
        plan("finish"),
    ]))
    rid = h.create(EXPLICIT)
    h.service.create_contribution(rid, {
        "contributionKind": "lemma",
        "content": "CANARY-LEMMA-9f3 every valid schedule omits job i",
        "attribution": "author",
    })
    h.service.create_contribution(rid, {
        "contributionKind": "code",
        "content": "CANARY-CODE-a71 int main(){return 0;}",
        "attribution": "author",
    })
    h.pump(rid)
    compose = _request_context(h, "collaboration.compose")
    blob = json.dumps(compose)
    assert "CANARY-LEMMA-9f3" in blob
    assert "CANARY-CODE-a71" in blob
    assert "do not discard an unconventional" in blob.lower()
    assert "Compatible prefix obligation" in blob
    assert compose["selectedMethods"]["selected"]
    method = compose["selectedMethods"]["selected"][0]
    assert method["sha256"] and method["version"] and method["range"] == [0, method["chars"]]
    contribution = compose["authorContext"]["contributions"][0]
    assert contribution["sha256"] and contribution["blobSha256"]
    assert contribution["revision"] == compose["authorContext"]["currentRevision"]
    assert contribution["untrusted"] is True
    # The planning request also has the author's original text, not only an ID.
    planning = _request_context(h, "plan")
    assert "CANARY-LEMMA-9f3" in json.dumps(planning)
    assert "procedureIndex" in planning
    assert compose["contextBudget"]["chars"] <= compose["contextBudget"]["maxChars"]
    h.close()


def test_ir03_stale_revision_content_is_omitted(tmp_path):
    h = Harness(root=tmp_path / "ir03-stale", script=script(plan=[plan("finish")]))
    rid = h.create(EXPLICIT)
    h.service.create_contribution(rid, {
        "contributionKind": "lemma",
        "content": "STALE-CANARY-44 old revision lemma",
        "attribution": "author",
    })
    h.service.submit_input(rid, {"kind": "steer", "text": "I meant closed intervals.",
                                 "clientRequestId": "ir03-stale-change"}, schedule=False)
    h.pump(rid)
    h.model._script["plan"] = [
        plan("collaborate", args={"procedure": "COL-COMPARE", "question": "Compare."}),
        plan("finish"),
    ]
    h.service.submit_input(rid, {"kind": "steer", "text": "Explain the current state.",
                                 "clientRequestId": "ir03-stale-explain"}, schedule=False)
    h.pump(rid)
    compose = _request_context(h, "collaboration.compose")
    assert "STALE-CANARY-44" not in json.dumps(compose)
    assert any(item.get("reason") == "stale_revision"
               for item in compose["authorContext"]["omitted"])
    h.close()


def test_ir03_unselected_and_cross_run_content_do_not_leak(tmp_path):
    h = Harness(root=tmp_path / "ir03-scope", script=script(plan=[
        plan("collaborate", args={"procedure": "COL-COMPARE",
                                  "resources": ["proof/prefix"], "question": "Compare."}),
        plan("finish"),
    ]))
    rid = h.create(EXPLICIT)
    other = h.create(EXPLICIT + " Second run")
    h.service.create_contribution(other, {
        "contributionKind": "lemma", "content": "CROSS-RUN-CANARY-51"})
    h.service.create_contribution(rid, {
        "contributionKind": "lemma", "content": "LOCAL-CANARY-51", "attribution": "author"})
    h.pump(rid)
    compose = _request_context(h, "collaboration.compose")
    blob = json.dumps(compose)
    assert "CROSS-RUN-CANARY-51" not in blob
    assert "LOCAL-CANARY-51" in blob
    # The unselected subset-oracle resource text is not delivered.
    assert "Independent subset oracle" not in blob
    h.close()


def test_ir03_oversized_contribution_is_truncated_and_bounded(tmp_path):
    h = Harness(root=tmp_path / "ir03-big", script=script(plan=[
        plan("collaborate", args={"procedure": "COL-COMPARE", "question": "Compare."}),
        plan("finish"),
    ]))
    rid = h.create(EXPLICIT)
    h.service.create_contribution(rid, {
        "contributionKind": "lemma",
        "content": "BIG-CANARY " + ("x" * 200_000),
        "attribution": "author",
    })
    h.pump(rid)
    compose = _request_context(h, "collaboration.compose")
    assert compose["authorContext"]["chars"] <= compose["authorContext"]["maxChars"]
    item = compose["authorContext"]["contributions"][0]
    assert item["truncated"] is True
    assert item["chars"] <= 6000
    assert item["continuation"]
    assert len(item["text"]) <= 6000
    h.close()


# ---------------------------------------------------------------- IR04
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

    def call(self, path, method="GET", body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None

        def attempt():
            request = urllib.request.Request(
                self.base + path, data=data, method=method,
                headers={"Content-Type": "application/json"} if data else {},
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    return response.status, json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                return exc.code, json.loads(exc.read().decode("utf-8"))

        last = None
        for _ in range(3 if method == "GET" else 1):
            try:
                return attempt()
            except (ConnectionAbortedError, ConnectionResetError) as exc:
                last = exc
                import time
                time.sleep(0.05)
        if last is not None:
            raise last
        return attempt()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.service.close()
        server.ENGINE_SERVICE = None


@pytest.fixture()
def api_edit(tmp_path):
    service = EngineService(
        tmp_path / "ir04-root",
        model_adapter=FakeModelAdapter(script=script(plan=[
            plan("edit", args={"path": "NOTES.md", "after": "unauthorized\n"}),
            plan("finish"),
        ])),
        worker=FakeWorker(), fixture_dir=str(FIXTURES),
    )
    httpd = _Http(service)
    yield httpd
    httpd.close()


def test_ir04_http_view_serializes_delegation_states_and_restart(api_edit):
    call = api_edit.call
    status, created = call("/api/engine/runs", "POST", {
        "workspaceId": "ir04", "idea": EXPLICIT + " Help me.",
        "clientRequestId": "ir04-create",
    })
    assert status == 201
    run_id = created["runId"]
    status, no_delegation = call(f"/api/engine/runs/{run_id}/view")
    assert status == 200
    assert no_delegation["delegations"] == []
    store = api_edit.service.store(run_id)
    grant = store.create_grant(run_id, actor_id="local-author", source_input_id="ir04",
                               operation_kinds=["read_artifact"], scope=["path:NOTES.md"],
                               goal_generation=0)
    base = {
        "objective": "Active review", "permitted_operations": ["read_artifact"],
        "exclusions": ["export", "edit"], "claim_scope": ["H1"],
        "budget_ceiling": {"cases": 12, "wallSeconds": 30},
        "deadline": "2030-01-01T00:00:00+00:00",
        "return_predicate": {"kind": "first_valid_witness", "caseCap": 12},
        "grant_ref": grant["id"], "return_kind": "first_valid_witness",
        "return_target_refs": ["H1"], "required_evidence_kinds": ["diagnostic_witness"],
    }
    records = [
        store.create_delegation(run_id, **base),
        store.create_delegation(run_id, **{**base, "objective": "Completed review"}),
        store.create_delegation(run_id, **{**base, "objective": "Revoked review"}),
        store.create_delegation(run_id, **{**base, "objective": "Expired review",
                                           "deadline": "2020-01-01T00:00:00+00:00"}),
    ]
    store.set_delegation_status(records[1]["id"], "returned")
    store.set_delegation_status(records[2]["id"], "revoked")
    status, view = call(f"/api/engine/runs/{run_id}/view")
    assert status == 200
    by_objective = {item["objective"]: item for item in view["delegations"]}
    assert set(by_objective) == {"Active review", "Completed review", "Revoked review", "Expired review"}
    active = by_objective["Active review"]
    assert active["permittedOperations"] == ["read_artifact"]
    assert active["exclusions"] == ["export", "edit"]
    assert active["claimScope"] == ["H1"]
    assert active["returnKind"] == "first_valid_witness"
    assert active["returnPredicate"]["caseCap"] == 12
    assert active["budgetCeiling"] == {"cases": 12, "wallSeconds": 30}
    assert active["requiredEvidenceKinds"] == ["diagnostic_witness"]
    assert active["grantRef"] == grant["id"]
    assert by_objective["Completed review"]["status"] == "returned"
    assert by_objective["Revoked review"]["status"] == "revoked"
    assert by_objective["Expired review"]["expired"] is True
    # Restart the service against the same root and view the same records.
    root = api_edit.service.base_root
    api_edit.service.close()
    service2 = EngineService(root, model_adapter=FakeModelAdapter(script=script()),
                             worker=FakeWorker(), fixture_dir=str(FIXTURES))
    server.ENGINE_SERVICE = service2
    status, view2 = call(f"/api/engine/runs/{run_id}/view")
    assert status == 200
    assert {item["objective"] for item in view2["delegations"]} == set(by_objective)
    assert view2["delegations"][0]["permittedOperations"] == ["read_artifact"]
    api_edit.service = service2


def test_ir04_no_patch_http_journey_has_valid_view_and_no_delegation_error(api_edit):
    call = api_edit.call
    status, created = call("/api/engine/runs", "POST", {
        "workspaceId": "ir04", "idea": "Use half-open intervals. Compare these solutions, "
                                      "but do not apply any patch.",
        "clientRequestId": "ir04-no-patch",
    })
    assert status == 201
    run_id = created["runId"]
    view = {}
    for _ in range(80):
        status, view = call(f"/api/engine/runs/{run_id}/view")
        assert status == 200
        if view["status"] in ("incomplete", "awaiting_author", "stage_returned"):
            break
        import time
        time.sleep(0.1)
    assert view["status"] in ("incomplete", "awaiting_author", "stage_returned")
    assert view["delegations"] and all("edit" in item["exclusions"] or
                                       "edit" not in item["permittedOperations"]
                                       for item in view["delegations"])
    store = api_edit.service.store(run_id)
    revision = store.get_revision(store.get_run(run_id)["observed_revision"])
    assert "NOTES.md" not in [item["canonical_path"] for item in revision["files"]]


def test_ir04_corrupt_delegation_fails_explicitly(tmp_path):
    service = EngineService(tmp_path / "ir04-corrupt",
                            model_adapter=FakeModelAdapter(script=script()),
                            worker=FakeWorker(), fixture_dir=str(FIXTURES))
    httpd = _Http(service)
    try:
        status, created = httpd.call("/api/engine/runs", "POST", {
            "workspaceId": "ir04", "idea": EXPLICIT,
            "clientRequestId": "ir04-corrupt",
        })
        assert status == 201
        run_id = created["runId"]
        store = service.store(run_id)
        grant = store.create_grant(run_id, actor_id="local-author", source_input_id="x",
                                   operation_kinds=["read_artifact"], scope=[], goal_generation=0)
        delegation = store.create_delegation(
            run_id, objective="Corrupt me", permitted_operations=["read_artifact"],
            exclusions=[], claim_scope=[], budget_ceiling={}, deadline=None,
            return_predicate={"kind": "campaign_complete"}, grant_ref=grant["id"],
            return_kind="campaign_complete", return_target_refs=[],
            required_evidence_kinds=[],
        )
        with store.tx() as conn:
            conn.execute("UPDATE delegations SET permitted_json=? WHERE id=?",
                         ("{not-json", delegation["id"]))
        status, body = httpd.call(f"/api/engine/runs/{run_id}/view")
        assert status == 409
        assert "Corrupt delegation" in body["error"]
    finally:
        httpd.close()


# ---------------------------------------------------------------- IR05
def _mock_success(**overrides):
    value = {"status": "OK", "exit": 0, "stdout": "12\n", "stderr": "", "time": 0.01,
             "wallTime": 0.02, "memory": 2048, "compileOutput": "", "message": "",
             "ok": True}
    value.update(overrides)
    return value


def test_ir05_success_ok_exit_zero_normalizes_and_evaluates(monkeypatch):
    import isolate_client

    responses = [_mock_success()]
    monkeypatch.setattr(isolate_client, "configured", lambda: True)
    monkeypatch.setattr(isolate_client, "run", lambda *a, **k: responses.pop(0))
    worker = IsolateWorker()
    raw = worker.submit({
        "job_id": "j", "candidate": {"source": "int main(){}", "language": "cpp"},
        "cases": [{"case_id": "c0", "input": "1\n0 1 12\n"}],
        "budget": {"wall_ms": 60000, "memory_mib": 256},
    })
    assert raw["status"] == "completed"
    assert raw["cases"][0]["status"] == "ok"
    assert raw["cases"][0]["rawStatus"] == "OK"
    assert raw["cases"][0]["usage"]["time_ms"] == 10.0
    from engine.graph import _evaluate_campaign
    evaluation = _evaluate_campaign(None, raw, [Instance((Job(0, 1, 12, 0),))])
    assert evaluation["classification"] == "agreement"
    assert evaluation["complete"] is True
    wrong_raw = {**raw, "cases": [{**raw["cases"][0], "output": "7"}]}
    wrong = _evaluate_campaign(None, wrong_raw, [Instance((Job(0, 1, 12, 0),))])
    assert wrong["classification"] == "counterexample"
    assert wrong["complete"] is True


def test_ir05_protocol_failures_remain_distinct(monkeypatch):
    import isolate_client

    monkeypatch.setattr(isolate_client, "configured", lambda: True)
    outcomes = {
        "wrong": _mock_success(stdout="7\n"),
        "nonzero": _mock_success(status="OK", exit=1),
        "compile": _mock_success(status="CE", exit=1, compileOutput="error: bad"),
        "timeout": _mock_success(status="TO", exit=-1, stdout=""),
        "memory": _mock_success(status="RE", exit=-1, message="Memory limit exceeded"),
        "missing": {"exit": 0, "stdout": "12"},
        "bad_exit": _mock_success(exit="not-an-int"),
        "truncated": _mock_success(status="OK", exit=0, stdout="1" * 70000),
    }
    for name, response in outcomes.items():
        monkeypatch.setattr(isolate_client, "run", lambda *a, **k: response)
        raw = IsolateWorker().submit({
            "job_id": name, "candidate": {"source": "int main(){}", "language": "cpp"},
            "cases": [{"case_id": "c0", "input": "1\n0 1 12\n"}],
            "budget": {"wall_ms": 60000, "memory_mib": 256},
        })
        if name == "wrong":
            # A wrong answer is a successful execution; the campaign classifies it.
            assert raw["status"] == "completed" and raw["cases"][0]["status"] == "ok"
            continue
        status = raw["cases"][0]["status"] if raw.get("cases") else raw["status"]
        assert status != "ok", (name, raw)
    # Exact classifications for representative cases.
    assert normalize_isolate_case(_mock_success(stdout="7"))["status"] == "ok"
    assert normalize_isolate_case(_mock_success(exit=1))["status"] == "candidate_runtime_error"
    assert normalize_isolate_case(_mock_success(status="CE", exit=1))["status"] == "compile_error"
    assert normalize_isolate_case(_mock_success(status="TO"))["status"] == "time_limit"
    assert normalize_isolate_case(_mock_success(status="RE", message="Memory limit exceeded"))["status"] == "memory_limit"
    assert normalize_isolate_case({"exit": 0})["status"] == "worker_protocol_error"
    assert normalize_isolate_case(_mock_success(exit="x"))["status"] == "worker_protocol_error"
    assert normalize_isolate_case(None)["status"] == "worker_protocol_error"
    assert normalize_isolate_case(_mock_success(status="PENDING"))["status"] == "pending"
    assert normalize_isolate_case(_mock_success(status="CANCELLED"))["status"] == "cancelled"
    assert normalize_isolate_case(_mock_success(status="UNKNOWN"))["status"] == "outcome_unknown"
    assert normalize_isolate_case(_mock_success())["usage"]["memory_mb"] == 2.0
    bounded = normalize_isolate_case(_mock_success(stderr="e" * 5000,
                                                    compileOutput="c" * 5000,
                                                    message="m" * 5000))
    assert len(bounded["stderr"]) == 2000 and bounded["stderrTruncated"] is True
    assert len(bounded["compileOutput"]) == 2000 and bounded["compileOutputTruncated"] is True
    assert len(bounded["message"]) == 2000 and bounded["messageTruncated"] is True


def test_ir05_transport_failure_fails_closed_without_native_fallback(monkeypatch, tmp_path):
    import isolate_client

    monkeypatch.setattr(isolate_client, "configured", lambda: True)

    def boom(*args, **kwargs):
        raise RuntimeError("transport disconnected")

    monkeypatch.setattr(isolate_client, "run", boom)
    raw = IsolateWorker().submit({
        "job_id": "transport", "candidate": {"source": "int main(){}", "language": "cpp"},
        "cases": [{"case_id": "c0", "input": "1\n0 1 12\n"}],
        "budget": {"wall_ms": 60000, "memory_mib": 256},
    })
    assert raw["status"] == "failed"
    assert raw["classification"] == "infrastructure_error"
    assert raw["cases"] == []
    assert raw["usage"]["unknown"] is True
    # Configured is not qualified.
    description = IsolateWorker().describe()
    assert description["configured"] is True
    assert description["qualified"] is False
    service = EngineService(tmp_path / "ir05-capabilities", worker=IsolateWorker(),
                            model_adapter=FakeModelAdapter(script=script()),
                            fixture_dir=str(FIXTURES))
    capabilities = service.capabilities()
    assert capabilities["workerConfigured"] is True
    assert capabilities["workerQualified"] is False
    service.close()


def test_ir05_truncated_batch_cannot_become_agreement(monkeypatch):
    import isolate_client

    monkeypatch.setattr(isolate_client, "configured", lambda: True)
    monkeypatch.setattr(isolate_client, "run", lambda *a, **k: _mock_success(stdout="12\n"))
    worker = IsolateWorker(batch_limit=1)
    raw = worker.submit({
        "job_id": "truncated", "candidate": {"source": "int main(){}", "language": "cpp"},
        "cases": [{"case_id": "c0", "input": "1\n0 1 12\n"},
                  {"case_id": "c1", "input": "1\n0 1 12\n"}],
        "budget": {"wall_ms": 60000, "memory_mib": 256},
    })
    assert raw["status"] == "incomplete"
    assert raw["truncation"]["requested"] == 2
    from engine.graph import _evaluate_campaign
    evaluation = _evaluate_campaign(None, raw, [Instance((Job(0, 1, 12, 0),)),
                                                Instance((Job(0, 1, 12, 0),))])
    assert evaluation["complete"] is False
    assert evaluation["classification"] == "resource_exhausted"


# ---------------------------------------------------------------- interpretation units
def test_authorization_unit_distinguishes_moods():
    assert interpret_authorization("Apply a patch to NOTES.md.").action == "grant"
    assert interpret_authorization("Apply a patch to NOTES.md.").scope_paths == ("NOTES.md",)
    assert interpret_authorization("Apply a patch to `NOTES.md`.").scope_paths == ("NOTES.md",)
    assert interpret_authorization("Do not apply any patch.").action == "deny"
    assert interpret_authorization("Don't patch anything.").action == "deny"
    assert interpret_authorization("Only compare the solutions.").action == "deny"
    assert interpret_authorization("Is a repair needed?").action == "none"
    assert interpret_authorization('He said "apply the patch" as an example.').action == "none"
    assert interpret_authorization("Maybe patch NOTES.md?").action == "ambiguous"
    assert interpret_authorization("Revoke the edit permission.").action == "revoke"
