"""V2 durable joint session, effects, wakes, projection and integrity schedules."""
from __future__ import annotations

import json
import pathlib
import tempfile

import pytest

from engine.clock import CrashInjected, ManualClock
from engine.projection import ProjectionManager
from engine.service import EngineService
from engine.store import ApplicationStore, IdempotencyConflict
from engine.graph import Runtime
from engine.budget import ModelGateway
from engine.input_service import InputService
from engine.model import FakeModelAdapter
from engine.worker import FakeWorker
from qa.engine_contracts.harness import FIXTURES, Harness, plan, script

IDEA = ("Maximise total reward over compatible half-open booking intervals. Labselled jobs, "
        "positive duration, duplicates allowed, output one integer.")
DELEGATE = ("Investigate whether earliest finish maximises reward for at most 100 tiny cases; "
            "return the first valid counterexample and explanation; do not edit solutions.")


def investigate(action_plan: dict | None = None) -> Harness:
    action_plan = action_plan or plan(
        "investigate",
        args={"candidate_ref": "fixture:earliest_finish_greedy", "claim_id": "H1",
              "domain": {"kind": "witness", "name": "weighted_greedy"}},
        requested_budget={"cases": 1},
    )
    return Harness(script(plan=[action_plan, plan("finish")]))


def start(harness: Harness, idea: str = IDEA + " " + DELEGATE) -> str:
    return harness.create(idea)


# ------------------------------------------------------------------ single owner
def test_os_lock_excludes_second_controller(tmp_path):
    from engine.lockfile import FileLock

    first = FileLock(tmp_path / "owner.lock")
    second = FileLock(tmp_path / "owner.lock")
    assert first.acquire() is True
    assert second.acquire() is False
    second.release()
    first.release()
    assert second.acquire() is True
    second.release()


def test_owner_epoch_advances_and_stale_owner_cannot_publish(tmp_path):
    h = investigate()
    rid = start(h)
    h.pump(rid)
    run = h.store(rid).get_run(rid)
    first_epoch = run["controller_epoch"]
    h.pump(rid)
    assert h.store(rid).get_run(rid)["controller_epoch"] == first_epoch + 1
    # A publication attempt carrying the old epoch is denied by the fence.
    from engine.graph import _publication_fence

    runtime = h.service.runtime(rid)
    operation = h.store(rid).list_operations(rid)[0]
    allowed, reasons = _publication_fence(runtime, operation, first_epoch,
                                          h.store(rid).get_run(rid))
    assert allowed is False and "controller_epoch" in reasons


# ------------------------------------------------------------------ crashes
def test_input_commit_before_checkpoint_crash_replays_once(tmp_path):
    h = Harness(root=tmp_path / "crash-input")
    rid = h.create(IDEA)
    h.page = None
    h.service.failpoints.arm("after_input_commit")
    with pytest.raises(CrashInjected):
        h.service.submit_input(rid, {"kind": "steer", "text": "Use half-open semantics.",
                                     "clientRequestId": "crash-input"}, schedule=False)
    input_id = h.store(rid).list_inputs(rid)[-1]["id"]
    assert h.store(rid).get_input(input_id)["status"] == "received"
    h.close()
    h2 = Harness(root=tmp_path / "crash-input")
    out = h2.pump(rid)
    assert h2.store(rid).get_input(input_id)["status"] in ("applied", "conflict",
                                                          "needs_disambiguation", "superseded")
    assert len(h2.store(rid).list_inputs(rid)) == 2  # no duplicate row on replay
    h2.close()


def test_receipt_commit_before_checkpoint_does_not_rerun_worker(tmp_path):
    h = investigate()
    rid = start(h)
    h.service.failpoints.arm("after_receipt_commit")
    with pytest.raises(CrashInjected):
        h.pump(rid)
    operation = h.store(rid).list_operations(rid)[0]
    assert operation["raw_receipt"] is not None
    assert len(h.worker.jobs) == 1
    h.close()
    # Restart with a fresh worker: the raw receipt must be consumed, not resubmitted.
    h2 = Harness(root=h.root)
    out = h2.pump(rid)
    assert len(h2.worker.jobs) == 0
    assert len(h2.store(rid).list_operations(rid)) == 1
    assert h2.store(rid).list_evidence(rid)
    h2.close()


def test_deferred_worker_waits_for_durable_receipt_then_interprets():
    worker = FakeWorker(deferred=True)
    h = Harness(script(plan=[
        plan("investigate", args={"candidate_ref": "fixture:earliest_finish_greedy",
                                  "claim_id": "H1",
                                  "domain": {"kind": "witness", "name": "weighted_greedy"}},
             requested_budget={"cases": 1}),
        plan("finish"),
    ]), worker=worker)
    rid = start(h)
    first = h.pump(rid)
    assert first["status"] == "waiting"
    assert "await_operation" in first["next"]
    operation = h.store(rid).list_operations(rid)[0]
    assert operation["status"] == "pending"
    settled = h.service.settle_worker("job:" + operation["operation_id"], schedule=False)
    assert settled["settled"] is True
    h.pump(rid)
    store = h.store(rid)
    assert store.get_operation(operation["operation_id"])["status"] == "completed"
    handoff = store.latest_handoff(rid)
    assert handoff and handoff["outcome"] == "stage_returned"
    h.close()


def test_unknown_worker_outcome_is_not_current_evidence():
    h = Harness(script(plan=[
        plan("investigate", args={"candidate_ref": "fixture:earliest_finish_greedy",
                                  "claim_id": "H1",
                                  "domain": {"kind": "witness", "name": "weighted_greedy"}}),
        plan("finish"),
    ]), worker=FakeWorker(failure={"outcome_unknown": True}))
    rid = start(h)
    h.pump(rid)
    store = h.store(rid)
    operation = store.list_operations(rid)[0]
    assert operation["status"] == "outcome_unknown"
    assert operation["raw_receipt"] is not None
    assert not [e for e in store.list_evidence(rid) if e["freshness"] == "current"]
    assert store.latest_handoff(rid)["outcome"] == "incomplete"
    assert store.budget_view(rid)["unknownUsage"] is True or operation["result"]["usage"]["unknown"]
    h.close()


def test_worker_unavailable_fails_closed_without_host_execution(tmp_path):
    from engine.worker import IsolateWorker

    h = Harness(script(plan=[
        plan("investigate", args={"candidate_ref": "fixture:earliest_finish_greedy",
                                  "claim_id": "H1",
                                  "domain": {"kind": "witness", "name": "weighted_greedy"}}),
        plan("finish"),
    ]), worker=IsolateWorker())
    rid = start(h)
    out = h.pump(rid)
    store = h.store(rid)
    operation = store.list_operations(rid)[0]
    assert operation["status"] == "failed"
    assert operation["classification"] == "infrastructure_error"
    assert not store.list_evidence(rid)
    assert store.latest_handoff(rid)["outcome"] == "incomplete"
    h.close()


# ------------------------------------------------------------------ wake outbox
def test_wake_consumption_is_exactly_once(tmp_path):
    store = ApplicationStore(tmp_path / "wake")
    run = store.create_run("w", "idea")
    store.append_input(run["run_id"], kind="steer", text="hello", client_request_id="k1")
    wake = store.next_pending_wake(run["run_id"])
    assert wake is not None
    first = store.consume_wake(wake["wake_id"], 1)
    second = store.consume_wake(wake["wake_id"], 2)
    assert first["wake_id"] == second["wake_id"]
    assert second["consumed_epoch"] == 1  # no second consumption effect
    assert store.next_pending_wake(run["run_id"]) is None


def test_forged_wake_and_raw_command_are_rejected(tmp_path):
    from engine.graph import Runtime as GraphRuntime, _validate_wake

    store = ApplicationStore(tmp_path / "forge")
    run = store.create_run("w", "idea")
    runtime = GraphRuntime(store=store, inputs=InputService(store),
                           gateway=ModelGateway(store, FakeModelAdapter(script={})),
                           worker=FakeWorker())
    with pytest.raises(Exception):
        _validate_wake(runtime, run["run_id"], {"wake_id": "forged", "reason": "worker_receipt"},
                       "operation:x")
    store.append_input(run["run_id"], kind="steer", text="x", client_request_id="k")
    wake = store.next_pending_wake(run["run_id"])
    with pytest.raises(Exception):
        _validate_wake(runtime, run["run_id"], {**wake, "reason": "worker_receipt"}, "operation:x")
    with pytest.raises(Exception):
        _validate_wake(runtime, "another-run", {**wake, "reason": "steering"}, wake["wait_id"])


# ------------------------------------------------------------------ steering / publication order
def test_input_wins_initial_publication_race(tmp_path):
    h = Harness(script(plan=[
        plan("investigate", args={"candidate_ref": "fixture:dp_strict", "claim_id": "H1",
                                  "domain": {"kind": "witness", "name": "touching"}}),
        plan("finish"),
    ]), root=tmp_path / "race-input")
    rid = start(h, IDEA + " Investigate for at most 100 cases; return a counterexample; no edits.")
    h.service.failpoints.arm("after_receipt_commit")
    with pytest.raises(CrashInjected):
        h.pump(rid)
    operation = h.store(rid).list_operations(rid)[0]
    raw_blob = operation["raw_receipt"]
    # The author corrects semantics before the publication commits.
    h.service.submit_input(rid, {"kind": "steer", "text": "I meant closed intervals.",
                                 "clientRequestId": "semantic-race"}, schedule=False)
    h.close()
    h2 = Harness(root=h.root, script=script(plan=[plan("finish")]))
    h2.pump(rid)
    store = h2.store(rid)
    run = store.get_run(rid)
    assert run["goal_generation"] >= 1
    assert all(e["freshness"] == "stale" for e in store.list_evidence(rid))
    assert store.get_operation(operation["operation_id"])["raw_receipt"] == raw_blob
    assert run["status"] in ("awaiting_author", "incomplete", "stage_returned")
    h2.close()


def test_publication_wins_then_steering_invalidates(tmp_path):
    h = Harness(script(plan=[
        plan("investigate", args={"candidate_ref": "fixture:earliest_finish_greedy",
                                  "claim_id": "H1",
                                  "domain": {"kind": "witness", "name": "weighted_greedy"}}),
        plan("collaborate", args={"procedure": "COL-EXPLAIN", "question": "Why?"}),
        plan("finish"),
    ]))
    rid = h.create(IDEA)
    h.pump(rid)
    store = h.store(rid)
    before = store.list_evidence(rid)
    assert before and before[0]["freshness"] == "current"
    assert store.current_explanation(rid) is not None
    h.service.submit_input(rid, {"kind": "steer", "text": "I meant closed intervals.",
                                 "clientRequestId": "late-semantic"}, schedule=False)
    h.pump(rid)
    after = store.list_evidence(rid)
    assert all(e["freshness"] == "stale" for e in after)
    assert store.current_explanation(rid) is None
    assert store.get_run(rid)["goal_generation"] >= 1
    # Historical receipt bytes are retained.
    assert after[0]["artifact_refs"]
    h.close()


# ------------------------------------------------------------------ C07 response lifecycle
def test_duplicate_and_changed_body_responses(tmp_path):
    h = Harness()
    rid = h.create()
    h.pump(rid)
    decision = h.view(rid)["pendingDecision"]
    payload = {"requirement_id": "endpoint_semantics", "option_id": "half_open"}
    first = h.respond(rid, decision, "semantic_choice", payload, key="same")
    second = h.respond(rid, decision, "semantic_choice", payload, key="same")
    assert first["responseId"] == second["responseId"]
    with pytest.raises(IdempotencyConflict):
        h.respond(rid, decision, "semantic_choice",
                  {"requirement_id": "endpoint_semantics", "option_id": "closed"}, key="same")
    store = h.store(rid)
    assert len(store.responses_for(decision["id"])) == 1
    h.pump(rid)
    assert store.get_run(rid)["goal_generation"] == 1
    events = [e["type"] for e in store.events_after(rid, 0, 200)]
    assert events.count("semantic_change") == 1
    h.close()


def test_stale_response_is_conflict_and_original_retained(tmp_path):
    h = Harness()
    rid = h.create()
    h.pump(rid)
    decision = h.view(rid)["pendingDecision"]
    receipt = h.service.submit_response(rid, decision["id"], {
        "clientRequestId": "stale-1",
        "kind": "semantic_choice",
        "payload": {"requirement_id": "endpoint_semantics", "option_id": "half_open"},
        "expectedRevision": "rev-does-not-exist",
        "expectedGoalGeneration": 99,
        "expectedProposalHash": "0" * 64,
    }, schedule=False)
    assert receipt["status"] == "conflict"
    assert set(receipt["stale"]) >= {"revision", "goal_generation", "proposal_hash"}
    store = h.store(rid)
    response = store.get_response(receipt["responseId"])
    assert response["applied"] == 0
    assert store.pending_interaction(rid) is not None
    h.pump(rid)
    assert store.pending_interaction(rid) is not None
    assert store.get_run(rid)["goal_generation"] == 0
    h.close()


def test_silence_never_approves(tmp_path):
    h = Harness()
    rid = h.create()
    h.pump(rid)
    h.clock.advance(3600)
    h.pump(rid)
    store = h.store(rid)
    assert store.pending_interaction(rid) is not None
    assert store.get_run(rid)["goal_generation"] == 0
    assert store.get_run(rid)["status"] == "waiting_human"
    assert not store.list_evidence(rid)
    h.close()


# ------------------------------------------------------------------ CR02 wake windows
@pytest.mark.parametrize("reason", ["response", "steering", "cancel"])
@pytest.mark.parametrize("window", ["before_pause", "after_pause", "after_resume",
                                    "duplicate_after_restart"])
def test_cr02_wake_windows(tmp_path, reason, window):
    name = f"cr02-{reason}-{window}"
    h = Harness(root=tmp_path / name)
    rid = h.create()

    def act(key: str) -> None:
        if reason == "response":
            h.respond(rid, h.store(rid).pending_interaction(rid), "semantic_choice",
                      {"requirement_id": "endpoint_semantics", "option_id": "half_open"},
                      key=key)
        elif reason == "steering":
            h.service.submit_input(rid, {"kind": "steer", "text": "I meant closed intervals.",
                                         "clientRequestId": key}, schedule=False)
        else:
            h.service.submit_input(rid, {"kind": "cancel", "text": "cancel",
                                         "clientRequestId": key}, schedule=False)

    if window == "before_pause":
        # The interaction is committed but the wait checkpoint is not.
        h.service.failpoints.arm("admit_action.after_interaction")
        with pytest.raises(CrashInjected):
            h.pump(rid)
        assert h.store(rid).pending_interaction(rid) is not None
        act("w-" + window)
        h.close()
        h = Harness(root=tmp_path / name)
    else:
        h.pump(rid)
        assert h.store(rid).pending_interaction(rid) is not None
        if window == "after_pause":
            act("w-" + window)
        elif window == "after_resume":
            act("w-" + window)
            h.service.failpoints.arm("reconcile.after_apply")
            with pytest.raises(CrashInjected):
                h.pump(rid)
            h.close()
            h = Harness(root=tmp_path / name)
        else:  # duplicate_after_restart
            decision = h.store(rid).pending_interaction(rid)
            act("w-dup")
            h.pump(rid)
            h.close()
            h = Harness(root=tmp_path / name)
            before = (len(h.store(rid).list_inputs(rid))
                      + len(h.store(rid).responses_for(decision["id"])))
            if reason == "response":
                h.respond(rid, decision, "semantic_choice",
                          {"requirement_id": "endpoint_semantics", "option_id": "half_open"},
                          key="w-dup")
            elif reason == "steering":
                h.service.submit_input(rid, {"kind": "steer", "text": "I meant closed intervals.",
                                             "clientRequestId": "w-dup"}, schedule=False)
            else:
                h.service.submit_input(rid, {"kind": "cancel", "text": "cancel",
                                             "clientRequestId": "w-dup"}, schedule=False)
            after = (len(h.store(rid).list_inputs(rid))
                     + len(h.store(rid).responses_for(decision["id"])))
            assert after == before

    h.pump(rid)
    store = h.store(rid)
    if reason == "response":
        assert store.get_run(rid)["goal_generation"] == 1
        assert len([e for e in store.events_after(rid, 0, 200)
                    if e["type"] == "semantic_change"]) == 1
    elif reason == "steering":
        assert store.get_run(rid)["goal_generation"] >= 1
        assert len([e for e in store.events_after(rid, 0, 200)
                    if e["type"] == "semantic_change"]) == 1
    else:
        assert store.get_run(rid)["status"] == "cancelled"
        assert len([e for e in store.events_after(rid, 0, 200)
                    if e["type"] == "cancelled"]) == 1
    h.close()


# ------------------------------------------------------------------ CR03 ordering
def test_later_resolve_supersede_and_cancel_unblock_ambiguity(tmp_path):
    h = Harness(root=tmp_path / "cr03")
    rid = h.create()
    h.pump(rid)
    h.answer_endpoint(rid)
    h.pump(rid)
    ambiguous = h.service.submit_input(rid, {
        "kind": "steer", "text": "Make them touch differently.", "clientRequestId": "amb",
    }, schedule=False)
    h.pump(rid)
    store = h.store(rid)
    assert store.get_input(ambiguous["inputId"])["status"] == "needs_disambiguation"
    decision = store.pending_interaction(rid)
    assert decision is not None and decision["kind"] == "semantics"
    # A later explicit answer resolves the ambiguity; it does not wait behind it.
    receipt = h.respond(rid, decision, "semantic_choice",
                        {"requirement_id": "endpoint_semantics", "option_id": "closed"},
                        key="resolve")
    assert receipt["status"] == "receipt"
    h.pump(rid)
    assert store.get_run(rid)["goal_generation"] == 2
    h.close()


def test_explicit_supersede_marks_earlier_terminal(tmp_path):
    h = Harness(root=tmp_path / "cr03-super")
    rid = h.create()
    h.pump(rid)
    h.answer_endpoint(rid)
    h.pump(rid)
    ambiguous = h.service.submit_input(rid, {
        "kind": "steer", "text": "Make them touch differently.", "clientRequestId": "amb2",
    }, schedule=False)
    h.pump(rid)
    later = h.service.submit_input(rid, {
        "kind": "steer", "text": "Use half-open; the earlier vague note is withdrawn.",
        "clientRequestId": "later", "supersedesInputId": ambiguous["inputId"],
    }, schedule=False)
    h.pump(rid)
    store = h.store(rid)
    assert store.get_input(ambiguous["inputId"])["status"] == "superseded"
    assert hash(store.get_input(ambiguous["inputId"])["original_hash"])
    assert later["status"] == "received"
    h.close()


def test_cancel_precedes_and_withdraws_pending(tmp_path):
    h = Harness(root=tmp_path / "cr03-cancel")
    rid = h.create()
    h.pump(rid)
    decision = h.store(rid).pending_interaction(rid)
    assert decision
    # A response is recorded, then cancellation wins before it is applied.
    receipt = h.respond(rid, decision, "semantic_choice",
                        {"requirement_id": "endpoint_semantics", "option_id": "half_open"},
                        key="cancel-race")
    h.service.submit_input(rid, {"kind": "cancel", "text": "stop", "clientRequestId": "c"},
                           schedule=False)
    h.pump(rid)
    store = h.store(rid)
    assert store.get_run(rid)["status"] == "cancelled"
    assert store.pending_interaction(rid) is None
    assert store.get_response(receipt["responseId"])["status"] == "conflict"
    assert store.get_run(rid)["goal_generation"] == 0
    assert all(i["status"] == "cancelled" for i in store.list_inputs(rid) if i["kind"] == "cancel")
    h.close()


def test_cancel_crash_restart_withdraws_pending(tmp_path):
    h = Harness(root=tmp_path / "cr03-cancel2")
    rid = h.create()
    h.pump(rid)
    assert h.store(rid).pending_interaction(rid)
    h.service.failpoints.arm("reconcile.after_apply")
    # Cancellation is accepted despite any stale generation and grants no effect scope.
    h.service.submit_input(rid, {"kind": "cancel", "text": "stop", "clientRequestId": "c2"},
                           schedule=False)
    with pytest.raises(CrashInjected):
        h.pump(rid)
    h.close()
    h2 = Harness(root=h.root)
    h2.pump(rid)
    store = h2.store(rid)
    assert store.get_run(rid)["status"] == "cancelled"
    assert store.pending_interaction(rid) is None
    h2.close()


# ------------------------------------------------------------------ projection
def test_external_edit_is_never_overwritten(tmp_path):
    store = ApplicationStore(tmp_path / "proj-store")
    run = store.create_run("w", "idea")
    blob = store.put_blob(b"int main(){return 0;}\n", kind="source")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "main.cpp").write_text("author external edit\n", encoding="utf-8")
    manager = ProjectionManager(checkout, store, managed=True)
    result = manager.apply(run["run_id"], "rev-9", [{
        "canonical_path": "main.cpp", "hash": blob, "size": 20, "kind": "source",
        "visibility": "author",
    }], {"main.cpp": None})
    assert result["state"] == "conflict"
    assert (checkout / "main.cpp").read_text(encoding="utf-8") == "author external edit\n"
    assert result["patchBlob"]
    assert store.get_projection_intent(result["intent"])["state"] == "conflict"


def test_partial_multi_file_projection_is_pending_not_complete(tmp_path):
    store = ApplicationStore(tmp_path / "proj-store2")
    run = store.create_run("w", "idea")
    one = store.put_blob(b"one\n", kind="source")
    two = store.put_blob(b"two\n", kind="source")
    files = [
        {"canonical_path": "a.txt", "hash": one, "size": 4},
        {"canonical_path": "b.txt", "hash": two, "size": 4},
    ]
    intent = store.begin_projection(run["run_id"], "rev-1", manifest=files,
                                    base_hashes={"a.txt": None, "b.txt": None})
    checkout = tmp_path / "checkout2"
    checkout.mkdir()
    (checkout / "a.txt").write_bytes(b"one\n")  # simulate crash after first member
    manager = ProjectionManager(checkout, store, managed=True)
    report = manager.reconcile(run["run_id"])
    assert report and report[0]["state"] == "pending"
    assert store.get_projection_intent(intent["id"])["state"] == "pending"


# ------------------------------------------------------------------ CR05 budget persistence
def test_crash_does_not_reset_budget_or_expiry(tmp_path):
    store = ApplicationStore(tmp_path / "budget-crash", clock=ManualClock())
    run = store.create_run("w", "idea")
    reservation = store.reserve_action(run["run_id"], action_id="x", attempts_limit=3)
    store.record_attempt(reservation["id"], kind="model", outcome="error")
    store.settle_reservation(reservation["id"], "exhausted")
    used = store.get_budget(run["run_id"])["model_attempts_used"]
    reopened = ApplicationStore(tmp_path / "budget-crash", clock=ManualClock())
    assert reopened.get_budget(run["run_id"])["model_attempts_used"] == used == 1
    assert json.loads(reopened.get_budget(run["run_id"])["settled_json"])
