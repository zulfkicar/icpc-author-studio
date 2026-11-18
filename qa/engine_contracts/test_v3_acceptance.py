"""V3 executable acceptance: C01-C12 and CR01, CR04, CR07, CR08, CR10.

Every assertion is bound to production paths (engine.graph, engine.input_service,
engine.diagnostic, engine.store).  C09/C10 additional schedules live in
test_v2_durability.py and test_api_boundary.py.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from engine.domain import Instance, Job, parse_instance
from engine.schemas import ApprovalV1
from engine.stage import evaluate_stage_return
from engine.store import IdempotencyConflict
from qa.engine_contracts.harness import FIXTURES, Harness, plan, script

EXPLICIT = "Maximise total reward over compatible half-open booking intervals; positive duration; duplicates allowed."
MISSING = "Help me develop profitable bookings; work with me, briefly."


def witness_plan(candidate="fixture:earliest_finish_greedy", witness="weighted_greedy",
                 claim="H1", **extra):
    return plan("investigate", args={"candidate_ref": candidate, "claim_id": claim,
                                     "domain": {"kind": "witness", "name": witness}, **extra},
                requested_budget={"cases": 1})


def campaign_plan(candidate, claim="H1", lengths=(1, 2, 3), **extra):
    return plan("investigate", args={
        "candidate_ref": candidate, "claim_id": claim,
        "domain": {"kind": "finite", "lengths": list(lengths)}, **extra,
    }, requested_budget={"cases": 400})


def add_contribution(h: Harness, run_id: str, content: str, kind: str = "code",
                     key: str | None = None, attribution: str = "author") -> str:
    h.service.submit_input(run_id, {
        "kind": "contribute", "clientRequestId": key or ("c-" + str(len(content))),
        "payload": {"contributionKind": kind, "content": content, "attribution": attribution},
    }, schedule=False)
    h.pump(run_id)
    return h.store(run_id).list_contributions(run_id)[-1]["id"]


def fixture_text(name: str) -> str:
    return (FIXTURES / f"{name}.cpp").read_text(encoding="utf-8")


# ---------------------------------------------------------------- C01
def test_c01_ask_missing_endpoint_once_and_preserve_decision(tmp_path):
    h = Harness(root=tmp_path / "c01", script=script(plan=[plan("finish")]))
    rid = h.create(MISSING)
    h.pump(rid)
    first = h.view(rid)["pendingDecision"]
    assert first is not None and first["kind"] == "semantics"
    h.answer_endpoint(rid)
    h.pump(rid)
    store = h.store(rid)
    decisions = store.get_run(rid)["collaboration_json"]
    assert "half_open" in decisions
    interactions = store.read_all("SELECT kind, status FROM interactions WHERE run_id=?", (rid,))
    assert len(interactions) == 1 and interactions[0]["status"] == "answered"
    # No dependent execution occurred before the choice.
    assert not store.list_evidence(rid)
    h.service.submit_input(rid, {"kind": "steer", "text": "Continue with brief explanations.",
                                 "clientRequestId": "c01-next"}, schedule=False)
    h.pump(rid)
    assert len(store.read_all("SELECT id FROM interactions WHERE run_id=?", (rid,))) == 1
    h.close()


def test_c01_explicit_endpoint_control_gets_no_question(tmp_path):
    h = Harness(root=tmp_path / "c01b", script=script(plan=[plan("finish")]))
    rid = h.create(EXPLICIT)
    h.pump(rid)
    store = h.store(rid)
    assert store.pending_interaction(rid) is None
    assert not store.read_all("SELECT id FROM interactions WHERE run_id=?", (rid,))
    assert h.view(rid)["goalGeneration"] == 0
    h.close()


# ---------------------------------------------------------------- C02
def test_c02_fairly_refute_weighted_greedy_and_explain(tmp_path):
    h = Harness(root=tmp_path / "c02", script=script(plan=[
        witness_plan(), plan("collaborate", args={"procedure": "COL-EXPLAIN",
                                                   "question": "Why does earliest finish fail?"}),
        plan("finish"),
    ]))
    rid = h.create(EXPLICIT)
    h.pump(rid)
    store = h.store(rid)
    witness = next(iter(store.list_evidence(rid)))
    artifact = json.loads(store.get_blob(witness["artifact_refs"][0]).decode("utf-8"))
    assert artifact["expected"] == 13 and artifact["actual"] == 12
    assert artifact["legal"] is True
    findings = store.list_findings(rid)
    assert findings and findings[0]["claim_id"] == "H1" and findings[0]["status"] == "open"
    explanation = store.current_explanation(rid)
    assert explanation is not None
    assert "weight" in (explanation["short_answer"] + explanation["question"]).lower()
    h.close()


def test_c02_valid_unconventional_sweep_line_survives(tmp_path):
    h = Harness(root=tmp_path / "c02b", script=script(plan=[plan("finish")]))
    rid = h.create(EXPLICIT)
    content = fixture_text("sweep_line_correct")
    contribution = h.service.create_contribution(rid, {
        "contributionKind": "code", "content": content, "attribution": "author",
    })
    h.model._script["plan"] = [
        campaign_plan("contribution:" + contribution["id"]),
        plan("finish"),
    ]
    h.pump(rid)
    store = h.store(rid)
    evidence = store.list_evidence(rid)
    assert evidence and evidence[0]["classification"] == "agreement"
    artifact = json.loads(store.get_blob(evidence[0]["artifact_refs"][0]).decode("utf-8"))
    assert artifact["complete"] is True
    assert artifact["declared"] == artifact["completed"] == 258
    assert store.list_findings(rid) == []
    assert store.get_contribution(contribution["id"])["validation_status"] == "tested"
    h.close()


# ---------------------------------------------------------------- C03
def test_c03_preserve_valid_lemma_and_challenge_false_prefix_claim(tmp_path):
    h = Harness(root=tmp_path / "c03", script=script(plan=[plan("finish")]))
    rid = h.create(EXPLICIT)
    valid_lemma = "Lemma: any schedule that omits job i is bounded by the optimum of prefix i-1."
    false_claim = ("Claim: if job i is chosen, every earlier job is compatible with i, so the whole "
                   "prefix i-1 is available.")
    valid = h.service.create_contribution(rid, {
        "contributionKind": "lemma", "content": valid_lemma, "attribution": "author"})
    false_contribution = h.service.create_contribution(rid, {
        "contributionKind": "lemma", "content": false_claim, "attribution": "author"})
    false_id = false_contribution["id"]
    h.model._script["plan"] = [
        plan("collaborate", args={"procedure": "COL-PROOF", "claim_check": "compatible_prefix_all",
                                  "contribution_id": false_id, "witness": "conflict_pair",
                                  "question": "Is the compatible-prefix claim justified?"}),
        plan("finish"),
    ]
    h.pump(rid)
    store = h.store(rid)
    findings = store.list_findings(rid)
    assert findings and findings[0]["claim_id"] == false_id and findings[0]["status"] == "open"
    assert "Conflicting pair" in findings[0]["allegation"]
    false_stored = store.get_contribution(false_id)
    assert false_stored["validation_status"] == "unvalidated"
    assert store.get_blob(false_stored["original_blob_hash"]).decode() == false_claim
    valid_stored = store.get_contribution(valid["id"])
    assert store.get_blob(valid_stored["original_blob_hash"]).decode() == valid_lemma
    explanation = store.current_explanation(rid)
    assert explanation and "compatible" in explanation["short_answer"]
    h.close()


# ---------------------------------------------------------------- C04
def test_c04_human_originals_survive_derived_edits_and_restart(tmp_path):
    h = Harness(root=tmp_path / "c04", script=script(plan=[plan("finish")]))
    rid = h.create(EXPLICIT)
    code = fixture_text("dp_strict")
    cid = add_contribution(h, rid, code, kind="code", key="orig-code")
    original = h.store(rid).get_contribution(cid)
    blob_before = h.store(rid).get_blob(original["original_blob_hash"])
    # Agent-derived artifact references do not rewrite the original.
    h.close()
    h2 = Harness(root=tmp_path / "c04", script=script(plan=[plan("finish")]))
    reopened = h2.store(rid).get_contribution(cid)
    assert reopened["original_blob_hash"] == original["original_blob_hash"]
    assert h2.store(rid).get_blob(reopened["original_blob_hash"]) == blob_before
    assert reopened["actor_kind"] == "human" and reopened["attribution"] == "author"
    h2.close()


# ---------------------------------------------------------------- C05
def test_c05_explain_legal_touching_witness_and_code_link(tmp_path):
    h = Harness(root=tmp_path / "c05", script=script(plan=[
        witness_plan("fixture:dp_strict", "touching"), 
        plan("collaborate", args={"procedure": "COL-EXPLAIN", "question": "Why 12 vs 7?"}),
        plan("finish"),
    ]))
    rid = h.create(EXPLICIT)
    h.pump(rid)
    store = h.store(rid)
    explanation = store.current_explanation(rid)
    assert explanation is not None
    assert "12" in explanation["short_answer"] and "7" in explanation["short_answer"]
    assert "touch" in explanation["short_answer"].lower() or "predecessor" in explanation["short_answer"].lower()
    assert explanation["worked_example_ref"]
    assert explanation["assumption_to_code_links"]
    assert explanation["evidence_refs"]
    h.close()


def test_c05_invalid_zero_duration_test_is_not_a_refutation(tmp_path):
    h = Harness(root=tmp_path / "c05b", script=script(plan=[plan("finish")]))
    rid = h.create(EXPLICIT)
    contribution = h.service.create_contribution(rid, {
        "contributionKind": "test", "content": "1\n0 0 5\n"})
    cid = contribution["id"]
    h.model._script["plan"] = [plan("collaborate", args={
        "procedure": "COL-TEST", "contribution_id": cid, "expected": 5,
    }), plan("finish")]
    h.pump(rid)
    store = h.store(rid)
    assert store.get_contribution(cid)["validation_status"] == "invalid"
    findings = store.list_findings(rid)
    assert findings and "Invalid" in findings[0]["allegation"]
    assert not [e for e in store.list_evidence(rid) if e["classification"] == "counterexample"]
    h.close()


def test_c05_shared_oracle_error_is_investigated_not_used_to_patch(tmp_path):
    h = Harness(root=tmp_path / "c05c", script=script(plan=[
        plan("investigate", args={"candidate_ref": "fixture:dp_strict", "claim_id": "H1",
                                  "oracle_semantics": "closed",
                                  "domain": {"kind": "witness", "name": "touching"}}),
        plan("finish"),
    ]))
    rid = h.create(EXPLICIT)
    h.pump(rid)
    store = h.store(rid)
    evidence = store.list_evidence(rid)
    assert evidence and evidence[0]["classification"] == "shared_semantics_defect"
    findings = store.list_findings(rid)
    assert findings and findings[0]["claim_id"].startswith("oracle-")
    assert "share an endpoint assumption" in findings[0]["allegation"]
    assert store.current_explanation(rid) is not None
    assert not [e for e in store.list_evidence(rid) if e["outcome"] == "patch"]
    h.close()


# ---------------------------------------------------------------- C08
def test_c08_delegated_witness_returns_without_implementing_dp(tmp_path):
    h = Harness(root=tmp_path / "c08", script=script(plan=[
        witness_plan(), plan("edit", args={"path": "solution.cpp", "after": "int main(){}"}),
    ]))
    rid = h.create(EXPLICIT + " Investigate whether earliest finish maximises reward for at most 100 "
                              "tiny cases; return the first valid counterexample and explanation; "
                              "do not edit solutions.")
    h.pump(rid)
    store = h.store(rid)
    handoff = store.latest_handoff(rid)
    assert handoff["outcome"] == "stage_returned"
    assert handoff["stage_return"]["contract"]["kind"] == "first_valid_witness"
    assert handoff["stage_return"]["satisfied"] is True
    assert store.get_run(rid)["status"] == "stage_returned"
    assert not [e for e in store.list_evidence(rid) if e["outcome"] == "patch"]
    assert not store.read_all("SELECT id FROM interactions WHERE run_id=? AND kind='repair_review'", (rid,))
    h.close()


def test_c08_delegation_expiry_returns_incomplete_and_forged_wake_blocked(tmp_path):
    h = Harness(root=tmp_path / "c08b", script=script(plan=[witness_plan(), plan("finish")]))
    rid = h.create(EXPLICIT)
    store = h.store(rid)
    inputs = h.service.runtime(rid).inputs
    parsed = inputs.interpret_delegation(
        "Investigate for at most 100 cases; return a counterexample and explanation; no edits.")
    grant = store.create_grant(rid, actor_id="local-author", source_input_id="expiry",
                               operation_kinds=parsed["permittedOperations"],
                               scope=["author-visible"], goal_generation=0)
    store.create_delegation(
        rid, objective=parsed["objective"],
        permitted_operations=parsed["permittedOperations"], exclusions=parsed["exclusions"],
        claim_scope=parsed["claimScope"], budget_ceiling=parsed["budgetCeiling"],
        deadline="2020-01-01T00:00:00+00:00", return_predicate=parsed["returnPredicate"],
        grant_ref=grant["id"], return_kind=parsed["returnKind"],
        return_target_refs=[], required_evidence_kinds=["diagnostic_witness"],
    )
    h.pump(rid)
    handoff = store.latest_handoff(rid)
    assert handoff["outcome"] == "incomplete"
    assert not [e for e in store.list_evidence(rid) if e["freshness"] == "current"]
    from engine.graph import Runtime as GraphRuntime, _validate_wake
    with pytest.raises(Exception):
        _validate_wake(h.service.runtime(rid), rid,
                       {"wake_id": "forged", "reason": "worker_receipt"}, "operation:x")
    h.close()


# ---------------------------------------------------------------- C09
def test_c09_author_edits_repair_diff_then_publishes_new_hash(tmp_path):
    h = Harness(root=tmp_path / "c09", script=script(plan=[
        plan("edit", args={"path": "solution.cpp", "after": "int main(){return 1;}\n"}),
        plan("finish"),
    ]))
    rid = h.create(EXPLICIT)
    h.pump(rid)
    store = h.store(rid)
    card = store.pending_interaction(rid)
    assert card is not None and card["kind"] == "repair_review"
    receipt = h.service.submit_response(rid, card["id"], {
        "clientRequestId": "edit-ui-path",
        "kind": "edit_proposal",
        "payload": {"base_proposal_hash": card["proposal_hash"],
                    "replacement_text": "int main(){return 2;}\n"},
        "expectedRevision": card["revision"],
        "expectedGoalGeneration": card["goal_generation"],
        "expectedProposalHash": card["proposal_hash"],
    }, schedule=False)
    assert receipt["status"] == "receipt"
    h.pump(rid)
    run = store.get_run(rid)
    revision = store.get_revision(run["observed_revision"])
    assert revision["id"] != "rev-0"
    file = next(f for f in revision["files"] if f["canonical_path"] == "solution.cpp")
    assert store.get_blob(file["hash"]).decode() == "int main(){return 2;}\n"
    assert store.list_evidence(rid)[0]["outcome"] == "patch"
    # The edited proposal receives a new hash and is the published revision.
    assert store.pending_interaction(rid) is None
    assert store.latest_handoff(rid)["outcome"] == "awaiting_author"
    h.close()


def test_c09_reject_repair_preserves_source_and_ends_stage(tmp_path):
    h = Harness(root=tmp_path / "c09b", script=script(plan=[
        plan("edit", args={"path": "solution.cpp", "after": "int main(){return 1;}\n"}),
        plan("finish"),
    ]))
    rid = h.create(EXPLICIT)
    h.pump(rid)
    store = h.store(rid)
    card = store.pending_interaction(rid)
    h.respond(rid, card, "reject", {"target_ref": card["id"], "reason": "keep the original"})
    h.pump(rid)
    assert store.get_run(rid)["observed_revision"] == "rev-0"
    assert not [e for e in store.list_evidence(rid) if e["outcome"] == "patch"]
    assert store.latest_handoff(rid)["outcome"] in ("awaiting_author", "incomplete")
    h.close()


def test_c09_patch_review_is_fenced_by_later_semantic_input(tmp_path):
    h = Harness(root=tmp_path / "c09-order", script=script(plan=[
        plan("edit", args={"path": "solution.cpp", "after": "int main(){return 1;}\n"}),
        plan("finish"),
    ]))
    rid = h.create(EXPLICIT)
    h.pump(rid)
    store = h.store(rid)
    card = store.pending_interaction(rid)
    assert card is not None
    # Input wins before the patch is applied: the card is superseded and no
    # stale diff may publish.
    h.service.submit_input(rid, {"kind": "steer", "text": "I meant closed intervals.",
                                 "clientRequestId": "patch-order"}, schedule=False)
    h.pump(rid)
    receipt = h.respond(rid, card, "edit_proposal", {
        "base_proposal_hash": card["proposal_hash"],
        "replacement_blob_ref": store.put_blob(b"int main(){return 2;}\n", kind="patch-content"),
    }, key="late-edit")
    assert receipt["status"] == "conflict"
    h.pump(rid)
    revision = store.get_revision(store.get_run(rid)["observed_revision"])
    assert not [f for f in revision["files"] if f["canonical_path"] == "solution.cpp"]
    assert not [e for e in store.list_evidence(rid) if e["outcome"] == "patch"]
    h.close()


def test_c09_patch_commit_wins_then_steering_invalidates_patch_evidence(tmp_path):
    h = Harness(root=tmp_path / "c09-order2", script=script(plan=[
        plan("edit", args={"path": "solution.cpp", "after": "int main(){return 1;}\n"}),
        plan("finish"),
    ]))
    rid = h.create(EXPLICIT)
    h.pump(rid)
    store = h.store(rid)
    card = store.pending_interaction(rid)
    h.respond(rid, card, "edit_proposal", {
        "base_proposal_hash": card["proposal_hash"],
        "replacement_blob_ref": store.put_blob(b"int main(){return 2;}\n", kind="patch-content"),
    }, key="edit-commit")
    h.pump(rid)
    patches = [e for e in store.list_evidence(rid) if e["outcome"] == "patch"]
    assert patches and patches[0]["freshness"] == "current"
    h.service.submit_input(rid, {"kind": "steer", "text": "I meant closed intervals.",
                                 "clientRequestId": "after-patch"}, schedule=False)
    h.pump(rid)
    assert all(e["freshness"] == "stale" for e in store.list_evidence(rid))
    h.close()


def test_c09_patch_reviewed_stage_return_is_satisfied_by_an_explicit_edit(tmp_path):
    h = Harness(root=tmp_path / "c09-reviewed", script=script(plan=[
        plan("edit", args={"path": "solution.cpp", "after": "int main(){return 1;}\n"}),
        plan("finish"),
    ]))
    rid = h.create(EXPLICIT + " Review a patch for at most 100 cases; return a reviewed patch; no delivery.")
    h.pump(rid)
    store = h.store(rid)
    card = store.pending_interaction(rid)
    assert card is not None and card["kind"] == "repair_review"
    h.respond(rid, card, "edit_proposal", {
        "base_proposal_hash": card["proposal_hash"],
        "replacement_blob_ref": store.put_blob(b"int main(){return 3;}\n", kind="patch-content"),
    }, key="reviewed-edit")
    h.pump(rid)
    handoff = store.latest_handoff(rid)
    assert handoff["stage_return"]["contract"]["kind"] == "patch_reviewed"
    assert handoff["stage_return"]["satisfied"] is True
    assert handoff["outcome"] == "stage_returned"
    h.close()


def test_c09_stale_synthetic_approval_binding_is_rejected(tmp_path):
    h = Harness(root=tmp_path / "c09c", script=script(plan=[plan("finish")]))
    rid = h.create(EXPLICIT)
    store = h.store(rid)
    manifest = "a" * 64
    approval = store.create_approval(rid, ApprovalV1(
        id="approval-1", run_id=rid, human_actor="author", revision="rev-0",
        action_kind="export", effect_manifest_hash=manifest, evidence_root_hash="root",
        goal_generation=0, steering_epoch=0, profile_hash="p", decision="approve",
    ))
    ok = store.check_approval_binding("approval-1", expected_revision="rev-0",
                                      expected_goal_generation=0, expected_steering_epoch=0,
                                      expected_manifest_hash=manifest)
    assert ok["ok"] is True
    for kwargs, reason in (
        ({"expected_revision": "rev-1", "expected_goal_generation": 0,
          "expected_steering_epoch": 0, "expected_manifest_hash": manifest}, "revision"),
        ({"expected_revision": "rev-0", "expected_goal_generation": 1,
          "expected_steering_epoch": 0, "expected_manifest_hash": manifest}, "goal_generation"),
        ({"expected_revision": "rev-0", "expected_goal_generation": 0,
          "expected_steering_epoch": 1, "expected_manifest_hash": manifest}, "steering_epoch"),
        ({"expected_revision": "rev-0", "expected_goal_generation": 0,
          "expected_steering_epoch": 0, "expected_manifest_hash": "b" * 64}, "effect_manifest"),
    ):
        result = store.check_approval_binding("approval-1", **kwargs)
        assert result["ok"] is False and reason in result["reasons"]
    h.close()


# ---------------------------------------------------------------- C10 isolation
def test_c10_two_threads_do_not_leak_state(tmp_path):
    h = Harness(root=tmp_path / "c10", script=script(plan=[plan("finish"), plan("finish")]))
    run_a = h.create("Run A idea without endpoints")
    run_b = h.create("Run B idea without endpoints")
    h.pump(run_a)
    decision_a = h.view(run_a)["pendingDecision"]
    assert decision_a is not None
    with pytest.raises(Exception):
        h.service.submit_response(run_b, decision_a["id"], {
            "clientRequestId": "cross", "kind": "semantic_choice",
            "payload": {"requirement_id": "endpoint_semantics", "option_id": "half_open"},
            "expectedRevision": decision_a["revision"],
        }, schedule=False)
    assert h.view(run_b)["goalGeneration"] == 0
    h.pump(run_b)
    decision_b = h.view(run_b)["pendingDecision"]
    assert decision_b is not None
    # Each run keeps its own response ledger; B's answer cannot answer A's card.
    first_b = h.respond(run_b, decision_b, "semantic_choice",
                        {"requirement_id": "endpoint_semantics", "option_id": "closed"},
                        key="b-own")
    assert first_b["status"] == "receipt"
    assert h.view(run_a)["pendingDecision"] is not None
    h.close()


# ---------------------------------------------------------------- C11
def test_c11_depth_preference_changes_presentation_not_correctness(tmp_path):
    def explanation_links(depth: str) -> list:
        h = Harness(root=tmp_path / f"c11-{depth}", script=script(plan=[
            witness_plan(),
            plan("collaborate", args={"procedure": "COL-EXPLAIN", "question": "Why?"}),
            plan("finish"),
        ]))
        rid = h.create(EXPLICIT, seed={"engagement": {"explanation_depth": depth}})
        h.pump(rid)
        store = h.store(rid)
        evidence = store.list_evidence(rid)
        assert evidence and evidence[0]["classification"] == "counterexample"
        explanation = store.current_explanation(rid)
        assert explanation["audience_depth"] == depth
        h.close()
        return explanation["assumption_to_code_links"]

    assert explanation_links("brief") == []
    assert explanation_links("standard")
    # A preference is per run; no durable personality is inferred elsewhere.
    h = Harness(root=tmp_path / "c11-fresh", script=script(plan=[plan("finish")]))
    fresh = h.create(EXPLICIT)
    assert h.view(fresh)["collaboration"]["explanation_depth"] == "standard"
    h.close()


def test_c11_settled_question_is_not_asked_again(tmp_path):
    h = Harness(root=tmp_path / "c11b", script=script(plan=[plan("finish")]))
    rid = h.create(MISSING)
    h.pump(rid)
    h.answer_endpoint(rid)
    h.pump(rid)
    for _ in range(3):
        h.service.submit_input(rid, {"kind": "steer", "text": "What next?",
                                     "clientRequestId": "n" + str(_)}, schedule=False)
        h.pump(rid)
    interactions = h.store(rid).read_all("SELECT id FROM interactions WHERE run_id=?", (rid,))
    assert len(interactions) == 1
    h.close()


# ---------------------------------------------------------------- C12
def test_c12_declined_extra_reference_gets_scoped_explanation(tmp_path):
    h = Harness(root=tmp_path / "c12", script=script(plan=[
        witness_plan(),
        plan("collaborate", args={"procedure": "COL-EXPLAIN",
                                  "question": "Skip the third reference; explain the DP idea."}),
        plan("finish"),
    ]))
    rid = h.create(EXPLICIT)
    h.pump(rid)
    store = h.store(rid)
    assert store.current_explanation(rid) is not None
    assert store.pending_interaction(rid) is None
    assert not [e for e in store.list_evidence(rid) if e["outcome"] == "patch"]
    assert not store.read_all("SELECT id FROM interactions WHERE run_id=? AND kind='repair_review'", (rid,))
    h.close()


# ---------------------------------------------------------------- CR01
def test_cr01_pending_reuses_continuation_and_reservation(tmp_path):
    from engine.worker import FakeWorker

    worker = FakeWorker(deferred=True)
    h = Harness(script(plan=[witness_plan(), plan("finish")]), worker=worker,
                root=tmp_path / "cr01")
    rid = h.create(EXPLICIT + " Investigate for at most 100 cases; return a counterexample; no edits.")
    out = h.pump(rid)
    assert out["status"] == "waiting"
    store = h.store(rid)
    continuation = json.loads(store.get_run(rid)["continuation_json"])
    operation = store.list_operations(rid)[0]
    reservation_id = operation["reservation_id"]
    assert len(store.read_all("SELECT id FROM reservations WHERE id=?", (reservation_id,))) == 1
    h.service.settle_worker("job:" + operation["operation_id"], schedule=False)
    h.pump(rid)
    # Interpret phase reused the same operation + reservation; no redesign.
    assert store.get_operation(operation["operation_id"])["status"] == "completed"
    assert len(store.list_operations(rid)) == 1
    assert store.get_operation(operation["operation_id"])["reservation_id"] == reservation_id
    assert store.latest_handoff(rid)["outcome"] == "stage_returned"
    h.close()


# ---------------------------------------------------------------- CR04
def test_cr04_typed_depth_preference_does_not_cancel_inflight_work(tmp_path):
    from engine.worker import FakeWorker

    h = Harness(script(plan=[witness_plan(), plan("finish")]),
                worker=FakeWorker(deferred=True), root=tmp_path / "cr04")
    rid = h.create(EXPLICIT + " Investigate for at most 100 cases; return a counterexample; no edits.")
    h.pump(rid)
    store = h.store(rid)
    epoch = store.get_run(rid)["steering_epoch"]
    continuation = store.get_run(rid)["continuation_json"]
    receipt = h.service.submit_input(rid, {
        "kind": "set_engagement",
        "payload": {"explanation_depth": "detailed", "engagement": "together"},
        "clientRequestId": "typed-control",
    }, schedule=False)
    assert receipt["barrier"] is False
    assert store.get_run(rid)["steering_epoch"] == epoch
    assert store.get_run(rid)["continuation_json"] == continuation
    operation = store.list_operations(rid)[0]
    h.service.settle_worker("job:" + operation["operation_id"], schedule=False)
    h.pump(rid)
    assert store.latest_handoff(rid)["outcome"] == "stage_returned"
    h.close()


# ---------------------------------------------------------------- CR07
def test_cr07_explanation_only_stops_without_new_experiment(tmp_path):
    h = Harness(root=tmp_path / "cr07", script=script(plan=[
        witness_plan(),
        plan("collaborate", args={"procedure": "COL-EXPLAIN", "question": "Why?"}),
        plan("collaborate", args={"procedure": "COL-EXPLAIN",
                                  "question": "Explain the same witness again briefly."}),
        plan("finish"),
    ]))
    rid = h.create(EXPLICIT)
    h.pump(rid)
    store = h.store(rid)
    operations = len(store.list_operations(rid))
    h.service.submit_input(rid, {"kind": "steer", "text": "Explain the witness again briefly.",
                                 "clientRequestId": "explain-again"}, schedule=False)
    h.pump(rid)
    assert len(store.list_operations(rid)) == operations
    assert store.current_explanation(rid) is not None
    assert not [e for e in store.list_evidence(rid) if e["outcome"] == "patch"]
    h.close()


def test_cr07_reviewed_dp_takes_direct_route_without_forced_greedy(tmp_path):
    h = Harness(root=tmp_path / "cr07b", script=script(plan=[plan("finish")]))
    rid = h.create(EXPLICIT + " The reviewed DP is supplied; compare it on tiny cases.")
    contribution = h.service.create_contribution(rid, {
        "contributionKind": "code", "content": fixture_text("dp_correct"),
        "attribution": "author"})
    h.model._script["plan"] = [campaign_plan("contribution:" + contribution["id"]), plan("finish")]
    h.pump(rid)
    h.pump(rid)
    store = h.store(rid)
    evidence = store.list_evidence(rid)
    assert evidence and evidence[0]["classification"] == "agreement"
    assert store.list_findings(rid) == []
    # No approach-choice card and no greedy hypothesis was imposed.
    assert not store.read_all("SELECT id FROM interactions WHERE run_id=? AND kind='approach_choice'", (rid,))
    h.close()


# ---------------------------------------------------------------- CR08
def test_cr08_actual_dp_base_defect_is_found(tmp_path):
    h = Harness(root=tmp_path / "cr08", script=script(plan=[
        campaign_plan("fixture:dp_base_error"),
        plan("finish"),
    ]))
    rid = h.create(EXPLICIT)
    h.pump(rid)
    store = h.store(rid)
    evidence = store.list_evidence(rid)
    assert evidence and evidence[0]["classification"] == "counterexample"
    assert store.list_findings(rid)
    h.close()


# ---------------------------------------------------------------- CR10
def test_cr10_stage_return_waits_for_author_and_export_has_no_effect(tmp_path):
    h = Harness(root=tmp_path / "cr10", script=script(plan=[witness_plan(), plan("finish")]))
    rid = h.create(EXPLICIT + " Investigate for at most 100 cases; return a counterexample; no edits.")
    h.pump(rid)
    store = h.store(rid)
    assert store.get_run(rid)["status"] == "stage_returned"
    operations = len(store.list_operations(rid))
    evidence = len(store.list_evidence(rid))
    events = len(store.events_after(rid, 0, 500))
    for _ in range(3):
        h.pump(rid)
    assert len(store.list_operations(rid)) == operations
    assert len(store.list_evidence(rid)) == evidence
    assert len(store.events_after(rid, 0, 500)) == events
    refusal = h.service.refuse(rid, "export")
    assert refusal["supported"] is False and refusal["effectsApplied"] == 0
    assert len(store.events_after(rid, 0, 500)) == events
    h.close()


# ---------------------------------------------------------------- two routes
def test_two_legitimate_routes_for_the_same_goal(tmp_path):
    # Route A: unresolved semantics -> question -> refuted greedy -> explanation.
    a = Harness(root=tmp_path / "route-a", script=script(plan=[
        witness_plan(), plan("collaborate", args={"procedure": "COL-EXPLAIN", "question": "Why?"}),
        plan("finish"),
    ]))
    rid_a = a.create(MISSING)
    a.pump(rid_a)
    assert a.view(rid_a)["pendingDecision"] is not None
    a.answer_endpoint(rid_a)
    a.pump(rid_a)
    assert a.store(rid_a).current_explanation(rid_a) is not None
    a.close()
    # Route B: explicit reviewed DP -> targeted correspondence campaign, no
    # forced approach discussion.
    b = Harness(root=tmp_path / "route-b", script=script(plan=[plan("finish")]))
    rid_b = b.create(EXPLICIT + " The reviewed DP is supplied.")
    contribution = b.service.create_contribution(rid_b, {
        "contributionKind": "code", "content": fixture_text("dp_correct")})
    b.model._script["plan"] = [campaign_plan("contribution:" + contribution["id"]), plan("finish")]
    b.pump(rid_b)
    assert b.store(rid_b).list_findings(rid_b) == []
    assert b.store(rid_b).list_evidence(rid_b)[0]["classification"] == "agreement"
    b.close()

def test_worker_deadline_expires_without_claiming_success(tmp_path):
    from engine.worker import FakeWorker

    h = Harness(script(plan=[witness_plan(), plan("finish")]),
                worker=FakeWorker(deferred=True), root=tmp_path / "deadline")
    rid = h.create(EXPLICIT)
    h.pump(rid)
    operation = h.store(rid).list_operations(rid)[0]
    assert operation["status"] == "pending"
    h.clock.advance(180)
    h.pump(rid)
    store = h.store(rid)
    expired = store.get_operation(operation["operation_id"])
    assert expired["status"] == "incomplete"
    assert expired["classification"] == "worker_deadline"
    assert not [e for e in store.list_evidence(rid) if e["freshness"] == "current"]
    assert store.latest_handoff(rid)["outcome"] == "incomplete"
    h.close()


def test_cancel_pending_worker_is_confirmed_and_denies_publication(tmp_path):
    from engine.worker import FakeWorker

    h = Harness(script(plan=[witness_plan(), plan("finish")]),
                worker=FakeWorker(deferred=True), root=tmp_path / "cancel-worker")
    rid = h.create(EXPLICIT)
    h.pump(rid)
    operation = h.store(rid).list_operations(rid)[0]
    h.service.submit_input(rid, {"kind": "cancel", "text": "stop the job",
                                 "clientRequestId": "cancel-job"}, schedule=False)
    h.pump(rid)
    store = h.store(rid)
    assert store.get_run(rid)["status"] == "cancelled"
    cancelled = store.get_operation(operation["operation_id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["classification"] == "cancelled_by_user"
    assert not [e for e in store.list_evidence(rid) if e["freshness"] == "current"]
    h.close()

def test_exhausted_model_still_returns_deterministic_explanation_without_extra_call(tmp_path):
    h = Harness(root=tmp_path / "exhausted", script=script(plan=[
        witness_plan(),
        plan("collaborate", args={"procedure": "COL-EXPLAIN", "question": "Why?"}),
        plan("finish"),
    ], **{"collaboration.compose": []}))
    rid = h.create(EXPLICIT)
    h.pump(rid)
    store = h.store(rid)
    explanation = store.current_explanation(rid)
    assert explanation is not None and "13" in explanation["short_answer"]
    compose_attempts = [
        e for e in store.events_after(rid, 0, 300)
        if e["type"] == "model_attempt" and (e["payload"] or {}).get("node") == "collaboration.compose"
    ]
    assert len(compose_attempts) == 3
    assert all((e["payload"] or {}).get("outcome") != "ok" for e in compose_attempts)
    # Unknown usage remains explicitly unknown; it is not reported as zero.
    assert store.budget_view(rid)["unknownUsage"] is True
    h.close()

def test_typed_campaign_complete_stage_return(tmp_path):
    h = Harness(root=tmp_path / "stage-campaign", script=script(plan=[
        campaign_plan("fixture:dp_correct", lengths=(1, 2, 3)),
        plan("finish"),
    ]))
    rid = h.create(EXPLICIT + " Run a completed campaign over the declared finite domain for at most "
                              "100 cases; no edits.")
    h.pump(rid)
    handoff = h.store(rid).latest_handoff(rid)
    assert handoff["stage_return"]["contract"]["kind"] == "campaign_complete"
    assert handoff["stage_return"]["satisfied"] is True
    assert handoff["outcome"] == "stage_returned"
    h.close()


def test_typed_explanation_delivered_stage_return(tmp_path):
    h = Harness(root=tmp_path / "stage-explanation", script=script(plan=[
        witness_plan(),
        plan("collaborate", args={"procedure": "COL-EXPLAIN", "question": "Why?"}),
        plan("finish"),
    ]))
    rid = h.create(EXPLICIT + " Investigate and explain why earliest finish fails; return the "
                              "explanation; no edits.")
    h.pump(rid)
    store = h.store(rid)
    handoff = store.latest_handoff(rid)
    assert handoff["stage_return"]["contract"]["kind"] == "explanation_delivered"
    assert handoff["stage_return"]["satisfied"] is True
    assert handoff["outcome"] == "stage_returned"
    assert store.current_explanation(rid) is not None
    h.close()
