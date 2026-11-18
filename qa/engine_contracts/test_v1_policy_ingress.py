"""V1 safe effects and author ingress."""
from __future__ import annotations

import json
import os
import pathlib
import tempfile

import pytest

from engine.policy import (
    LOCAL_ACTOR,
    PolicyDenied,
    capability,
    canonical_workspace_path,
    classify_free_text,
    classify_input_barrier,
    render_text_escaped,
)
from engine.schemas import validate_response_payload
from engine.store import IdempotencyConflict
from qa.engine_contracts.harness import Harness, plan, script


def test_canonical_paths_fail_closed(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    assert canonical_workspace_path(root, "a/b.txt") == (root / "a" / "b.txt").resolve()
    for bad in ("../escape.txt", "/etc/passwd", "C:\\windows\\x", "a/../../b", "a\x00b",
                "CON", "aux.txt", "trailing."):
        with pytest.raises(PolicyDenied):
            canonical_workspace_path(root, bad)
    # Case-insensitive collision on Windows semantics.
    (root / "A").write_text("x", encoding="utf-8")
    with pytest.raises(PolicyDenied):
        canonical_workspace_path(root, "a")


def test_capability_matrix_and_unknown_principal():
    engine = capability("author-engine")
    assert engine.can_execute and not engine.can_approve
    assert "differential_search" in engine.operation_kinds
    review = capability("review-mode")
    assert review.can_mutate is False and review.can_approve is False
    with pytest.raises(PolicyDenied):
        capability("root")


def test_barrier_classification_is_deterministic():
    assert classify_input_barrier("set_engagement", {"engagement": "together"}) is False
    assert classify_input_barrier("set_engagement", {"explanation_depth": "brief"}) is False
    assert classify_input_barrier("respond", {"kind": "request_explanation"}) is False
    assert classify_input_barrier("respond", {"kind": "semantic_choice"}) is True
    assert classify_input_barrier("steer", None) is True
    assert classify_input_barrier("contribute", None) is True
    assert classify_input_barrier("cancel", None) is True
    with pytest.raises(PolicyDenied):
        classify_input_barrier("set_engagement", {"engagement": "brief", "grant": "all"})


def test_free_text_interpretation_is_a_proposal_not_authority():
    result = classify_free_text("work with me briefly and use half-open endpoints")
    assert result["depth"] == "brief"
    assert result["engagement"] == "together"
    assert result["endpointSemantics"] == "half_open"
    ambiguous = classify_free_text("make them touch differently")
    assert ambiguous["endpointSemantics"] is None


def test_render_escaped_never_trusts_html():
    payload = '<img src=x onerror="alert(1)"><script>bad()</script>'
    escaped = render_text_escaped(payload)
    assert "<" not in escaped and ">" not in escaped
    assert "&lt;img" in escaped and "&lt;script&gt;" in escaped


def test_response_payload_rejects_extra_authority():
    with pytest.raises(Exception):
        validate_response_payload("semantic_choice", {
            "requirement_id": "x", "option_id": "a", "grant": "edit",
        })
    with pytest.raises(Exception):
        validate_response_payload("semantic_choice", {"requirement_id": "x"})
    validate_response_payload("approach_preference", {"approach_id": "sweep"})


def test_input_received_before_applied_and_idempotent(harness: Harness):
    run_id = harness.create("Help with bookings.", seed={"goalText": "Help with bookings."})
    first = harness.service.submit_input(run_id, {
        "kind": "steer", "text": "Use brief explanations.",
        "clientRequestId": "k-1", "expectedGeneration": 0,
    }, schedule=False)
    assert first["status"] == "received"
    duplicate = harness.service.submit_input(run_id, {
        "kind": "steer", "text": "Use brief explanations.",
        "clientRequestId": "k-1", "expectedGeneration": 0,
    }, schedule=False)
    assert duplicate == first
    with pytest.raises(IdempotencyConflict):
        harness.service.submit_input(run_id, {
            "kind": "steer", "text": "A different body.",
            "clientRequestId": "k-1", "expectedGeneration": 0,
        }, schedule=False)
    store = harness.store(run_id)
    assert store.get_run(run_id)["steering_epoch"] >= 1  # barrier is durable before ack
    before = store.get_input(first["inputId"])
    assert before["status"] == "received"
    harness.pump(run_id)
    after = store.get_input(first["inputId"])
    assert after["status"] in ("applied", "needs_disambiguation", "conflict")
    assert after["applied_at"]


def test_typed_preference_does_not_advance_barrier(harness: Harness):
    run_id = harness.create()
    before = harness.store(run_id).get_run(run_id)["steering_epoch"]
    receipt = harness.service.submit_input(run_id, {
        "kind": "set_engagement",
        "payload": {"engagement": "delegated", "explanation_depth": "brief"},
        "clientRequestId": "pref-1",
    }, schedule=False)
    assert receipt["barrier"] is False
    assert harness.store(run_id).get_run(run_id)["steering_epoch"] == before
    harness.pump(run_id)
    collab = harness.view(run_id)["collaboration"]
    assert collab["engagement"] == "delegated"
    assert collab["explanation_depth"] == "brief"


def test_explanation_request_keeps_semantic_decision_pending(harness: Harness):
    run_id = harness.create()
    harness.pump(run_id)
    decision = harness.view(run_id)["pendingDecision"]
    assert decision is not None
    receipt = harness.respond(run_id, decision, "request_explanation",
                              {"target_ref": decision["id"], "question": "Why does this matter?"})
    assert receipt["status"] == "receipt"
    harness.pump(run_id, rounds=6)
    pending = harness.store(run_id).pending_interaction(run_id)
    assert pending is not None, "an explanation request must not settle the semantic decision"
    assert pending["id"] == decision["id"]


def test_contribution_original_preserved_and_duplicate_deduped(harness: Harness):
    run_id = harness.create("Help me with a lemma.", seed={"goalText": "Help me with a lemma."})
    content = "Lemma: every schedule without job i lies in prefix i-1.\n"
    receipt = harness.service.submit_input(run_id, {
        "kind": "contribute", "clientRequestId": "c-1",
        "payload": {"contributionKind": "lemma", "content": content, "attribution": "author"},
    }, schedule=False)
    harness.pump(run_id)
    duplicate = harness.service.submit_input(run_id, {
        "kind": "contribute", "clientRequestId": "c-2",
        "payload": {"contributionKind": "lemma", "content": content, "attribution": "author"},
    }, schedule=False)
    harness.pump(run_id)
    store = harness.store(run_id)
    contributions = store.list_contributions(run_id)
    assert len(contributions) == 1, "same content/kind/actor must not duplicate credit"
    contribution = contributions[0]
    assert store.get_blob(contribution["original_blob_hash"]).decode("utf-8") == content
    assert contribution["actor_kind"] == "human"
    assert contribution["attribution"] == "author"


def test_unsafe_or_oversized_contribution_rejected_other_work_preserved(harness: Harness):
    run_id = harness.create("Help me.", seed={"goalText": "Help me."})
    with pytest.raises(PolicyDenied):
        harness.service.submit_input(run_id, {
            "kind": "contribute", "clientRequestId": "bad-1",
            "payload": {"contributionKind": "code", "content": "int main(){}", "path": "../../x.cpp"},
        }, schedule=False)
    with pytest.raises(PolicyDenied):
        harness.service.submit_input(run_id, {
            "kind": "contribute", "clientRequestId": "bad-2",
            "payload": {"contributionKind": "code", "content": "x" * (1024 * 1024 + 1)},
        }, schedule=False)
    ok = harness.service.submit_input(run_id, {
        "kind": "contribute", "clientRequestId": "ok-1",
        "payload": {"contributionKind": "test", "content": "2\n0 1 5\n1 2 7\n"},
    }, schedule=False)
    harness.pump(run_id)
    assert harness.store(run_id).list_contributions(run_id)
    assert ok["status"] == "received"
    # The unsafe inputs created no executable intent.
    assert all(i["kind"] != "contribute" or i["status"] != "applied"
               for i in harness.store(run_id).list_inputs(run_id)
               if i.get("payload") and i["payload"].get("content", "").startswith("x" * 10))


def test_actor_and_server_owned_fields_rejected(harness: Harness):
    run_id = harness.create()
    for field in ("actorId", "runId", "serverOwned", "controllerEpoch"):
        with pytest.raises(PolicyDenied):
            harness.service.submit_input(run_id, {
                "kind": "steer", "text": "hello", "clientRequestId": "a-" + field, field: "forged",
            }, schedule=False)


def test_explicit_delegation_creates_scope_without_extra_ceremony(harness: Harness):
    run_id = harness.create("Investigate earliest finish for at most 100 tiny cases. "
                            "Return the first valid counterexample and explanation; do not edit solutions.")
    harness.pump(run_id)
    store = harness.store(run_id)
    grant = store.active_grant(run_id)
    assert grant is not None
    assert "differential_search" in grant["operation_kinds"]
    assert "edit" not in grant["operation_kinds"]
    delegations = store.list_delegations(run_id)
    assert len(delegations) == 1
    delegation = delegations[0]
    assert delegation["return_kind"] == "first_valid_witness"
    assert "edit" in delegation["exclusions"]
    assert delegation["budget_ceiling"]["cases"] == 100
    # No repair-approval card was fabricated for an explicit scoped instruction.
    interactions = store.read_all("SELECT kind FROM interactions WHERE run_id=?", (run_id,))
    assert all(row["kind"] != "repair_review" for row in interactions)


def test_ambiguous_consequential_steer_creates_typed_question(harness: Harness):
    run_id = harness.create("Help me decide how jobs touch.")
    harness.pump(run_id)
    harness.answer_endpoint(run_id)
    harness.pump(run_id)
    receipt = harness.service.submit_input(run_id, {
        "kind": "steer", "text": "Make them touch differently.",
        "clientRequestId": "amb-1",
    }, schedule=False)
    assert receipt["barrier"] is True
    harness.pump(run_id)
    store = harness.store(run_id)
    inputs = store.list_inputs(run_id)
    ambiguous = [i for i in inputs if i["id"] == receipt["inputId"]][0]
    assert ambiguous["status"] in ("needs_disambiguation", "superseded", "conflict")
    # Dependent publication stays fenced and a concrete card or handoff exists;
    # no silent assumption is applied.
    assert store.get_run(run_id)["status"] in ("waiting_human", "awaiting_author", "incomplete")


def test_cross_run_blob_reference_rejected(harness: Harness):
    run_a = harness.create("Run A")
    run_b = harness.create("Run B")
    receipt = harness.service.submit_input(run_a, {
        "kind": "contribute", "clientRequestId": "blob-a",
        "payload": {"contributionKind": "code", "content": "int main(){}"},
    }, schedule=False)
    harness.pump(run_a)
    contribution = harness.store(run_a).list_contributions(run_a)[0]
    blob = contribution["original_blob_hash"]
    with pytest.raises(Exception):
        harness.service.submit_input(run_b, {
            "kind": "contribute", "clientRequestId": "blob-b",
            "payload": {"contributionKind": "code", "content": "x", "originalBlobRef": blob},
        }, schedule=False)


def test_oversized_text_and_bad_kind_rejected(harness: Harness):
    run_id = harness.create()
    with pytest.raises(PolicyDenied):
        harness.service.submit_input(run_id, {
            "kind": "steer", "text": "x" * 200_001, "clientRequestId": "big",
        }, schedule=False)
    with pytest.raises(PolicyDenied):
        harness.service.submit_input(run_id, {
            "kind": "execute_arbitrary", "text": "x", "clientRequestId": "kind",
        }, schedule=False)


def test_requirement_symbol_is_importable():
    # Guard against accidental module-level typos in the policy seam.
    assert LOCAL_ACTOR
